# Full Court Press V2

Product & Architecture Charter

Decision record for the V2 restart • 21 August 2026

## ADHD TL;DR

What are we building? A fantasy-basketball league history and
intelligence platform with a private competitive layer.

Shared side: help an entire league follow its season as a living story,
closer to following the NBA than reading a box score.

Private side: give serious managers tools to draft, stream, trade,
project, simulate, and make better decisions.

Architecture direction: start FCP V2 cleanly, keep current FCP running,
and transplant valuable domain logic rather than inheriting historical
structure.

Core data rule: keep the evidence. Normalize it reproducibly. Version
beliefs and analytics. Prefer unknown over confidently wrong.

## 1. Why V2 Exists

FCP began as a single-league ESPN decision tool and expanded rapidly
into a newsroom, multi-league platform, draft optimizer, projection
framework, onboarding system, and projection-research environment. Three
independent forensic audits reached essentially the same conclusion: the
basketball domain logic contains valuable IP, but the current
architecture carries scars from repeated scope expansion.

Because restart cost is intentionally treated as effectively zero, V2 is
not constrained by sunk cost. The goal is the best end product, clean
code, clear boundaries, durable data, and an architecture that can
support a few hundred enthusiastic users without baking today's
ESPN-first implementation into the permanent domain model.

## 2. Product Thesis

> Follow the league together. Dominate it privately.

FCP has two complementary experiences built on one data platform. The
league-facing experience turns results, transactions, rivalries,
records, power shifts, and manager decisions into an ongoing sports
story. The private manager experience turns the same underlying facts
into competitive intelligence.

## 3. Product Scope

### Shared league experience

-   League timeline and historical record

-   Matchups, standings, transactions, roster changes, records,
    rivalries and milestones

-   Power rankings and season narratives

-   Weekly newsroom / recap publication

-   Shared analytics that help the league understand what happened and
    why

-   Optional manager-published signals such as categories sought,
    players of interest, or trade availability

### Private manager intelligence

-   Personal projection sources and manual projection adjustments

-   Draft plans and auction optimization

-   Waiver and streaming recommendations

-   Trade evaluation and private targets

-   Matchup/category strategy

-   Watchlists, notes, simulations and decision support

-   Manager-performance analytics that distinguish process quality from
    outcome luck

## 4. V2 Foundational Decisions

Decision 1: Product identity. FCP is both a league story platform and a
serious-manager intelligence platform. Neither side is merely an
accessory.

Decision 2: Draft Room positioning. Draft intelligence can remain
private until Patrick has used it competitively; long-term it belongs to
the power-user layer.

Decision 3: Projection plurality. Users can use FCP projections or their
own sources. Short-horizon and season-horizon projections are distinct
needs.

Decision 4: Editable projections. Uploaded or FCP-generated projections
may be adjusted by users without destroying the original version.

Decision 5: Multi-provider future. ESPN is first because it is known and
used today. Yahoo and Sleeper are explicit future targets, so provider
concepts must be normalized behind FCP concepts.

Decision 6: Scale target. Design for a credible early public launch and
a few hundred users, not hyperscale.

Decision 7: Restart posture. A clean V2 restart is acceptable and
preferred if it improves the end product. Current FCP remains a
reference implementation and test oracle.

Decision 8: League/team history. League and team identity must persist
across seasons rather than being treated as one disposable
current-season object.

Decision 9: Co-managers. A fantasy team can have multiple managers.

Decision 10: Historical depth. Retain rich historical league data,
including roster and lineup state when obtainable. More data is
preferable while storage is cheap.

Decision 11: Season-specific rules. League settings belong to
LeagueSeason. The product launches around 9-cat H2H, but the database
should not hardcode exactly nine categories forever.

Decision 12: Shared vs private boundary. League intelligence is shared
by default. Manager strategy is private by default. Crossing that
boundary requires explicit sharing.

Decision 13: Manager identity. A login User is not the same thing as a
fantasy Manager. Manager identity survives team changes, co-management
and historical ownership.

Decision 14: Canonical NBA schedule. FCP owns canonical NBA seasons,
teams and games. Fantasy providers map their matchup periods onto those
real NBA dates.

Decision 15: Matchup periods. Matchup periods are real season-specific
database objects with dates and types, imported from providers and
normalized by FCP. No hand-maintained week calendars.

Decision 16: Raw provider retention. Keep raw provider evidence
alongside normalized data so ingestion can be replayed, audited and
improved later.

Decision 17: Data lineage. Canonical facts record source, observation
time, normalizer/parser version and supersession where appropriate.
Normalization must be reproducible.

