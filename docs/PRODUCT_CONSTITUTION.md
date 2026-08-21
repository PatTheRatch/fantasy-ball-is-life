# Full Court Press (FCP) Product Constitution

## 1. What FCP is

Full Court Press is a fantasy basketball platform for serious fantasy basketball managers.

It has two equally important product layers:

### Shared league experience
FCP should make a fantasy league feel like a sports league worth following.

Members should be able to follow the story of their league across a season, not just look at standings and weekly scores.

This includes things like:

- weekly recaps
- power rankings
- awards
- rivalries
- transactions
- breakout teams
- collapses
- playoff races
- historical moments
- season narratives
- league records and trends

The goal is for a fantasy league to have something resembling its own ESPN or league media ecosystem.

### Private power-user experience
FCP should also help an individual manager gain a competitive advantage.

Private tools may include:

- Draft Room
- waiver analysis
- streaming recommendations
- matchup optimization
- trade analysis
- roster construction
- player comparison
- schedule analysis
- projections
- custom player evaluations
- playoff planning

These tools exist to help the individual user win.

A user's private strategy must not be visible to other league members.

---

## 2. Primary user

The primary user is an individual fantasy basketball manager who cares enough to use analytical tools to make better decisions.

Commissioners may receive additional administrative capabilities, but FCP should not depend on commissioners being the primary users.

One user may belong to multiple leagues.

One league may contain multiple FCP users.

---

## 3. Shared vs private information

FCP must explicitly distinguish between league-shared information and private user information.

### League-shared

Examples include:

- league configuration
- teams
- rosters
- matchups
- results
- transactions
- standings
- league history
- published recaps
- shared power rankings
- awards
- league storylines

### Private to an individual user

Examples include:

- Draft Room strategy
- target players
- do-not-draft lists
- waiver targets
- potential add/drop decisions
- trades being considered
- private player evaluations
- custom projection preferences
- custom projection adjustments
- watchlists
- roster optimization
- private model settings

Another manager in the same league must not be able to see these.

---

## 4. Basketball intelligence is a core platform capability

FCP should have a reusable basketball intelligence layer that powers multiple products.

Decision tools should not each independently invent their own versions of:

- player identity
- projections
- category values
- schedule calculations
- roster value
- league context
- matchup logic
- team fit
- player availability

Shared domain capabilities should power Draft Room, matchups, streaming, trades, waivers, season analysis, and future tools.

---

## 5. Projections are a first-class system

Projection data is central to FCP.

FCP must support multiple projection sources.

Potential sources include:

- FCP's own models
- ESPN
- Basketball Monster
- Hashtag Basketball
- other supported providers
- user-uploaded projections
- custom user projections

FCP may not legally or commercially be able to redistribute some paid projection sources.

For those sources, the user may need to download their own licensed projections and upload them privately.

### Projection horizons

Projection horizon must be explicit.

Examples include:

- very short term
- rest of current matchup week
- several weeks
- rest of season
- full preseason season projection

Different FCP tools may require different horizons.

For example:

- streaming and matchup tools need short-term projections
- trades may need medium- and long-term projections
- Draft Room needs season projections

### User choice

Users should be able to choose which projection source powers their private analysis.

Two users in the same league may use completely different projections.

Shared league-facing analytics should use a consistent FCP/default methodology so that league-wide rankings and stories are coherent.

### User adjustments

The architecture should permit users to modify projections or assumptions.

For example, a user might believe:

- a player will receive more minutes
- a player will miss games
- a player's role has changed
- a player should have different rates than the base projection assumes

A user should eventually be able to adjust either imported projections or FCP projections without overwriting the original underlying source.

Projection source, projection horizon, and user adjustments should therefore be separate concepts.

---

## 6. FCP should eventually own projections

FCP intends to develop its own projections and valuation models.

They do not need to exist in the first rebuilt version.

However, first-party FCP projections should eventually be able to participate in the same projection system as external or uploaded sources.

The architecture should not require another redesign when FCP's own model becomes production-ready.

---

## 7. External fantasy platforms are adapters, not the domain model

