# D-09 · Live-check findings — can the D-08 fixture actually drive V1?

**Date:** 2026-09-10 · **Bite:** D-09 (characterization oracle + solver-cap semantics)
**Verdict:** Yes — but the fixture needed **three fixes** before it could, and all
three were invisible to every test that existed.

This is the reconnaissance half of D-09. The ticket's mandated first act was:

> construct the frame and confirm V1's `OptimizeLineup` actually accepts
> `projections_df` — the one thing the D-08 review could not verify, and
> everything downstream depends on it.

It does. But confirming it meant actually running the solver, and running the
solver broke the fixture three times. This document records each one, because
each is a *silent* failure: the fixture parsed, passed all 30 of its own tests,
and was unusable as optimizer input.

---

## Method

V1 lives on `main`. A scratch worktree was used so `main` is never mutated:

```bash
git worktree add -f /tmp/d09-probe/v1main main
cp -r tests/fixtures/projections /tmp/d09-probe/v1main/tests/fixtures/
```

Then, with the league context injected locally (the same stub `tests/conftest.py`
uses) and ESPN stubbed, construct and solve:

```python
_LEAGUE_CTX.set(LeagueContext(league_id="t", slug="t", name="T", espn_league_id=123456,
    espn_season=2026, swid="s", espn_s2="s2", timezone="America/New_York"))

class FakeLeague:          # only .draft and .teams are touched at construction
    draft = []; teams = []

opt = ol.OptimizeLineup(
    projections_df=pd.DataFrame(adapter.to_v1_columns(adapter.load_canonical())),
    minimum_game_threshold=20, value_col="$",
)
opt.optimize_roster("PTS")
```

---

## Confirmed: injection works, and there is a second injection path

`OptimizeLineup.__init__` takes **two** injection arguments, and neither was
documented before this probe:

```python
projections_df:   Optional[pd.DataFrame] = None,
projections_rows: Optional[list] = None,       # takes PRECEDENCE over projections_df
```

```python
if projections_rows is not None:
    projections_df = _projections_to_optimizer_df(projections_rows)
self._projections_df = projections_df
```

`projections_rows` is the **V2 consumer shape** — the adapter should feed that
one when D-12 ports the optimizer, since a list of row objects is what a domain
layer would carry. `projections_df` is the lower-level escape hatch.

**Injection is sufficient for the projections.** `BBM_PROJECTIONS_PATH` is never
read when a frame is supplied, which settles D-08's open question: the CSV never
needs to be Excel, and no dependency is added.

## Requirement the ticket did not know about: a league object is also required

Construction is not injection-only. `process_draft_data()` immediately does:

```python
draft_data = [(pick.playerName, pick.bid_amount, pick.team.team_name)
              for pick in self.league.draft]
```

and `self.league` comes from `get_cached_my_league(...)` — **a live ESPN fetch
(four requests) by default.** Offline construction therefore needs both an
injected `LeagueContext` *and* a stubbed `get_cached_my_league`. A stub with just
`.draft = []` and `.teams = []` is enough for the golden-capture path; anything
that needs real league membership (roster rules, team names) will need more.

**This is a D-09 precondition, not a footnote.** Any oracle harness has to
stub the network or it will not run in CI.

---

## Three fixture defects, each found only by running the solver

### 1. No players at `$1` — the solver requires them

```
ValueError: `minimum_value_players`=3 but only 0 player(s) with $==1 remain
after filtering (minimum_game_threshold=20).
```

`_validate_pool_feasibility` requires `minimum_value_players` (default 3)
players priced at **exactly $1**, and the LP constraint is an equality:

```python
constraints.append(cp.sum(player_vars[player_data_df[self.value_col] == 1])
                   == self.minimum_value_players)
```

D-08's generator decayed exponentially (`70 * 0.977**rank`) and bottomed out at
**$1.67** — never reaching the floor. A real auction has a $1 tail; modelling one
is both more realistic and what makes the fixture usable.

**Fixed:** the last 12 ranked players are priced at $1.00. Locked by
`test_dollar_ladder_reaches_the_one_dollar_floor`.

### 2. Guards labelled `'G'` — not a position V1 matches

```
ValueError: No eligible players remain at position 'PG' after filtering
(minimum_game_threshold=20).
```

V1's vocabulary is exactly `('C', 'PG', 'SG', 'SF', 'PF')`:

```python
for position in ('C', 'PG', 'SG', 'SF', 'PF'):
    available = int(player_data_df['Pos'].str.contains(position).sum())
    if available < 1: raise ValueError(...)
```

**V1 checks positions in two places with different rules — worth stating
precisely, because this doc is D-12's handoff:**

| Path | Rule for `C` | Rule for `PG`/`SG`/`SF`/`PF` |
|---|---|---|
| `_validate_pool_feasibility` | `str.contains('C')` | `str.contains(code)` |
| LP position constraint | `Pos == 'C'`, capped `(1, 3)` | `str.contains(code)`, min 1 |

