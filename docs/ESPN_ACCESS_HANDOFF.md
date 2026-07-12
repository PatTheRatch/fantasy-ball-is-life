# ESPN Fantasy Basketball — Access Handoff

This document explains how to connect to and pull data from my ESPN fantasy
basketball league, so another project (e.g. a larger dashboard) can reuse the
same approach. It is distilled from the working `PatriotGames` codebase
(`config.py`, `data_feed.py`, `fantasy.py`, `api.py`).

---

## 1. TL;DR

- The data source is **ESPN's fantasy API**, accessed through the open-source
  **`espn-api`** Python package (`from espn_api.basketball import League`).
- You need **4 things** to connect: `league_id`, `season` (year), and — for a
  private league — two browser cookies: `SWID` and `ESPN_S2`.
- My league:
  - `LEAGUE_ID = 3853870`
  - `SEASON = 2026` (this is the **2025–26** NBA season; ESPN labels it by the
    ending year)
  - Scoring format: **9-category head-to-head** (H2H Cats)
- The 9 categories are: `PTS, REB, AST, STL, BLK, 3PM, FG%, FT%, TO`
  (TO = turnovers, where **lower is better** — see the gotchas section).

---

## 2. Credentials

### What you need
| Value | Where it comes from | Required? |
|-------|--------------------|-----------|
| `ESPN_LEAGUE_ID` | The `leagueId=` in your ESPN league URL | Yes |
| `ESPN_SEASON` | Ending year of the season (2026 for 2025–26) | Yes |
| `ESPN_SWID` | Browser cookie, looks like `{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}` | Only for **private** leagues |
| `ESPN_S2` | Browser cookie, a long URL-encoded string | Only for **private** leagues |

