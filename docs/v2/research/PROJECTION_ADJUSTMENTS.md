# Manual projection adjustments — external research + verification

**Source:** ChatGPT (with browsing), commissioned 2026-08-22 to answer
[`BACKLOG.md`](../BACKLOG.md) open question #5 and
[`schema/05-projections.md`](../schema/05-projections.md) open question #1
(*does raising projected minutes scale dependent stats?*).

**Status:** external research. §0 is the verification and the part that changes
our design; §1 is the memo, condensed with nothing load-bearing dropped.

---

## §0 · Verification against our schema

Checked against [`schema/05-projections.md`](../schema/05-projections.md) and
charter Decisions 3, 4, 22, 24.

### Where the memo confirms what we already decided

| Memo recommendation | Our design | Verdict |
|---|---|---|
| Base projection + **sparse user overlay**, composed at read time — never fork the whole set on an edit | `projection_sets` (immutable) + `projection_adjustments` (deltas composed at READ time) + `projection_freezes` — schema §"the three tables", charter D24 | **Already decided.** Independent agreement. |
| A minutes edit means *"I disagree with your opportunity assumption"*, so scale volume from the underlying rate | Open question #1's own recommendation: *"scale rate stats proportionally by default with an explicit opt-out, because 'more minutes' is what a manager means"* | **Confirms our prior recommendation.** |
| Store the user's *assertion*, not the computed result, so model improvements keep flowing underneath | Schema: *"a manager who has hand-adjusted forty players must be able to switch base source (BBM → FCP model) and keep those adjustments. Forking welds the edits to one base."* | **Our rationale is stronger** — it covers switching source entirely, not just base refresh. |
| Keep an immutable record of what drove a decision | `projection_freezes` + `adjustment_ids` — *"what exactly was I looking at when I drafted him at $34"* | **Already decided.** No conflict: freezes capture at decision points, they do not make composition static. |

The composition model the memo recommends is also **implementable as-is against
our schema**, which was not guaranteed. `projection_rows` already carries
`minutes_per_game` and `games`, and stores shooting as makes *and* attempts
with the comment *"makes AND attempts. never a bare percentage."* Without that
denominator the memo's model would have had nothing to scale.

`adjustment_mode` already supports `absolute | multiplier | delta`. The memo
argues for **absolute as the default** for minutes: a manager saying "he plays
34" asserts a value, not a standing +25% bullishness, and the three modes
diverge the moment the base moves (27 base → 34 absolute, 33 additive, 33.75
multiplicative). Recommend absolute as the default with the other modes
available; nothing in the schema needs to change.

### The gap it fills — and the bug we would have shipped

Schema line 182 says composition *"applies the delta and lets dependent stats
scale."* That sentence is under-specified in a way that produces a wrong
answer, because **not every dependent stat scales.**

Naive proportional scaling of every field at 1.25× gives:

```
FG%  .450  ×1.25  →  .5625      ← claims more minutes make him a better shooter
```

The correct rule treats efficiency and volume differently:

```
scale:        fga, fgm, fta, ftm, tpa, tpm, pts, reb, ast, stl, blk, tov
hold:         the RATIOS — fg%, ft%, tp% are derived, never scaled
result:       10.5/18.3 = .573   →   13.125/22.875 = .573   ✓
```

Because we store makes and attempts rather than bare percentages, this falls
out for free: scale both components and the ratio is invariant. A schema that
stored `fg_pct` directly could not express it. **The composition rule must scale
components and derive percentages, never scale a percentage.**

### A distinction the memo misses: `games` ≠ `minutes_per_game`

Our schema has two adjustable opportunity fields, and they compose at
*different levels*:

- `minutes_per_game` scales **per-game** volume stats.
- `games` scales **season aggregates** and must leave per-game rates alone.

A manager dropping a player 82 → 65 games for injury risk is not saying he
plays fewer minutes per night. Applying one rule to both fields double-scales
season totals. The memo only ever discusses minutes, so this is ours to get
right.

### Worth adopting: stale-adjustment detection

The memo proposes recording the base value an override was created against:

```json
{ "field": "minutes_per_game", "value": 34,
  "base_value_at_creation": 28, "base_projection_set_id": "..." }
```

