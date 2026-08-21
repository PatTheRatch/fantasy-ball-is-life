# S1-03 · Live check: `matchupPeriods` — findings

**Date:** 2026-08-21
**Method:** constructed `espn_api.basketball.League` against the live
Patriot Games league (ESPN id 3853870) for seasons 2025 (completed) and 2026
(upcoming), then inspected `settings._raw_schedule_settings`.

## What the design doc got right

- **`matchupPeriods` is populated** for basketball leagues. Confirmed on both
  seasons. The bracket access in `espn_api/base_settings.py:5` does not raise.
- **Keys are strings.** JSON object keys — cast on read. Confirmed: every key
  in the live payload is a `str`.
- **Values are `list[int]`.** Confirmed.

## What the design doc's example got wrong

The "headline finding" used a *representative* payload:

```python
matchup_periods : {'1': [1, 2, 3, 4, 5, 6], '2': [7, 8, 9, 10, 11, 12, 13]}
```

That is a **weekly** league — each matchup period spans ~6–7 scoring periods.
Patriot Games is not that. Live data:

```json
{
  "matchupPeriodCount": 17,
  "matchupPeriodLength": 1,
  "matchupPeriods": {"1": [1], "2": [2], "…": ["…"], "20": [20]},
  "periodTypeId": 2,
  "playoffMatchupPeriodLength": 1,
  "playoffTeamCount": 6
}
```

`matchupPeriodLength: 1` means the mapping is **1:1** — each matchup period
contains exactly one scoring period. The design's "join to derive the calendar"
still works, but the "many scoring periods per matchup" picture is wrong for
this league. The mapping density is driven by `matchupPeriodLength`, which
must be read and honoured, not assumed.

## The open questions, now answered

| Question | Answer |
|---|---|
| Do playoff/championship periods appear in `matchupPeriods`? | **Yes.** 2025: 20 periods = 17 regular + 3 playoff. 2026: 22 = 19 + 3. |
| How does the All-Star break appear? | **As a gap**, not a period. The pro schedule's scoring-period dates jump 7 days (scoring period 115 → 122, 2026-02-13 → 2026-02-20). Days with no games consume no scoring-period id. |
| Is the shape stable across seasons? | Structurally yes (`matchupPeriodLength` stays 1), but `matchupPeriodCount`, `playoffTeamCount`, and `playoffSeedingRule` change year to year (e.g. 17→19 regular matchups, 6→7 playoff teams). |

## Implication for S1-06 (fantasy core schema)

- `matchup_periods` must be modelled as `matchup_period_id → [scoring_period_id]`
  with **no assumption that the list length is 1 or >1** — read
  `matchupPeriodLength` and store it.
- Playoff periods live in the same mapping as regular-season periods; the
  split is `matchupPeriodCount` (regular) vs the remainder (playoff), so
  `matchup_periods` needs a `kind` (regular/playoff) derived from index > count.
- The All-Star break is a **gap in scoring-period dates**, not a row in the
  matchup-period mapping — finality/status logic must not assume contiguous
  scoring periods.
- The hardcoded `MATCHUP_WEEKS_2025_26` in V1 (22 hand-typed week ranges) is
  confirmed unnecessary: this mapping + `proGamesByScoringPeriod` dates gives
  the calendar, and the "no hardcoded season calendars" non-negotiable is
  satisfiable.

## Fixture

`tests/providers/fixtures/espn_schedule_settings.json` — the raw
`scheduleSettings` for seasons 2025 and 2026, with the matching
shape-locking tests in `tests/providers/test_matchup_periods_fixture.py`.