So the feasibility loop treats `C` the same as the others (substring), while the
LP objective distinguishes it by equality and caps it at 3. For this fixture's
vocabulary the two rules select the identical set — nothing else contains `"C"`
as a substring — which is why the defect surfaced as a `PG` failure and not a `C`
one. But a future label like `"C PF"` would satisfy feasibility and then be
treated as a centre by the cap, so the distinction is real and a port must keep
both rules.

`str.contains('PG')` does **not** match `'G'`. Labelling guards `'G'` — the
obvious choice, and what the fixture did — makes `PG` match zero players.

**Fixed:** the adapter emits `PG`, not `G`. Locked by
`test_adapter_positions_use_v1_vocabulary`, which mirrors V1's exact matching
rule per position.

### 3. The position vocabulary is coupled to the LP constraints

The solver's position constraints are not uniform, which constrains what labels
are *safe*:

```python
'C':  Pos == 'C'               (min 1, max 3)   ← equality, and capped
'PG': Pos.str.contains('PG')   (min 1)
'SG': Pos.str.contains('SG')   (min 1)
'SF': Pos.str.contains('SF')   (min 1)
'PF': Pos.str.contains('PF')   (min 1)
```

- `C` is capped at **3**, so it cannot be used as a catch-all label.
- The four `str.contains` codes must not be substrings of each other; distinct
  two-letter codes satisfy this, multi-position strings (`"PG SG"`) remain safe.

Recorded so D-12 does not rediscover it when porting the constraints.

---

## Result: the oracle is viable

With the three fixes in place, the unmodified V1 solver produces a real optimum
from the fixture:

```
optimize_roster('PTS') -> DataFrame in 0.07s
PTS: 744.275      Cost: 200.0      shape: (13, 33)

              Name Pos     $    PTS   REB   AST
   Synthetic 124  SF   1.0  10.71  3.86  1.68
   Synthetic 168  SF   1.0   9.72  2.27  1.75
   Synthetic 102  SF   1.0  11.01  2.17  1.92
   Synthetic 087   C  18.0  15.74  9.99  2.49
   Synthetic 171  PG   7.0  18.09  3.47  3.58
   Synthetic 133  PG  31.0  19.01  3.43  4.76
   Synthetic 164  PG  24.0  19.64  3.79  4.26
   Synthetic 192  PG  34.0  20.48  3.34  4.30
   Synthetic 157  PG  25.0  19.24  4.30  5.04
   Synthetic 147  SF   4.0  17.42  3.46  2.50
   Synthetic 186  PG  21.0  19.72  4.12  5.30
   Synthetic 050  PF  14.0  15.90  8.48  2.65
   Synthetic 074  SG  19.0  15.97  3.78  3.15
```

Sanity, not just success: the budget is spent exactly ($200.00), the floor
constraint is honoured (three $1 players), the position minimums are met, and
the roster is *coherent* — the centre leads rebounds (9.99) and the guards lead
assists (5.30). A fixture that solved but produced nonsense would be worse than
one that failed loudly.

## What this costs D-08's claims

D-08 was reviewed and merged on the claim that the fixture is a valid oracle
input. That claim was **untested against the real solver** and was, in fact,
false in three ways. The D-08 tests were structurally correct — columns, shapes,
determinism, makes-vs-attempts — and none of them could see any of this, because
none of them ran V1.

The lesson worth carrying: **a fixture is only proven by its consumer.** D-08's
review correctly flagged that "injectable into V1" was the one thing it could not
verify; this probe is the verification, and it took three rounds.

## Open for the capture half of D-09

- Solver-cap semantics are **not** yet characterized. `SOLVER_TIME_LIMIT_SECONDS=8`
  exists because real MC-derived targets took 8–24s unbounded; what a *timeout*
  returns versus an *infeasible* solve is still undocumented. §6 item 3.
- **Determinism: measured, and it holds — for this problem.** Five consecutive
  solves produced a byte-identical roster (same 13 names, same order), the same
  objective (744.275), and the same cost (200.00), in 0.038–0.044s. So goldens
  on *this* fixture are safe to pin.
  Two caveats, both real risks not yet ruled out:

  1. **Ties.** This shows determinism on a problem with no *visible* ties. A
     different category or a tighter budget could admit equal-objective optima
     and return any of them.
  2. **Solver-internal nondeterminism under the cap — the sharper risk.** This is
     a binary integer program. If a harder problem reaches
     `SOLVER_TIME_LIMIT_SECONDS`, the returned incumbent depends on
     branch-and-bound timing and is genuinely nondeterministic *even with no
     objective ties at all*. Multithreaded B&B can likewise return different
     equal-objective optima run-to-run. Naming "ties" alone would understate it.

  Mitigation for both is the same: the capture step asserts **objective and cost**
  stability across N runs, and treats the exact roster as stable-only-if-proven
  for that specific problem.
- `optimize_roster` ran in **0.04–0.07s** here — far inside the 8s cap. The cap
  path needs a deliberately hard problem to exercise (large pool, many
  categories, or MC-derived targets as the original bug had), not this fixture at
  rest. Capture must construct one; the fixture as-is will never reach the cap.
- Only `PTS` has been solved. The other eight categories and the MC-target path
  are uncharacterized.