so the UI can say *"your projection 34, current model 33, originally 28 — your
adjustment is now +1"* and offer keep / use-model / remove. `projection_adjustments`
does not carry this today. It is cheap (two nullable columns), it makes a
stale October opinion visible instead of silently authoritative, and it fits
our "no silent degradation" non-negotiable. Recommend adding it when the
projections slice is cut — not a schema change to make speculatively now.

### Evidence quality — read the memo's citations with care

The memo is honest that its Basketball Monster findings are **inferred, not
documented**. What is established: BBM exposes *Custom Daily Minutes* and
*Custom Projections* as separate features, and displays a per-minute "Skill
Level". What is *not* established: the actual formula, or whether scaling is
strictly linear. It found no evidence at all that Hashtag exposes minute
overrides, and correctly warns against citing Hashtag as precedent. DARKO/DRIP
are architectural analogies, not fantasy-UI precedent.

That is the right level of confidence for a decision we had already reached on
our own reasoning. It corroborates; it does not prove.

---

## §1 · The memo, condensed

### Executive summary

There is a useful distinction between **projection engines** and **projection
editors**. Basketball Monster exposes both *Custom Projections* and a separate
*Custom Daily Minutes* feature, and describes a player's "Skill Level" in
per-minute terms — strong evidence it separates playing time from per-minute
production, though its public docs never specify which statistics recalculate
when minutes change.

Hashtag Basketball publishes projections containing MPG alongside FG%, FT%,
attempts/makes and counting stats, but has no documented equivalent of Custom
Daily Minutes. Its visible "multipliers" change the *valuation weight* of
categories, not the underlying projection. BLEND7/BLEND14 are blends of whole
projection lines, not user minute overrides.

DARKO is useful architecturally rather than as UX precedent: it estimates
underlying abilities/rates independently and applies playing time separately
when converting ability into expected production. That separation favours
treating "34 minutes instead of 28" as an adjustment to *opportunity*, not six
unrelated overrides to points, rebounds, assists.

**Recommendation: base projection + sparse user overlay.** Minutes is a
first-class override. Changing it rescales volume from the underlying rate
while leaving efficiency rates unchanged. Users may still explicitly override
individual rates when they disagree about more than playing time.

### Basketball Monster

Exposes three relevant concepts — *Projections*, *Custom Daily Minutes*,
*Custom Projections* — plus *Import Bulk Projections*. The separation implies
BBM distinguishes "I think he'll play different minutes" from "I disagree with
his projection," rather than making every minutes change a rewrite of the whole
line. BBM also displays *Skill Level*, showing how players "produce on a
per-minute basis," and its projection-range methodology explicitly adjusts
expected output according to different minutes scenarios.

**Inferred, not documented:** Custom Daily Minutes almost certainly recalculates
volume from the per-minute projection (`0.50 pts/min × 30 min = 15`). It would
make little sense for the feature to change displayed minutes and leave a
20-minute player's 10 points at 10 when moved to 35. Whether the scaling is
strictly linear, or whether usage adjusts nonlinearly at large minute changes,
cannot be established publicly.

