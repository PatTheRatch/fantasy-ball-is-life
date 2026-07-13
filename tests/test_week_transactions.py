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
import json
import pathlib
from types import SimpleNamespace

import pytest

from backend.league import data_feed as feed

_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "mtransactions2_sample.json"


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


def _trade_payload():
    """A completed trade: the ACCEPT record has EMPTY items; the player-level
    items live on the linked TRADE_PROPOSAL (as confirmed by the live fixture)."""
    return {
        "transactions": [
            {  # proposal carries the player items (type TRADE, from/to team)
                "id": "tr0", "teamId": 1, "type": "TRADE_PROPOSAL", "status": "EXECUTED",
                "scoringPeriodId": 21, "proposedDate": 1_699_000_000_000,
                "items": [
                    {"type": "TRADE", "playerId": 101, "fromTeamId": 2, "toTeamId": 1},
                    {"type": "TRADE", "playerId": 102, "fromTeamId": 1, "toTeamId": 2},
                ],
            },
            {  # acceptance: empty items, links back to the proposal
                "id": "tr1", "teamId": 2, "type": "TRADE_ACCEPT", "status": "EXECUTED",
                "scoringPeriodId": 21, "processDate": 1_700_000_000_000,
                "relatedTransactionId": "tr0", "items": [],
            },
        ]
    }


def test_completed_trade_reconstructed_from_linked_proposal():
    rows = feed.week_transactions(_handles(_trade_payload()), scoring_period=21)
    trade_rows = [r for r in rows if r["action_type"] == "TRADE"]
    assert len(trade_rows) == 2
    # Each moved player is attributed to the RECEIVING team (toTeamId).
    got = {r["player"]: (r["team_name"], r["from_team_id"], r["to_team_id"]) for r in trade_rows}
    assert got["Player A"] == ("Alpha", 2, 1)  # 101: Beta -> Alpha
    assert got["Player B"] == ("Beta", 1, 2)   # 102: Alpha -> Beta
    assert all(r["related_transaction_id"] == "tr0" for r in trade_rows)
    # Date comes from the completion record (processDate), not the proposal.
    assert all(r["date"] == "2023-11-14" for r in trade_rows)


def test_trade_accepted_and_upheld_counts_once():
    payload = _trade_payload()
    payload["transactions"].append(
        {  # upheld after surviving veto -> must not double-count the proposal
            "id": "tr2", "teamId": 2, "type": "TRADE_UPHOLD", "status": "EXECUTED",
            "scoringPeriodId": 21, "processDate": 1_700_100_000_000,
            "relatedTransactionId": "tr0", "items": [],
        }
    )
    rows = feed.week_transactions(_handles(payload), scoring_period=21)
    assert len([r for r in rows if r["action_type"] == "TRADE"]) == 2  # 2 players, once


def test_trade_with_proposal_outside_window_is_skipped():
    payload = {
        "transactions": [
            {
                "id": "tr1", "teamId": 2, "type": "TRADE_ACCEPT", "status": "EXECUTED",
                "scoringPeriodId": 21, "relatedTransactionId": "proposed-last-week",
                "items": [],
            }
        ]
    }
    assert feed.week_transactions(_handles(payload), scoring_period=21) == []


def test_request_uses_mtransactions2_and_type_filter():
    handles = _handles(_mixed_payload())
    feed.week_transactions(handles, scoring_period=21, types={"FREEAGENT"})
    call = handles.league.espn_request.calls[0]
    assert call["params"] == {"view": "mTransactions2", "scoringPeriodId": 21}
    assert "x-fantasy-filter" in call["headers"]
    assert "FREEAGENT" in call["headers"]["x-fantasy-filter"]
    # FREEAGENT-only request must not drag proposals into the filter.
    assert "TRADE_PROPOSAL" not in call["headers"]["x-fantasy-filter"]


def test_trade_request_auto_includes_proposals_in_filter():
    handles = _handles(_trade_payload())
    feed.week_transactions(handles, scoring_period=21, types={"TRADE_ACCEPT"})
    sent = handles.league.espn_request.calls[0]["headers"]["x-fantasy-filter"]
    assert "TRADE_PROPOSAL" in sent  # needed to reconstruct trades
    assert "TRADE_ACCEPT" in sent


def test_transport_error_propagates_for_data_quality_signal():
    # An ESPN outage must be distinguishable from a quiet week, so the recap's
    # capture layer can mark transactions unavailable instead of silently empty.
    league = SimpleNamespace(
        espn_request=_RaisingEspnRequest(), player_map={}, teams=[]
    )
    handles = feed.ESPNHandles(league=league)
    with pytest.raises(RuntimeError):
        feed.week_transactions(handles, scoring_period=21)


def test_missing_transactions_key_is_empty():
    rows = feed.week_transactions(_handles({}), scoring_period=21)
    assert rows == []


@pytest.mark.skipif(not _FIXTURE.exists(), reason="live mTransactions2 fixture not captured yet")
def test_adapter_holds_against_live_fixture():
    """Golden test against a real (sanitized) week of ESPN transactions.

    Player/team maps aren't captured in the fixture, so names resolve to
    placeholders; this exercises filtering + trade reconstruction against the
    real JSON shape rather than checking exact names.
    """
    payload = json.loads(_FIXTURE.read_text())
    handles = _handles(payload, player_map={}, teams=[])

    rows = feed.week_transactions(handles, scoring_period=21)

    assert isinstance(rows, list)
    for row in rows:
        # Only executed player movement of the recap-relevant kinds survives.
        assert row["status"] == "EXECUTED"
        assert row["type"] in {"FREEAGENT", "WAIVER", "TRADE_ACCEPT", "TRADE_UPHOLD"}
        assert row["action_type"] in {"ADD", "DROP", "TRADE"}
        assert row["player_id"] is not None
        # Reconstructed trades must know both sides.
        if row["action_type"] == "TRADE":
            assert row["from_team_id"] is not None
            assert row["to_team_id"] is not None
            assert row["team_id"] == row["to_team_id"]
    # None of the excluded types leak through.
    leaked = {r["type"] for r in rows} & {"FUTURE_ROSTER", "DRAFT", "ROSTER", "TRADE_PROPOSAL"}
    assert not leaked