ESPN is the first supported fantasy platform because that is the platform currently used by the initial users.

Long term, FCP should be capable of supporting at least:

- ESPN
- Yahoo
- Sleeper

Potentially others later.

We do NOT need to implement Yahoo or Sleeper now.

However, FCP's internal concepts must not fundamentally be ESPN objects.

Conceptually:

ESPN / Yahoo / Sleeper
→ normalized FCP league model
→ FCP features

FCP should own canonical concepts such as:

- fantasy league
- fantasy team
- manager
- roster
- matchup
- transaction
- scoring settings
- schedule
- season

Provider-specific structures should be translated into those concepts.

Adding Yahoo or Sleeper in the future should primarily involve creating a provider integration, not rewriting FCP's domain logic.

---

## 8. Player identity must belong to FCP

FCP needs a durable player identity independent of any specific source.

ESPN IDs, NBA IDs, Basketball Monster names, Hashtag names, and future Yahoo/Sleeper identifiers should map onto FCP's player identity.

Player names should not be the canonical join key.

Name matching may be used during ingestion, but important relationships should eventually resolve to stable FCP player identifiers.

---

## 9. Data has different meanings and lifetimes

The architecture should explicitly distinguish:

### Source data
Examples:

- ESPN
- Yahoo
- Sleeper
- NBA data
- Basketball Monster
- Hashtag

### Normalized FCP data

Provider-independent representations of players, leagues, teams, rosters, matchups, transactions, schedules, etc.

### Derived analytics

Examples:

- category strength
- power rankings
- projected matchup outcomes
- team fit
- player value
- streaming value
- trade value

### User-specific analytics

Derived calculations incorporating:

- the user's team
- chosen projections
- projection adjustments
- preferences
- strategy

### Presentation

What the frontend ultimately displays.

These layers should not be accidentally mixed together.

---

## 10. Historical state matters

FCP should be capable of answering questions such as:

"What did this league look like after Week 7?"

Historical results should not be reconstructed incorrectly using today's rosters or current ESPN state.

Completed historical facts should be durable.

The architecture should deliberately define what data is:

- live
- periodically refreshed
- historical and immutable

---

## 11. Freshness should be explicit

Not all FCP data needs to be live.

Possible examples:

### Live or near-live

- active draft state
- current matchup
- current roster
- recent transactions

### Periodically refreshed

- standings
- season statistics
- power rankings
- projection accuracy
- some league analytics

### Historical / immutable

- completed weekly matchups
- historical transactions
- published recap facts
- previous projection snapshots
- completed NBA seasons

Users and developers should be able to understand the freshness semantics of a feature without reverse-engineering its implementation.

---

## 12. Multi-league is fundamental

FCP is not fundamentally a single-league application.

Nothing league-specific should accidentally become global.

Examples include:

- league settings
- season
- roster configuration
- player ownership
- draft configuration
- matchup state
- team identity

Similarly, private user preferences should not accidentally apply to every user or league.

---

## 13. The Newsroom is a real product pillar

League storytelling is not merely decorative AI text.

It is one of FCP's core reasons for existing.

The factual basis for storytelling must remain deterministic and auditable.

The system should conceptually separate:

league facts
→ deterministic story inputs
→ generated editorial content

An LLM may turn facts into compelling editorial output.

An LLM should never be the authoritative source of standings, awards, transactions, rankings, matchup results, or other factual league state.

League members should eventually be able to follow a multi-season history of their league and its narratives.

---

## 14. Draft Room is a private power-user product

Draft Room is a serious decision tool.

It may remain private or limited until the initial users have personally benefited from it.

Long-term, if exposed to other users, it should be private to each manager.

It should be capable of considering:

- league settings
- available players
- projections
- budget
- roster slots
- category targets
- target players
- excluded players
- draft history
- changing remaining player pool
- personal preferences

The optimization engine should remain separable from UI and persistence concerns.

---

## 15. Future private decision tools

The architecture should leave a natural home for future tools such as:

- streaming advisor
- waiver recommendations
- trade analyzer
- player comparison
- schedule optimization
- playoff planning
- roster construction
- add/drop analysis

