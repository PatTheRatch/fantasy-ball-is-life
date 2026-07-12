"""Tests for the mTransactions2 adapter (feed.week_transactions).

The adapter replaces the broken safe_recent_activity() path. It reads ESPN's
mTransactions2 view through the league's authenticated request helper and
normalizes executed player movement into recap-facing rows.

Fixtures here are synthetic but modeled on the field names the installed
espn_api basketball client parses (teamId, type, status, scoringPeriodId,
processDate, bidAmount, items[].type/playerId) plus the documented trade fields
(fromTeamId/toTeamId, relatedTransactionId). They are NOT captured live; a
sanitized live sample should validate exact status enums and trade item shape
before trade-derived awards are trusted.
"""
from types import SimpleNamespace

import pytest

from backend.league import data_feed as feed


class _FakeEspnRequest:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def league_get(self, params=None, headers=None, extend=""):
        self.calls.append({"params": params, "headers": headers})
        return self.payload


class _RaisingEspnRequest:
    def league_get(self, params=None, headers=None, extend=""):
        raise RuntimeError("ESPN 500")


def _team(team_id, name):
    return SimpleNamespace(team_id=team_id, team_name=name)


def _handles(payload, *, player_map=None, teams=None):
    league = SimpleNamespace(
        espn_request=_FakeEspnRequest(payload),
        player_map=player_map or {101: "Player A", 102: "Player B", 103: "Player C"},
        teams=teams or [_team(1, "Alpha"), _team(2, "Beta")],
    )
    return feed.ESPNHandles(league=league)


# A realistic mixed payload spanning the transaction vocabulary.
def _mixed_payload():
    return {
        "transactions": [
            {  # executed free-agent add -> KEEP
                "id": "t1", "teamId": 1, "type": "FREEAGENT", "status": "EXECUTED",
                "scoringPeriodId": 21, "processDate": 1_700_000_000_000, "bidAmount": 0,
                "items": [{"type": "ADD", "playerId": 101}],
            },
            {  # executed waiver add + drop -> KEEP both
                "id": "t2", "teamId": 2, "type": "WAIVER", "status": "EXECUTED",
                "scoringPeriodId": 21, "processDate": 1_700_050_000_000, "bidAmount": 17,
                "items": [
                    {"type": "ADD", "playerId": 102},
                    {"type": "DROP", "playerId": 103},
                ],
            },
            {  # future roster / lineup-only -> DROP (wrong type)
                "id": "t3", "teamId": 1, "type": "FUTURE_ROSTER", "status": "EXECUTED",
                "scoringPeriodId": 21, "items": [{"type": "LINEUP", "playerId": 101}],
            },
            {  # draft record -> DROP (wrong type)
                "id": "t4", "teamId": 1, "type": "DRAFT", "status": "EXECUTED",
                "scoringPeriodId": 21, "items": [{"type": "ADD", "playerId": 101}],
            },
            {  # pending waiver -> DROP (wrong status)
                "id": "t5", "teamId": 2, "type": "WAIVER", "status": "PENDING",
                "scoringPeriodId": 21, "items": [{"type": "ADD", "playerId": 102}],
            },
        ]
    }


def test_keeps_only_executed_adds_and_drops():
    handles = _handles(_mixed_payload())
    rows = feed.week_transactions(handles, scoring_period=21)

    # t1 ADD, t2 ADD, t2 DROP == 3 movement rows; future/draft/pending excluded.
    assert len(rows) == 3
    kinds = sorted((r["type"], r["action_type"]) for r in rows)
    assert kinds == [("FREEAGENT", "ADD"), ("WAIVER", "ADD"), ("WAIVER", "DROP")]


def test_normalizes_team_player_date_and_bid():
    rows = feed.week_transactions(_handles(_mixed_payload()), scoring_period=21)
    by_player = {r["player"]: r for r in rows}

    assert by_player["Player A"]["team_name"] == "Alpha"
    assert by_player["Player A"]["action_type"] == "ADD"
    assert by_player["Player B"]["team_name"] == "Beta"
    assert by_player["Player B"]["bid_amount"] == 17
    # epoch-ms processDate -> ISO date string
    assert by_player["Player A"]["date"] == "2023-11-14"
    # stable, unique activity ids
    assert len({r["activity_id"] for r in rows}) == 3


def test_unknown_player_id_degrades_to_placeholder_not_crash():
    payload = {
        "transactions": [
            {
                "id": "t9", "teamId": 1, "type": "FREEAGENT", "status": "EXECUTED",
                "scoringPeriodId": 21, "items": [{"type": "ADD", "playerId": 999}],
            }
        ]
    }
    rows = feed.week_transactions(_handles(payload), scoring_period=21)
    assert len(rows) == 1
    assert rows[0]["player"] == "Unknown"


def test_completed_trade_uses_item_source_destination_teams():
    payload = {
        "transactions": [
            {
                "id": "tr1", "teamId": 0, "type": "TRADE_ACCEPT", "status": "EXECUTED",
                "scoringPeriodId": 21, "relatedTransactionId": "tr0",
                "items": [
                    {"type": "ADD", "playerId": 101, "fromTeamId": 2, "toTeamId": 1},
                    {"type": "ADD", "playerId": 102, "fromTeamId": 1, "toTeamId": 2},
                ],
            }
        ]
    }
    rows = feed.week_transactions(
        _handles(payload), scoring_period=21, types={"TRADE_ACCEPT"}
    )
    assert len(rows) == 2
    # teamId==0 -> owner derived from item destination (toTeamId) for an ADD.
    got = {r["player"]: r["team_name"] for r in rows}
    assert got == {"Player A": "Alpha", "Player B": "Beta"}
    assert all(r["related_transaction_id"] == "tr0" for r in rows)


def test_request_uses_mtransactions2_and_type_filter():
    handles = _handles(_mixed_payload())
    feed.week_transactions(handles, scoring_period=21, types={"FREEAGENT"})
    call = handles.league.espn_request.calls[0]
    assert call["params"] == {"view": "mTransactions2", "scoringPeriodId": 21}
    assert "x-fantasy-filter" in call["headers"]
    assert "FREEAGENT" in call["headers"]["x-fantasy-filter"]


def test_transport_error_degrades_to_empty_list():
    league = SimpleNamespace(
        espn_request=_RaisingEspnRequest(), player_map={}, teams=[]
    )
    handles = feed.ESPNHandles(league=league)
    assert feed.week_transactions(handles, scoring_period=21) == []


def test_missing_transactions_key_is_empty():
    rows = feed.week_transactions(_handles({}), scoring_period=21)
    assert rows == []