Decision 18: Identity resolution. Provider records map to canonical FCP
entities. Ambiguous matches are flagged rather than silently
fuzzy-matched. Prefer unknown over confidently wrong.

Decision 19: Permanent identity crosswalk. Maintain durable mappings
between FCP player IDs and NBA/ESPN/Yahoo/Sleeper/BBM/Hashtag
identities, including match method, confidence and verification.

Decision 20: Events + snapshots. Events describe what happened;
snapshots describe what the world looked like at a point in time. Both
are permanent first-class historical data.

Decision 21: Reproducible analytics. Facts are permanent. Derived
metrics/models are versioned so historical scores can be reproduced and
compared as methodology improves.

Decision 22: Historical beliefs. Projection sets are immutable,
versioned records of what was believed at a particular time. Editing
creates a new version.

Decision 23: Durable storage boundary. Postgres is the durable
structured source of truth; object storage holds appropriate raw/files;
Python performs analytics, optimization, simulation and modelling.

Decision 24: Projection adjustment model. User adjustments are stored as
deltas against an immutable base set and composed at read time, so a
user can switch base source and keep their adjustments. When a composed
view actually drives a decision --- a draft, a published ranking, a
recorded recommendation --- the composed result is frozen as an
immutable snapshot so that decision remains reproducible. Supersedes the
"editing creates a new version" phrasing in Decision 22 for user
adjustments specifically; Decision 22 continues to govern base sets.

Decision 25: Cutover data. V2 starts with an empty database. All data in
current FCP is development/mock data created after the 2025-26 season
ended; it has never been used by real managers and nothing in it needs
to be preserved. Historical data may be re-ingested later as test
fixtures, through the V2 ingestion path rather than by migration.

Decision 26: Tenancy from day one. Authorization and league/manager
scoping land in the first vertical slice, not afterwards. Scope is
structural: repositories touching league or manager data cannot be
constructed without a scope object, and a route-policy test fails CI on
any route without an explicit declared policy.

Decision 27: Manager-published signals. The sharing boundary is modelled
in V2 (explicit, attributable, revocable share records; nothing shared
by default), but the user-facing signals surface is not built in V2.
This keeps a later feature from requiring a migration.

## 5. Core Domain Model Direction

The following is the conceptual V2 map. It is not yet a final SQL
schema; it defines the domains and ownership boundaries the schema
should express.

### Identity

User accounts • Managers • Team-manager assignments • Co-manager
relationships

### Fantasy

Leagues • League seasons • Fantasy teams • Season-specific
settings/categories • Matchup periods • Matchups • Rosters • Lineups •
Transactions • League events

### NBA

NBA seasons • NBA teams • Players • Games • Player performances /
availability where obtainable

### Provider & ingestion

Provider connections • Raw provider snapshots • Provider identities •
Canonical identity crosswalk • Normalizer/parser versions • Ingestion
runs and lineage

### Projections

Projection sources • Projection sets • Immutable versions • Player
projections • User adjustments • Short- and long-horizon projections

### Intelligence

Matchup analytics • Streaming / waiver analysis • Trade analysis • Draft
optimizer • Manager evaluation • Simulations • Versioned derived metrics

### Story engine

League timeline • Records and milestones • Rivalries • Power rankings •
Weekly recaps • Published newsroom editions

## 6. Data Principles

Data is king: At early scale, retain useful evidence rather than
aggressively deleting information that may become analytically valuable.

FCP owns canonical identity: External IDs are mappings, not FCP primary
keys. NBA ID is a valuable anchor when available, but FCP retains its
own stable IDs.

Raw is not canonical: Provider payloads are evidence. FCP normalization
creates canonical domain facts while preserving provenance.

Replay beats patching: Improved normalizers should be able to replay
stored raw data instead of requiring another provider fetch.

Unknown is valid: Uncertain identity or interpretation is surfaced for
resolution rather than silently guessed.

History is immutable by default: Corrections supersede prior
interpretations rather than erasing the fact that the earlier
interpretation existed.

Beliefs are time-dependent: Projections and other decision inputs are
stored as-of the time they were known.

Process can differ from outcome: Manager analytics should eventually
distinguish good decisions that failed from poor decisions that got
lucky.

## 7. Architectural Direction

V2 should begin as a modular application, not a fleet of microservices.
Clean domain boundaries matter more than process boundaries at this
scale.

-   React frontend for the consumer and manager experiences.

-   A clearly structured API/application layer with consistent
    authentication, authorization and league/manager scoping.

-   Postgres/Supabase for durable relational facts, identities, history,
    projection metadata and derived results.

-   Object storage for raw payload archives, uploaded source files and
    other large immutable artifacts where appropriate.