### How to get SWID and ESPN_S2
1. Log into [fantasy.espn.com](https://fantasy.espn.com) in a desktop browser.
2. Open DevTools → **Application** (Chrome) or **Storage** (Firefox) → **Cookies**
   → `https://fantasy.espn.com`.
3. Copy the values of the `SWID` and `espn_s2` cookies.
   - `SWID` includes the surrounding curly braces `{ ... }` — keep them.
   - `espn_s2` is long; copy the whole thing.

These cookies act as your login. They eventually expire (re-grab them if calls
start returning 401/unauthorized). If the league is **public**, you can omit both.

### How the code reads them
Credentials are read from environment variables, with a fallback default for the
league id/season. From `config.py`:

```python
LEAGUE_ID: int = int(os.getenv("ESPN_LEAGUE_ID", "3853870"))
SEASON: int = int(os.getenv("ESPN_SEASON", "2026"))
SWID = os.getenv("ESPN_SWID", None)
ESPN_S2 = os.getenv("ESPN_S2", None)
```

Recommended for the new project: put these in a `.env` (and load with
`python-dotenv`) or export them in the shell. **Never commit the cookie values
or API keys to git.**

```bash
# .env  (example — do not commit)
ESPN_LEAGUE_ID=3853870
ESPN_SEASON=2026
ESPN_SWID={XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}
ESPN_S2=AEB...long...string
```

---

## 3. Install

```bash
pip install -U espn-api pandas numpy python-dateutil pytz rapidfuzz
```

`espn-api` is the only piece strictly required to talk to ESPN. The others are
used by my data-shaping helpers.

---

## 4. Minimal connection

The core connection is a single object:

```python
from espn_api.basketball import League

league = League(
    league_id=3853870,
    year=2026,
    espn_s2=ESPN_S2,   # None is fine for public leagues
    swid=SWID,         # None is fine for public leagues
)
```

That `league` object is the gateway to everything: teams, rosters, box scores,
matchups, settings, and transactions.

In my codebase this is wrapped in `data_feed.connect()`, which returns an
`ESPNHandles` dataclass holding the `League`. There is also a `MyLeague` subclass
(in `fantasy.py`) that adds season-long analytics on top of `League`.

---

## 5. What you can pull (the useful surface area)

Everything below comes from the live `league` object. Column names in the tables
are the ones my helpers produce — your dashboard can reshape as needed.

### League settings / metadata
```python
league.settings.name                 # league name
league.settings.team_count
league.settings.scoring_type         # e.g. "H2H_CATEGORY"
league.settings.reg_season_count     # number of regular-season matchup weeks
league.settings.playoff_team_count
league.settings.acquisition_budget   # FAAB budget
league.currentMatchupPeriod          # the current matchup week number
```

### Teams & standings
```python
for t in league.teams:
    t.team_id, t.team_name, t.wins, t.losses, t.ties, t.standing
    t.roster            # list of player objects
    t.acquisitions, t.trades, t.drops
```

### Rosters & player stats
Each `player` on `team.roster` exposes:
```python
player.name
player.proTeam
player.injuryStatus           # e.g. "ACTIVE", "OUT", "DAY_TO_DAY"
player.eligibleSlots          # position eligibility
player.playerId
player.stats                  # dict keyed by stat window (see below)
player.schedule               # dict of upcoming/past games with dates
```

**Important — the stats dict keys are season-prefixed.** For the 2026 season:
- `player.stats["2026_total"]` — season totals/averages
- `player.stats["2026_last_15"]` — trailing 15-day window
- `player.stats["2026_last_30"]` — trailing 30-day window

Each entry has an `"avg"` sub-dict with per-game stats:
`PTS, BLK, AST, STL, OREB, DREB, 3PM, FTA, FTM, FGM, FGA, TO`.
Note **REB is not stored directly** — compute it as `OREB + DREB`.

`player.schedule` is used to count how many games a player has left in a given
date window (drives projections):
```python
games_this_week = sum(
    week_start <= pd.to_datetime(g["date"]).normalize() <= week_end
    for g in player.schedule.values()
)
```

### Box scores / scoreboard (current and past weeks)
```python
matchups = league.box_scores(matchup_period=week_number)
for m in matchups:
    m.home_team.team_name, m.away_team.team_name
    m.home_stats, m.away_stats        # dict: stat -> {"value": ...}
```
`box_scores` works for the current and completed weeks. For future weeks use
`league.scoreboard(week)` (no live stat values yet).

### Transactions (adds / drops / trades / waivers)
```python
acts = league.recent_activity(size=500)
for a in acts:
    a.date          # epoch ms timestamp
    a.actions       # list of (team_obj, action_type, player_name, ...) tuples
    a.bid_amount    # FAAB bid, if applicable
```
`action_type` values include `WAIVER ADDED`, `FA ADDED`, `DROPPED`, `TRADED`.

> Gotcha: `league.recent_activity()` sometimes 404s. My fallback hits the raw
> endpoint directly with the same cookies — see `safe_recent_activity()` in
> `data_feed.py`:
> ```
> https://fantasy.espn.com/apis/v3/games/fba/seasons/{year}/segments/0/leagues/{league_id}?view=kona_league_communication
> ```

---

## 6. League-specific gotchas (read this)

These tripped me up; bake them into the new project.

1. **Turnovers (TO) are "lower is better."** When comparing/scoring categories,
   invert TO (e.g. negate it) so the win/loss logic treats fewer turnovers as a
   win. My box-score loader stores TO as a negative value for exactly this
   reason.

2. **FG% / FT% must be derived, not summed.** When aggregating a team's
   projected week, sum the makes and attempts (FGM/FGA, FTM/FTA) first, then
   compute `FG% = FGM/FGA` and `FT% = FTM/FTA`. Never average the percentages.

3. **REB = OREB + DREB.** ESPN stores offensive and defensive rebounds
   separately in the `avg` dicts.

4. **`currentMatchupPeriod` can exceed the real schedule length** during
   playoffs / championship week. Clamp week numbers to the weeks that actually
   exist in the schedule before requesting them, or you'll get `KeyError`. See
   `MyLeague.effective_current_week` and the clamping logic in `api.py`'s
   power-rankings endpoint.

5. **Season label vs. calendar year.** `SEASON = 2026` means the 2025–26 NBA
   season. The stat-window keys are prefixed with that same year
   (`"2026_last_15"`).

6. **Matchup week → calendar date mapping is hardcoded.** ESPN's week boundaries
   don't come back cleanly per league, so I maintain a dict
   `MATCHUP_WEEKS_2025_26` in `data_feed.py` mapping week number → `{start, end}`
   ISO dates (weeks 1–22, including an extended All-Star week 17 and playoff
   weeks 20–22). If your dashboard needs "which week is it" or "what dates does
   week N cover," copy that dict. It will need updating each season.

7. **Private-league cookies expire.** If previously-working calls start failing
   with auth errors, re-pull `SWID` / `ESPN_S2` from the browser.

8. **Player name matching across sources is fuzzy.** When joining ESPN players
   to external projection files (e.g. Basketball Monster), names don't match
   exactly. I normalize (strip accents/punctuation, lowercase) and use
   `rapidfuzz` fuzzy matching (`add_bbm_projections`, `fuzzy_map_names`). Only
   relevant if you merge in outside projection data.

---

## 7. Suggested integration paths for the new dashboard

Pick whichever fits your architecture:

### Option A — Import the data layer directly (Python dashboard)
Reuse `data_feed.py` / `fantasy.py` as-is. They already return clean pandas
DataFrames:
- `connect()` → handles
- `teams_df(h)`, `standings_df(h)`
- `rosters_df(h, on_date)`, `get_current_rosters(h, ...)`
- `get_current_scoreboard(h, scoring_period=...)`
- `get_projected_scoreboard(h, current_matchup_period=...)`
- `transactions_df(h, start, end)`
- `MyLeague(...).get_universe_wins(weeks=[...])` for all-play / power-ranking data

### Option B — Call the existing FastAPI service (any frontend)
`backend/api/main.py` already exposes HTTP endpoints over the data layer.
Run it with:
```bash
uvicorn backend.api.main:app --host 127.0.0.1 --port 8000 --reload
```
Then GET/POST JSON. Most useful endpoints for a dashboard:
- `GET /league/settings`
- `GET /league/teams`, `GET /league/standings`
- `GET /scoreboard/current?scoring_period={week}`
- `GET /projected-scoreboard?current_matchup_period={week}&projections=BBM`
- `GET /power-rankings?weeks=1,2,3`
- `GET /season-stats?weeks=1,2,3`
- `GET /transactions?start=YYYY-MM-DD&end=YYYY-MM-DD`

(The AI commentary endpoints additionally require an `ANTHROPIC_API_KEY` env var;
those are optional for raw data.)

### Option C — Talk to ESPN directly (minimal dependency)
If you only need raw data and want to skip my helpers, just use `espn-api`'s
`League` object (section 4) and read the fields in section 5.

---

## 8. Quick smoke test

```python
import os
from espn_api.basketball import League

league = League(
    league_id=int(os.getenv("ESPN_LEAGUE_ID", "3853870")),
    year=int(os.getenv("ESPN_SEASON", "2026")),
    espn_s2=os.getenv("ESPN_S2"),
    swid=os.getenv("ESPN_SWID"),
)

print("League:", league.settings.name)
print("Teams:", [t.team_name for t in league.teams])
print("Current week:", league.currentMatchupPeriod)
print("Scoring:", league.settings.scoring_type)
```

If you see your league name and teams printed, you're connected. If you get an
auth error on a private league, re-check `SWID` / `ESPN_S2`.

---

## 9. Security note
- Treat `SWID`, `ESPN_S2`, and any `ANTHROPIC_API_KEY` as secrets. Keep them in
  environment variables / a `.env` that is gitignored — never hardcode them in
  source or paste them into shared docs.
```