*Custom Projections* appears to be a different mechanism — supplying alternate
projected **values** (overrides), not deltas, consistent with the presence of a
bulk import. Field-level merge behaviour (does an unpopulated custom stat fall
back to BBM's?) is unknown.

### Percentages

A fantasy FG% is not an independent counting stat; it is `FGM/FGA`. Hashtag
exposes this structure directly, e.g. `FG% .573 (10.5 / 18.3)`. A pure minutes
increase should raise the volume behind a percentage without changing
efficiency:

```
10.5 / 18.3 = 57.3%     ×1.20 minutes →     12.6 / 21.96 = 57.3%
```

This matters for category valuation: a 90% FT shooter at 2 FTA/game and the same
shooter at 8 FTA/game do not have equal fantasy impact. Use unrounded internals —
rounded components produce small discrepancies.

### Hashtag Basketball

Projection fields: `GP, MPG, FG%, FT%, 3PM, PTS, REB, AST, STL, BLK, TO`, with
makes/attempts in detailed views. Three in-season sets: standard, BLEND7 (50%
standard + 50% last 7 days), BLEND14. Blends apply to the projection data
itself, treating projections as coherent statistical vectors.

**Category multipliers are not projection adjustments.** `AST ×1.5` changes how
much the category contributes to a player's value/rank; it does not mean
`projected AST × 1.5`. The pipeline is `projection → valuation → user category
weights → ranking`, not `projection → user changes production`. Worth
preserving that distinction.

No public documentation establishes that Hashtag exposes user minute overrides.
Do not cite it as evidence for any minute-override algorithm.

### DARKO / DRIP

DARKO is a forward-looking box-score projection system that projects components
independently and updates continuously as games arrive (Bayesian, with
per-player/per-stat update strength). Its ratings have been combined with
*separately predicted minutes* to forecast games — i.e.
`TALENT/RATE × EXPECTED OPPORTUNITY → EXPECTED PRODUCTION`, rather than four
unrelated projections of PTS/REB/AST/MIN.

DARKO also projects shooting percentages independently, designed to answer
whether an observed 3P% shift is real or noise. So a minutes change must not
imply `32→36 min ⇒ 38%→42.75% 3P`. Minutes provide more opportunities to shoot;
they do not make shots likelier to go in.

DRIP is an impact model, not a fantasy editor — relevant only for reinforcing
the same separation between "how productive is the player" and "how much will
he play."

### The three adjustment models

Base: `MIN 24, PTS 12, REB 6, AST 3, FGM 4.5, FGA 10.0 (.450)`. User sets
minutes to 30.

**Model A — minutes-only override.** `MIN 30`, everything else unchanged.
Implicitly says per-minute productivity collapses 20%. Almost never what the
user means. Poor default.

**Model B — proportional opportunity scaling** (×1.25). `MIN 30, PTS 15.00,
REB 7.50, AST 3.75, FGM 5.625, FGA 12.50, FG% .450`. Says "I disagree with the
playing-time assumption but accept the model's production rates." Cleanest
interpretation of a minutes override; closest to BBM's per-minute Skill Level
and DARKO-style rate-plus-opportunity modelling.

**Model C — full projection override.** User enters the whole line; their
projection replaces the model's. Useful, but should be a *different operation*
from changing minutes — BBM's separation of Custom Daily Minutes from Custom
Projections is the precedent.

### Persistence semantics

Three representations diverge once the base moves. Base 24 → user believes 30;
base later becomes 27:

```
absolute        minutes = 30        → 30
additive        delta   = +6        → 33
multiplicative  factor  = 1.25      → 33.75
```

No public evidence on what BBM does. But absolute captures what the user
actually asserted — "I think Player X plays 30 minutes" — not "I am permanently
25% more bullish than your model."

### Base refreshes

The weakest area in public documentation; no established-tool behaviour could be
confirmed. Do not reverse-engineer a requirement from that absence — make the
semantics explicit instead.

Recommended: keep the user's assertion, recompute everything else from the new
base. Base v17 `28 MIN, 0.60 PTS/min, 48% FG` + user `minutes = 34` yields
`34 MIN, 20.4 PTS, 48% FG`. When v18 arrives at `30 MIN, 0.63 PTS/min, 49% FG`,
the user's only expressed disagreement was minutes, so recompute to `34 MIN,
21.42 PTS, 49% FG`. The user gets every model improvement except the assumption
they explicitly rejected — far better than freezing `20.4 PTS, 48% FG` forever.

### Stale-adjustment detection

Record the base value an override was created against, then surface when the
model has caught up: *"Your projection 34, current model 33, originally 28 —
your adjustment is now only +1 minute"*, offering keep / use-model / remove. An
opinion that was meaningful in October can become redundant by December.

### Recommendation

Live base + sparse absolute overrides + derived rate scaling. Interpret a
minutes adjustment semantically as *"I disagree with your opportunity
assumption"*: keep the model's per-minute rates, recompute volume at the new
minutes, and preserve shooting percentages while scaling their attempts and
makes. Do not fork the projection set on an edit, and do not persist the
computed PTS/REB/AST as overrides — store only the user's actual assertions and
compose them onto the newest base, so the engine keeps learning underneath the
user's opinion instead of their October tweak becoming a fossil trapped in
amber.
