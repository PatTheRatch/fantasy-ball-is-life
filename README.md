# Full Court Press — V2

> **This is the `v2` branch: a clean foundation. V1 lives on `main` and is still the deployed product.**

A fantasy-basketball league history and intelligence platform with a private
competitive layer.

**Follow the league together. Dominate it privately.**

- **Shared** — turn results, transactions, rivalries, records and manager
  decisions into an ongoing sports story a whole league follows.
- **Private** — turn the same underlying facts into competitive intelligence
  for an individual manager: draft, stream, trade, project, simulate.

---

## Why this branch is nearly empty

V2 is a deliberate restart, not a refactor. Three independent forensic audits
agreed: the basketball domain logic is valuable, the architecture around it
carries scars from repeated scope expansion. The decision (charter §18, and
`docs/CLAUDE_GREENFIELD_ARCHITECTURE.md` Part C) was **preserve the domain
logic, rebuild the application around it**.

So this branch starts clean. V1's 251 code files are not here — not because
they are worthless, but because roughly 70% of them are classified KILL and
having them in the tree makes it ambiguous what is being built versus what is
being replaced.

**Nothing was lost.** V1 is complete on `main`, still deployed, and is
explicitly the behavioural reference and test oracle (charter §9).

## Reading V1 while building V2

```bash
# one-off file read
git show main:backend/league/scoreboard.py

# side-by-side working copy, pinned to main
git worktree add ../fcp-v1 main
```

The worktree is the right tool when capturing characterization tests — run V1,
record its outputs, assert V2 reproduces them.

## Start here

Read in this order. All of it also lives on `main`, which is authoritative.

| Document | What it is |
|---|---|
| [`docs/FCP_V2_Product_Architecture_Charter.md`](docs/FCP_V2_Product_Architecture_Charter.md) | **Authoritative.** 28 decisions, 10 non-negotiables, the north-star test |
| [`docs/v2/schema/README.md`](docs/v2/schema/README.md) | Binding schema conventions + the seven domain files |
| [`docs/v2/PROVIDER_INGESTION_DESIGN.md`](docs/v2/PROVIDER_INGESTION_DESIGN.md) | Ingestion pipeline, adapter contract, replay |
| [`docs/v2/V1_CLASSIFICATION.md`](docs/v2/V1_CLASSIFICATION.md) | KEEP/EXTRACT/REWRITE/KILL/DEFER + the 44-invariant register |
| [`docs/CLAUDE_FCP_AUDIT.md`](docs/CLAUDE_FCP_AUDIT.md) | What went wrong in V1, cited to `path:line` |

If you are an agent picking up work: read the charter, then
`docs/v2/schema/README.md`, then the domain file you are touching. The schema
README's conventions are binding — an ID strategy or lineage block invented
locally is wrong even if internally consistent.

## The non-negotiables

From charter §10. These are the failure modes V1 actually produced.

- No silent cross-league or cross-manager state leakage.
- No durable product state stored only on a container filesystem.
- No provider-specific client object as the canonical domain model.
- No player identity strategy based primarily on fuzzy names.
- No hardcoded season calendars.
- No private strategy leaking into shared storytelling without explicit action.
- No derived metric without a versioned definition when used historically.
- No overwriting projection history when a user edits assumptions.
- No normalization that cannot explain where a canonical fact came from.
- **No silent degradation** — a feature that cannot produce its output says so,
  records why, and surfaces it.

## Build order

Charter §11. Slice 1's port list is `docs/v2/V1_CLASSIFICATION.md` §9.

1. ~~Freeze the charter~~ ✅
2. ~~V2 domain schema~~ ✅ `docs/v2/schema/`
3. ~~Provider ingestion design~~ ✅
4. Identity resolution design — largely settled in schema `04` + the ingestion design
5. ~~Classify V1~~ ✅
6. **Thin vertical slice** ← next. user → manager → league → season → ESPN sync
   → canonical teams/players/periods → one shared league page, **with tenancy
   from day one** (charter D26)
7. Historical event capture — cannot be backfilled, so it starts early
8. Reintroduce intelligence (projections, matchups, draft)
9. Rebuild storytelling from canonical facts

## Status

Design complete, no code. `v2` triggers CI but never deploys — production
deploys run only from `main`.
