"""CLI argument + environment handling (hermetic — no DB, no ESPN).

The parts of the CLI that bite in the dark: credentials cannot arrive via
``argv``, a missing credential is named without echoing its value, and the
credential flags cannot be added back later for convenience.
"""

from __future__ import annotations

import pytest

from backend.platform.settings import SettingsError
from scripts.sync_league import build_parser, load_config, main


def test_parser_has_no_credential_flags() -> None:
    parser = build_parser()
    for flag in ("--espn-s2", "--swid", "--espn-swid", "--espn-s2-secret", "--password"):
        with pytest.raises(SystemExit):
            parser.parse_args(["--season", "2026", flag, "x"])


def test_parser_rejects_a_secret_positional() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--season", "2026", "SECRET"])


def test_missing_credential_names_the_variable() -> None:
    with pytest.raises(SettingsError) as excinfo:
        load_config(
            {
                "FCP_ESPN_ESPN_S2": "s2",
                "FCP_ESPN_LEAGUE_ID": "1",
                "DATABASE_URL": "url",
            }
        )
    assert "FCP_ESPN_SWID" in str(excinfo.value)


def test_missing_credential_error_does_not_leak_values() -> None:
    # The error names the variable; it never echoes a credential that *was* set.
    with pytest.raises(SettingsError) as excinfo:
        load_config(
            {
                "FCP_ESPN_SWID": "{SUPER_SECRET_SWID}",
                "FCP_ESPN_ESPN_S2": "{SUPER_SECRET_S2}",
                "DATABASE_URL": "url",
            }
        )
    msg = str(excinfo.value)
    assert "FCP_ESPN_LEAGUE_ID" in msg
    assert "{SUPER_SECRET" not in msg


def test_load_config_reads_all_four_from_environment() -> None:
    conn, url = load_config(
        {
            "FCP_ESPN_SWID": "{SWID}",
            "FCP_ESPN_ESPN_S2": "{S2}",
            "FCP_ESPN_LEAGUE_ID": "3853870",
            "DATABASE_URL": "postgresql://example",
        }
    )
    assert conn.league_id == "3853870"
    assert conn.swid == "{SWID}"
    assert conn.espn_s2 == "{S2}"
    assert url == "postgresql://example"


def test_main_missing_credential_exits_nonzero(capsys) -> None:
    code = main(["--season", "2026"], environ={})
    captured = capsys.readouterr()
    assert code == 2
    assert "required setting" in captured.err  # names a variable, never a value