-   Python for projection modelling, optimization, Monte Carlo,
    simulations and analytical jobs.

-   Durable background jobs/workers for provider synchronization,
    normalization, recalculation and publishing workflows.

-   Provider adapters at the boundary. ESPN-specific objects must not
    become the domain model.

## 8. What Current FCP Taught Us

Three independent audits broadly agreed on the same pattern: the
basketball domain logic is worth keeping and the surrounding structure
is not. All three independently recommended preserving the domain logic
and rebuilding the application around it.

| Preserve the idea / logic | Do not inherit the scar |
| --- | --- |
| Canonical projection schema and adapters | Local ephemeral Parquet/manifest as production persistence |
| Draft optimization, Monte Carlo targets, Forge/value logic | Flat global/unscoped draft and projection APIs |
| Deterministic recap facts + versioned publication | RecapStore becoming the universal database layer |
| 9-cat category semantics and all-play math | ESPN client subclasses as the domain model |
| ESPN timeout/error gateway ideas | Live third-party fetches scattered through page requests |
| Worker failure isolation | One synchronous HTTP refresh loop as the job system |
| Historical weekly correctness | Overlapping snapshot tables created reactively |
| Strong regression-test habit | Mocks that hide frontend/backend/schema contract drift |

## 9. V2 Migration Posture

Current FCP should stay running during V2 development as a behavioral
reference, a source of domain logic, and a test oracle. It is not a
live product and has no real users (Decision 25), so there is no
parallel-run obligation, no cutover event and no data-migration phase
--- V2 can be built and switched to whenever it is better.

The unit of migration is not the file. It is the idea, invariant,
algorithm, test case, or proven domain behavior.

KEEP --- Already clean enough to preserve substantially as-is.

EXTRACT --- Valuable domain logic that should be moved behind a cleaner
V2 boundary.

REWRITE --- The product concept is right but the implementation is tied
to current architectural scars.

KILL --- Legacy paths, duplication, global defaults, historical
deployment residue, or behavior no longer wanted.

DEFER --- Useful idea that should not block the V2 foundation.

## 10. V2 Non-Negotiables

-   No silent cross-league or cross-manager state leakage.

-   No important durable product state stored only on a container
    filesystem.

-   No provider-specific client object as the canonical fantasy domain
    model.

-   No player identity strategy based primarily on fuzzy names.

-   No hardcoded season calendars.

-   No private strategy leaking into shared league storytelling without
    explicit user action.

-   No derived metric without a versioned definition/input lineage when
    it is used historically.

-   No overwriting projection history when a user edits assumptions.

-   No normalization that cannot explain where a canonical fact came
    from.

-   No silent degradation. A feature that cannot produce its output says
    so explicitly, records why, and surfaces it. The absence of a result
    must never be indistinguishable from a result, and a computation that
    ran on partial inputs must say which inputs were missing.

## 11. Immediate V2 Work Plan

1.  Freeze the charter. Treat the decisions in this document as the
    starting product/architecture contract. Changes are allowed, but
    should be explicit decisions.

2.  Produce the V2 domain schema. Turn the conceptual domains into
    entities, keys, relationships, ownership/scoping rules and
    historical semantics.

3.  Design provider ingestion. Define raw snapshot storage, ingestion
    runs, ESPN adapter contracts, normalization outputs and replay
    behavior.

4.  Design identity resolution. Define FCP IDs, provider crosswalks,
    NBA-ID anchoring, unresolved queues and verification workflows.

5.  Classify current FCP. Run KEEP / EXTRACT / REWRITE / KILL / DEFER
    across current domain logic and tests.

6.  Build a thin vertical slice. User → manager → league → season → ESPN
    sync → canonical teams/players/matchup period → one shared league
    page. Prove the architecture before rebuilding every feature.

7.  Add historical event capture. Transactions, roster/lineup state,
    matchups and snapshots become durable early, because some historical
    data cannot be reconstructed later.

8.  Reintroduce intelligence. Bring projections, matchup analysis and
    eventually draft/stream/trade tooling onto the new canonical data
    model.

9.  Rebuild storytelling. Generate timeline/newsroom experiences from
    canonical facts and events, not from ad hoc current-state blobs.

## 12. North-Star Test

When considering a V2 design choice, ask: Can this help a league
understand and remember its own story, while also helping an individual
manager make a better private decision, without corrupting history or
tying FCP permanently to one provider?

> If yes, it probably belongs in FCP. If it only preserves an accident
> of the current implementation, it probably does not.

FCP V2 starting point: clean foundation, durable history,
provider-neutral domain, serious basketball intelligence.