Do not build these merely for architectural completeness.

But adding them later should not require duplicating core basketball logic.

---

## 16. Product scale

FCP is being built for the creator and their league first.

The best realistic growth case in the near future might be posting it to fantasy basketball communities and attracting hundreds of users, potentially growing into thousands of users or leagues.

Design for a legitimate multi-user product.

Do not design for millions of concurrent users.

Avoid infrastructure complexity without a concrete reason.

A simple system that comfortably supports hundreds or thousands of users is preferable to speculative distributed infrastructure.

---

## 17. Commercial assumption

FCP may eventually become a paid product.

There is no need to implement billing during the architectural rebuild unless it naturally belongs in the initial product.

However, the architecture should not assume:

- one trusted user
- one trusted league
- one global configuration
- free unlimited external API usage
- free unlimited LLM usage

Security, authorization, tenancy, usage controls, and data durability should be appropriate for a real public product.

---

## 18. Rebuild constraint

For the architecture review, treat sunk development cost as effectively zero.

Existing:

- frontend
- backend
- database tables
- APIs
- deployment
- directory structure
- migrations
- components

may all be replaced.

Downtime and migration effort are not meaningful constraints.

Starting again from "Hello World" is completely acceptable.

However:

Do not recommend rebuilding something merely because greenfield development feels cleaner.

Existing components, algorithms, schemas, concepts, or implementations should survive if they are genuinely good.

The only meaningful objective is the quality of the resulting FCP product.

---

## 19. Existing domain IP should be evaluated carefully

The current application contains non-trivial domain work.

Examples include:

- auction optimization
- diverse draft strategies
- Monte Carlo category targets
- Forge Value / valuation logic
- all-play calculations
- category-direction rules
- historical standings reconstruction
- recap fact assembly
- deterministic awards
- projection normalization
- projection accuracy evaluation
- ESPN transport hardening

Do not assume these implementations should be preserved.

Do not assume they should be discarded either.

Evaluate them on their merits.

It is acceptable to preserve an algorithm or domain concept while completely replacing the surrounding architecture.

---

## 20. Architecture priorities

The target system should prioritize:

1. Correctness
2. Clear domain boundaries
3. Security and tenant isolation
4. Data durability
5. Understandability
6. Testability
7. Ease of adding product features
8. Operational simplicity
9. Performance
10. Scalability appropriate to realistic demand

Prefer boring, explicit systems over unnecessary abstraction.

Do not introduce microservices, queues, event buses, distributed systems, or complex infrastructure merely because they are architecturally fashionable.

Use complexity only where the problem actually requires it.

---

## 21. Developer and agent comprehensibility

A strong engineer or coding agent entering the repository should be able to quickly answer:

- Where does external data enter FCP?
- What is the canonical FCP player?
- What is the canonical league?
- What is the canonical fantasy team?
- What is the canonical roster?
- What is the canonical matchup?
- What is the canonical projection?
- Where does fantasy basketball business logic live?
- Where does user-specific logic live?
- What data is persisted?
- What data is calculated?
- What data is current?
- What data is historical?
- What data belongs to a user?
- What data belongs to a league?
- What can each user access or mutate?
- Where should a new feature be implemented?

If answering those questions requires extensive repository archaeology, the architecture has failed.

---

## 22. Explicit non-goals for the rebuild

Do not build these unless they are required by the chosen initial vertical slice:

- native mobile apps
- real-time chat
- a social network
- support for every fantasy platform
- massive distributed infrastructure
- generalized multi-sport architecture
- every future fantasy tool
- speculative ML infrastructure
- every possible projection provider
- real-time NBA play-by-play
- premature billing complexity

Leave reasonable room for future growth without implementing hypothetical products.

---

## 23. Architectural north star

FCP should ultimately feel like:

**A shared fantasy league world that is fun to follow, powered underneath by a private analytical weapon for managers who want to win.**

The shared experience creates engagement.

The private tools create competitive value.

The basketball intelligence layer powers both.

The architecture should make those relationships obvious rather than allowing them to become three unrelated products accidentally sharing a repository.
