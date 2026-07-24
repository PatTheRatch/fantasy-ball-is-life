# Feature Spec: FCP Projections — our own player projection model

**Status:** Product direction set by Patrick (owner) 2026-07-24 — pending
Aisha's technical review before implementation (per
`docs/AISHA_OPERATING_MANUAL.md`).
**Author:** Claude Code (implementation engineer)
**Date:** 2026-07-24
**Decision basis:** Fulfils the projection framework's founding **Product
Decision B** ("user-uploaded projections now, **our own model later**, all
behind one framework"). Ends the recurring Basketball Monster dependency and
becomes the platform's flagship differentiator: explainable, benchmarked,
in-house projections.

**Hard deadline:** usable for a real draft by **~October (draft day)**. This
is the largest item on the roadmap by an order of magnitude — it ships as a
long series of small PRs, and the deadline governs sequencing.

---

## 1. What this is (and the architectural cheat code)

A projection model that outputs one row per player in the existing canonical
`PlayerProjection` schema, registered as **just another source** in
`backend/projections/` (adapter + registry entry), with both **season** and
**week** horizons — the two the `ProjectionStore` already supports.

Because every consumer (draft optimizer/auction values via `value_col`,
projected scoreboards, matchup confidence, MC draft targets, the Streaming
Advisor) reads only the canonical schema, **none of them change**. Framework
acceptance criterion 6, cashed in.

The model itself is deliberately boring in v1: weighted multi-season rates ×
age curve × role/minutes assumptions, with makes/attempts (never averaged
percentages), a separately-projected games-played estimate, and a distinct
rookie translation model. Machine learning is a later refinement, not the
foundation — v1's bar is "difficult to embarrass," proven by backtest.

## 2. Data pipeline (shared infrastructure)

New ingest layer `backend/nbadata/` fed by the **`nba_api`** package (new
dependency) — deliberately built as **shared infrastructure**: the Streaming
Advisor's S-5 enrichment adapter (recent form, minutes trends) reads the same
tables. One nightly ingest, two consumers.

### Tables (all service-role write; global, not league-scoped)

**`nba_player_seasons`** — one row per player per season, ~15 seasons back:
identity (nba person id, name, season, age, team, position), availability
(GP, GS, minutes, MPG), volume (FGA/FGM, FTA/FTM, 3PA/3PM, TOV, USG%),
production (PTS/REB/AST/STL/BLK), context (team pace, ORtg). Store **makes
and attempts**, not just percentages.

**`nba_player_bio`** — DOB, height, weight, draft year/pick, experience.

**`nba_rookie_translation`** — per historical drafted prospect: pre-NBA
stats (per-minute rates, league source: NCAA / G-League / EuroLeague / other
international / other), age at draft, pick, measurements → joined to actual
rookie-season NBA rates. ≥10 draft classes. Seeded from public draft/NCAA
datasets (licensing checked before anything commercial) + a manual CSV for
the current class.

**`projection_assumptions`** — the human-in-the-loop layer (see §4).

Historical NBA data is fully backfillable (no urgency clock, unlike daily
roster snapshots) — the ingest is a one-time backfill + light nightly upkeep.

## 3. The model (v1)

Computed offline by a job (`backend/projections/fcp_model.py`), output saved
as a `ProjectionSet` via the existing store:

1. **Per-minute rates:** weighted history (e.g. 55/30/15 across last three
   seasons — weights *learned by backtest*, not chosen by vibes), regressed
   toward position/age means for small samples.
2. **Age curve:** multiplicative adjustment from ~15–20 seasons of
   league-wide aging data.
3. **Minutes & role:** `projected_mpg` from prior minutes + the assumptions
   layer; enforce **team coherence** — ~240 team minutes/game and sane usage
   totals per team (no eight 31-MPG teammates; not a rotation, a clown car).
4. **Games played:** projected separately (availability history + age), so
   injury expectations never contaminate per-game ability. Consumers already
   multiply rate × games.
5. **Percentages:** projected FGM/FGA and FTM/FTA → derive FG%/FT% (attempt
   volume matters; 48.7% on 1,100 FGA ≠ 48.7% on 90).
6. **Rookies:** separate translation model (draft pick + age + per-minute
   pre-NBA rates + league-strength indicator → rookie NBA rates and MPG).
   NCAA model first; international gets broader priors + manual overrides.

## 4. Assumptions layer (the part BBM actually charges for)

A small editable table + admin UI (global, platform-level — same CRUD shape
as `InviteAdmin`): per player, `projected_mpg`, `projected_games`,
`role` (starter/sixth man/bench), `usage_adjustment`, `confidence`, `notes`.
The model consumes it at run time; offseason maintenance becomes "edit the
assumptions," not "rewrite the model." Every non-default assumption is
visible in the player's outlook (explainability is the product).

## 5. The benchmark harness ("final boss battle")

Because BBM uploads and FCP output live in the same canonical schema, and
actual weekly results are stored (`league_week_scoreboards`), we build a
**projection accuracy scoreboard** early and keep it forever:

- Per source × per category × per week: projected vs actual error (MAE +
  rank-correlation of player values).
- Compares FCP vs BBM vs ESPN-15 head-to-head — works **today** for
  BBM vs ESPN before FCP even exists (build it first, M-2).
- Public page eventually — "our model vs Basketball Monster, measured" is
  the portfolio artifact.

Run one full season with BBM as benchmark before cutting the cord; the £80
becomes tuition for the final boss battle.

## 6. Phases

| Phase | Scope | Depends on | Done when |
|---|---|---|---|
| **M-1** | `nba_api` ingest: `backend/nbadata/`, `nba_player_seasons` + `nba_player_bio` migrations, backfill (~15 seasons) + nightly upkeep job, name-resolution to ESPN players via existing normalize/fuzzy pipeline | — | Backfill idempotent; hermetic tests (mocked nba_api); unmatched-name report, not silent drops |
| **M-2** | Accuracy scoreboard: projected-vs-actual per source/category/week from stored results; internal page | — (works with BBM/ESPN now) | BBM vs ESPN-15 measurable for past weeks |
| **M-3** | Veteran model v1: weighted rates + age curve + team-coherence + separate GP; outputs a season-horizon `ProjectionSet` behind a `fcp` registry source | M-1 | Backtest ≥1 held-out season; beats naive last-season-repeated baseline on MAE; adapter-only (zero consumer changes) |
| **M-4** | Assumptions layer: table + admin CRUD UI; model consumes overrides | M-3 | Edited assumption changes the next run's output; audit trail |
| **M-5** | Rookie translation: `nba_rookie_translation` seed + NCAA model + international priors + manual overrides | M-1 | Backtest on held-out draft classes; every current-class rookie gets a projection |
| **M-6** | Week horizon: FCP weekly sets (rest-of-week rates × schedule), feeding advisor/scoreboards | M-3 | Weekly set activates like BBM weekly uploads do |
| **M-7** *(stretch)* | Learned weights / gradient boosting where backtest justifies it | M-3, M-2 | Only merges if it beats v1 on the M-2 scoreboard |

M-1 and M-2 can run in parallel. **M-3 by early September** leaves buffer for
the October draft deadline.

## 7. Test plan

- Ingest: idempotent backfill; schema conformance; name-matching surfaces
  unmatched players (framework criterion 3).
- Model: golden-player unit tests (aging vet declines, small-sample regresses,
  percentages derived from makes/attempts); team-coherence property test
  (no team > ~248 projected minutes/game); determinism given fixed inputs +
  assumptions.
- Backtest harness itself tested against a synthetic season with known
  answers.
- Meta: clean-env runs, `spec=` mocks (standing lessons).

## 8. Risks & open questions

- **nba_api fragility/rate limits** — unofficial NBA.com client; nightly
  batch with retries + the ingest never blocks anything user-facing.
- **Scope creep is the killer.** v1 is weighted averages + assumptions, not
  ML. M-7 is gated on *measured* improvement.
- **Rookie data licensing** — check before any public/commercial use.
- **The assumptions burden is real** (it's what BBM charges for) — budget
  offseason hours; the UI (M-4) exists to make that cheap.
- **Open:** exact backtest metric weighting (per-category MAE vs value rank
  correlation) — decide in M-2.
- **Open:** publish FCP projections publicly, or keep as the app's engine
  only? (Licensing/ToS review before publishing.)

## 9. Out of scope (v1)

- Daily DFS-style projections; betting anything.
- Live in-season model retraining (weekly refresh is enough).
- Non-NBA data purchases (Option B commercial feeds — avoided).
- Publishing/selling projections (revisit post-benchmark).
