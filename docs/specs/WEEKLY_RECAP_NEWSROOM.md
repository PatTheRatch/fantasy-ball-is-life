# Feature Spec: Weekly Recap Newsroom & Publishing

**Status: APPROVED** — Aisha (architecture) + Patrick (product) on 2026-07-12.
Phase 1 implementation authorized. Phase 2 follows.

**Handoff note for agents (Claude, Codex, Cursor):** this spec is the single source of truth. All architecture decisions are recorded here. Before implementing, read this spec + `docs/AISHA_OPERATING_MANUAL.md` + `CONTRIBUTING.md`. Commit often, write tests, keep PRs small. If you hit an ambiguity not covered here, flag it — do not guess. The latest state of the repo is on `main`; pull before starting.

**Author:** Claude Code (implementation engineer), with Aisha + Patrick review
**Decision basis:** Dossier Decision D makes the weekly recap the next feature
after the backend restructure. Patrick's product interview (2026-07-12)
reframed v1 from automatic WhatsApp delivery into a persistent league
newsroom with reliable AI generation, admin-controlled publishing, and
WhatsApp-friendly copy tools. Bot delivery remains a future phase.

---

## 0. Why now, concretely

- The current workflow is expensive in attention: Patrick gathers the data,
  gives it to a chatbot, and iterates several times to correct context and
  formatting before pasting the result into WhatsApp.
- The app already has `POST /league-recap`, a Recap page, power rankings,
  standings, scoreboards, and transaction feeds. What it lacks is a durable,
  shared publication: generation is browser-driven, results live in
  `sessionStorage`, and every user could trigger another token-consuming run.
- The league should see one authoritative published edition per week, while
  Patrick privately generates, previews, refreshes, and publishes drafts.
- The result should feel like a league's own ESPN-style newsroom: attractive
  enough for members to revisit, structured enough to trust, and architected
  so the product can later support accounts, many leagues, public/private
  visibility, and bot delivery.

---

## 1. User stories

> As a league member, I want a polished weekly newsroom with the recap,
> matchup results, power rankings, transactions, awards, standings, and
> season statistics, so I can understand what happened without reading raw
> tables or a generic chatbot answer.

> As the league admin, I want to generate a private draft from validated,
> well-structured league data, preview it, refresh it if necessary, and
> publish one shared version, so users cannot burn my AI tokens or see
> inconsistent recaps.

> As the commissioner sharing into WhatsApp, I want one-click copy actions
> for a clean summary or the full narrative, so v1 improves today's workflow
> without depending on brittle WhatsApp group automation.

Secondary product story: each league ultimately has an account-backed hub,
public/private visibility, memberships, and its own newsroom URL. Week-one
ships one seeded public league with Patrick as admin; the data model and
authorization boundaries must not assume it is the only league.

---

## 2. Acceptance criteria

### Publication workflow

1. Public readers see only the latest **published** version for a league,
   season, and week. Drafts are never returned to anonymous readers.
2. An authenticated league admin can enter admin mode on the Recap page and:
   **Generate Draft → Preview → Publish**.
3. **Refresh Draft** creates a new private draft. It does not alter the
   currently published edition until the admin publishes the replacement.
4. Publishing a replacement atomically makes it current and retains the prior
   published version in admin history for rollback.
5. Ordinary users cannot call generation or publication endpoints. All users
   see the same persisted edition; page refreshes do not consume AI tokens.
6. Every completed, published week remains in a season/week archive. The
   latest published week opens by default; unpublished weeks are absent from
   public navigation.

### Data reliability and AI boundaries

7. Before generation, admin mode shows a data-readiness report covering:
   matchup completeness, all nine categories, standings, power rankings,
   prior-week comparison data, and transaction availability.
8. Missing data produces a prominent warning. Admin-only **Generate Anyway**
   requires a second confirmation listing exactly what is missing. The
   edition visibly discloses omitted/incomplete sections; the LLM must not
   infer missing facts.
9. The backend builds and persists a versioned, schema-validated weekly fact
   snapshot before calling the LLM. Browser-composed prose or unlabeled data
   dumps are not the source of truth.
10. Deterministic data renders matchup scores, category results, rankings,
    movements, transactions, standings, season statistics, and award winners.
    AI is limited to the lead story, matchup one-liners, ranking explanations,
    award explanations, and WhatsApp narratives.
11. The LLM returns validated structured JSON, not one unconstrained article
    string. Malformed output or unsupported references fail generation rather
    than partially publishing.
12. The structured output includes evidence references back to fact-snapshot
    IDs/keys where practical. Prompts explicitly prohibit facts not present in
    the snapshot.

### Public newsroom

13. Each league has a stable route:
    `/leagues/:leagueSlug/recaps/:season/:week`. Public leagues are readable
    without signing in; private-league rules are designed now and enabled
    when league onboarding ships.
14. The newsroom uses a hybrid premium-editorial layout: a spacious lead story
    followed by denser data tabs. It uses league/team logos, strong typography,
    ranking arrows, category bars, and small trend charts—not AI-generated
    cover art.
15. **Weekly Recap** is the default tab. Remaining tabs:
    **Matchups**, **Power Rankings**, **Transactions**, **Awards & Stats**, and
    **Standings & Season Stats**.
16. Matchups render as compact result cards with an AI-written one-line
    takeaway; each expands to the deterministic nine-category breakdown.
17. Power Rankings show frozen weekly rank, prior-published-week movement,
    record, all-play strength, category strengths, and a grounded explanation.
18. Transactions show both the selected week's chronological feed and a
    season activity leaderboard.
19. Standings & Season Stats uses a pinned team column, sortable visible
    columns, and NBA.com-style column groups:
    - **Overview:** rank, team, record, win percentage, playoff status
    - **Category Stats:** all nine categories, with **season totals**,
      **per-week averages**, and **category ranks** views
    - **Advanced:** all-play win percentage, luck ratio, power rank, movement
    - **Activity:** transaction count and transaction awards
20. Mobile layouts remain readable without requiring users to navigate one
    extremely wide table.

### Sharing

21. **Copy Summary** produces a WhatsApp-friendly version a few phone-scrolls
    long: bold headline/section labels, every matchup result plus a quick
    line, key ranking movers, selected awards, and the public newsroom link.
22. **Copy Full Recap** produces the complete narrative with WhatsApp-friendly
    headings and spacing but omits bulky tables.
23. Formatting is restrained: minimal emoji as section markers, no decorative
    emoji throughout the prose.
24. Published public editions have shareable URLs and rich social metadata
    (league logo, week, headline, summary) suitable for WhatsApp and Discord
    link previews.

---

## 3. Editorial model and awards

### Voice

Patriot Games defaults to professional sports journalism with witty, friendly
trash talk. Store this as a league-level `recap_voice` setting so future
leagues can choose a different tone. Aggressive or sensitive claims must not
be fabricated from tone alone.

### Awards

Winners/candidates are computed deterministically; AI writes only the
explanation. If the required evidence is unavailable, omit the award.

**Core weekly awards**

- Team of the Week
- Biggest Upset
- Blowout of the Week
- Photo Finish
- Luckiest Team
- Unluckiest Team
- Move of the Week — only when transaction-to-performance linkage is reliable

**Best rotating awards**

- Category King
- Stock Rising
- Falling Fast
- Fraud Watch
- Waiver Wire Wizard — only with reliable transaction/performance linkage
- Transaction Addict — can use validated transaction counts

The system selects only rotating awards with a genuinely strong candidate;
it does not fill a quota with weak or unsupported claims.

---

## 4. Data model impact (Supabase)

Supabase is the v1 system of record. The existing project is provisioned but
unused. Migrations live in the repository; secrets remain server-side.

### Core future-state entities

| Entity | Purpose |
|---|---|
| `profiles` | App profile linked to `auth.users` |
| `leagues` | Slug, name, logo, accent color, visibility, voice, owner, source IDs |
| `league_memberships` | User-to-league role (`owner`, `admin`, `member`) |
| `league_week_snapshots` | Immutable structured facts and data-quality report for one league/season/week |
| `recap_editions` | Versioned generated content with `draft`, `published`, or `superseded` status |

Suggested load-bearing fields:

```text
leagues:
  id, slug, name, logo_url, accent_color, visibility,
  recap_voice, owner_user_id, espn_league_id, created_at

league_week_snapshots:
  id, league_id, season, week, captured_at, schema_version,
  matchups_json, standings_json, power_rankings_json,
  transactions_json, season_stats_json, award_candidates_json,
  data_quality_json

recap_editions:
  id, league_id, season, week, version, snapshot_id,
  status, structured_content_json, data_warnings_json,
  created_by, created_at, published_at
```

Week-one seeds one `leagues` row for Patriot Games and one Patrick membership.
The schema is multi-league from day one; account registration, create/connect
league, invitations, and private-league onboarding are later UI phases.

### Authorization / RLS

- Anonymous users may read only published editions for `public` leagues and
  only the snapshot fields required to render those editions.
- Private-league reads require membership (future UI, policy designed now).
- Draft/history reads require league admin or owner role.
- Generate, refresh, publish, and rollback require league admin/owner role.
- LLM provider keys, ESPN credentials, and the Supabase service-role key never
  reach the browser.
- Publishing a replacement occurs transactionally so there is exactly one
  current public edition per league/season/week.

---

## 5. API / UI impact

### Backend

Proposed package ownership:

```text
backend/
  commentary/
    prompts.py          # structured, evidence-bound prompt builders
    generate.py         # structured LLM call + response validation
    schemas.py          # fact snapshot + generated-content models
  recaps/
    assemble.py         # ESPN/data layer → deterministic weekly snapshot
    awards.py           # deterministic award selection
    publish.py          # versioning + atomic publish/rollback
    sharing.py          # WhatsApp summary/full formatters
  api/routers/
    commentary.py       # existing commentary endpoints during migration
    recaps.py           # public reads + authenticated admin actions
```

Indicative API:

| Method | Surface | Access |
|---|---|---|
| `GET` | `/leagues/{slug}/recaps` | Public archive for public leagues |
| `GET` | `/leagues/{slug}/recaps/{season}/{week}` | Published edition only |
| `POST` | `/leagues/{id}/recaps/{season}/{week}/generate` | Admin; creates draft |
| `POST` | `/leagues/{id}/recaps/{season}/{week}/publish` | Admin; atomically publishes selected draft |
| `POST` | `/leagues/{id}/recaps/{season}/{week}/rollback` | Admin; restores prior version |
| `GET` | `/leagues/{id}/recaps/{season}/{week}/history` | Admin |

The existing `POST /league-recap` remains during migration, then becomes an
internal generation path or compatibility endpoint. Public clients never send
raw fact payloads to generate their own editions.

### Frontend

- Move from one global `/recap` experience toward a league hub and stable
  league-scoped route. Existing single-league navigation can redirect to the
  seeded Patriot Games URL during week-one rollout.
- Public mode has no generation controls.
- Supabase-authenticated Patrick can toggle admin mode on the same Recap page.
  Admin mode exposes readiness, draft preview, Generate/Refresh, Publish,
  version history, and rollback.
- Season selector + week selector drive the archive; latest published opens
  by default.
- League masthead uses league name/logo and configurable accent color.

### Structured generated content

The validated response schema includes at least:

```text
headline
dek
lead_story[]
matchup_takeaways[{matchup_id, text, evidence_ids[]}]
ranking_explanations[{team_id, text, evidence_ids[]}]
award_explanations[{award_id, text, evidence_ids[]}]
whatsapp_summary
whatsapp_full
```

Deterministic facts are not duplicated as AI-authored values.

---

## 6. Test plan

- **Snapshot assembly:** fixture ESPN/data inputs produce exact canonical
  matchups, category results, standings, rankings, transactions, and quality
  warnings.
- **Completeness:** missing category/standings/transactions produces the
  correct readiness state; Generate Anyway records and exposes warnings.
- **Awards:** deterministic fixtures prove upset, margins, luck/all-play,
  ranking movement, category dominance, and transaction-data gating.
- **Structured generation:** mocked LLM responses validate schema and evidence
  references; malformed or unknown references fail without creating a
  publishable draft.
- **Publication:** draft privacy, atomic replacement, version history,
  rollback, and one-current-edition constraints.
- **RLS:** anonymous public read, anonymous draft denial, private-league denial,
  member read, non-admin write denial, owner/admin generation and publish.
- **UI:** latest-week default, archive navigation, tab rendering, admin/public
  control separation, sortable column groups, mobile behavior, and both copy
  formats.
- **Token guard:** repeated public reads never invoke generation; unauthorized
  generation returns 401/403 before any paid LLM call.
- **Regression:** current league data endpoints and other commentary endpoints
  remain green.

No live LLM, ESPN, or Supabase production calls in default CI. Use local
Supabase/test migrations or isolated fixtures.

---

## 7. Rollback / failure considerations

- The currently published version remains visible while draft generation or
  refresh fails.
- Publishing is transactional; readers never observe a half-published edition.
- Admin can roll back to a prior published version.
- If Supabase is unavailable, show the last client-cached published edition
  where available and a clear unavailable state; do not fall back to
  user-triggered AI generation.
- If transaction data is unreliable, mark it unavailable and omit dependent
  awards rather than guessing.
- If generation is forced with incomplete data, persist and display the exact
  warnings on that edition.
- Feature rollback leaves the existing manual Recap flow available until the
  new newsroom is proven; remove compatibility only in a later cleanup PR.

---

## 8. Phasing

### Week-one product

1. **Supabase foundation:** migrations, RLS, Patrick auth, seeded public Patriot
   Games league, membership, versioned snapshots/editions.
2. **Reliable generation + publishing:** deterministic assembler and awards,
   structured LLM output, readiness warnings, admin mode, draft/publish/history.
3. **Public newsroom:** league-scoped routes, archive, six tabs, grouped
   standings/stat views, WhatsApp Copy Summary / Copy Full Recap.

### Future-state phases (designed now, not required for week one)

4. Account registration, create/connect league onboarding, memberships,
   invitations, public/private controls, and multi-league navigation.
5. Separate **Midweek Report** edition type using live scores/projections.
   It must never masquerade as a final Weekly Recap.
6. Channel adapters and scheduled delivery: Discord first-class if the league
   migrates; WhatsApp only through an official/safe route. A general bot
   companion remains a later product.

---

## 9. Non-goals for week one

- Automatic posting into the existing WhatsApp group.
- Discord migration or bot installation flows.
- General multi-league onboarding UI, despite multi-league schema/RLS.
- Midweek reports.
- AI-generated cover art.
- Manual line editing or section-by-section correction tools. Reliability
  comes from canonical data, deterministic facts, evidence-bound prompts, and
  schema validation; admin may refresh the whole draft.

---

## 10. Resolved by Aisha + Patrick (architecture review, 2026-07-12)

1. **Runtime boundary: FastAPI.** ESPN + LLM provider calls are Python-native and already work in FastAPI. Supabase Edge Functions add a second runtime, deploy pipeline, and cold-start latency for no gain. Generation/publication stays in `backend/recaps/` served by FastAPI. Supabase is storage + auth only, not compute.

2. **Social previews: Defer to Phase 2.** Copy Summary / Copy Full Recap solves the WhatsApp sharing problem without OG meta tags. Add edge-rendered share pages when the public newsroom ships.

3. **Snapshot storage: JSONB + relational metadata.** Agree with the recommendation. Versioned JSONB for the week's fact snapshot, relational columns for `league_id`, `season`, `week`, `status`, `created_by`, `published_at`. Normalize individual entities only when query needs demand it.

4. **Transaction quality gate: Audit first.** Move of the Week and Waiver Wire Wizard gated behind a feed audit. Spot-check the last 4 weeks of ESPN transactions against actual roster moves. If the feed misses waiver claims or has timestamp errors, those awards ship disabled with a visible "data quality" flag. Transaction Addict (counts only) is safe to ship immediately.

5. **Migration of `POST /league-recap`:** Keep as compatibility endpoint until the newsroom is proven stable on the new generation path, then remove. No new features depend on it.

6. **RLS: Schema-ready now, enforce later.** Design the Supabase schema with RLS policies from day one, but for v1 with one seeded public league, enforce admin-only generation via a simple `admin_user_id` check on the league row. Enable RLS enforcement when multi-league onboarding ships.

7. **Phase 1 LLM provider: DeepSeek.** Use the configurable provider boundary in
   `backend/commentary/generate.py`, with `deepseek-v4-flash` as the default
   structured-recap model while validating the workflow at lower cost. Keep
   Anthropic support for the existing compatibility commentary endpoints and
   as a configurable recap fallback. Provider output must pass the same JSON
   schema and evidence validation before a draft can be created.

### Phasing (Aisha, 2026-07-12)

Original §8 proposed launching everything at once. Revised plan: two phases so the workflow improvement ships immediately.

**Phase 1 — Ship first (replaces Monday workflow)**:
- Supabase foundation: migrations, seeded Patriot Games league, Patrick auth, versioned snapshots/editions
- Reliable generation: deterministic assembler + awards, structured LLM output, readiness warnings
- Admin mode: Generate Draft → Preview → Publish, version history, rollback
- **Copy Summary / Copy Full Recap buttons** — the killer feature. Replaces the 2-hour Monday morning workflow in one click

**Phase 2 — Follow-up (public consumption)**:
- League-scoped public newsroom routes: `/leagues/:slug/recaps/:season/:week`
- Six tabs: Weekly Recap, Matchups, Power Rankings, Transactions, Awards & Stats, Standings & Season Stats
- Archive navigation, sortable standings, mobile-responsive layouts
- Social previews (OG meta tags) for shareable URLs

Everything after Phase 2 (multi-league onboarding, midweek reports, bot delivery, Discord) stays as future-state per §8.

---

## Resolved by Patrick (product interview, 2026-07-12)

1. V1 is **newsroom + admin publishing + copy tools**, not bot delivery.
2. Weekly Recap is the default tab; Matchups, Power Rankings, Transactions,
   Awards & Stats, and Standings & Season Stats are subtabs.
3. Admin workflow is Generate Draft → Preview → Publish. Refresh does not
   replace the public edition until publish.
4. Users see only the shared published edition and cannot spend AI tokens.
5. Every completed published week remains archived.
6. Supabase is committed for storage and Patrick admin auth.
7. Future model is account-backed, multi-league, and public/private; week one
   seeds one public league instead of shipping full onboarding.
8. Public URL is league/season/week scoped; latest published opens by default.
9. AI writes narrative only; factual tables, rankings, outcomes, and award
   winners are deterministic.
10. Incomplete data warns but admin may Generate Anyway after explicit
    confirmation. Midweek reports are a separate future edition.
11. The visual direction is premium-editorial lead story plus denser data tabs,
    using real league/team branding and data visualization—not AI art.
12. WhatsApp offers Copy Summary and Copy Full Recap; summary includes every
    matchup result and a quick line, ranking movers, awards, and the app link.
13. Re-publishing retains prior versions for admin rollback.

---

## Addendum: Playoff-week narrative mode (2026-07-13)

Prompted by a live playoff-week generation (semifinals, round 2 of 3) where
the recap read as a flat regular-season week despite obvious bracket stakes.
Patrick's own hand-written recap for that week (shared as a reference) uses a
denser structure than the regular-season narrative: a per-matchup "what
really happened" account, a "what this sets up" note per advancing team,
2-4 cross-team storylines, and a closing line.

**Scope decisions (Patrick, 2026-07-13):**
1. Playoff mode is **automatic** — detected from league settings
   (`reg_season_count`, `playoff_team_count`, `playoff_matchup_period_length`),
   not an admin toggle.
2. Adopt the denser structure for playoff weeks specifically, as new
   *additive* fields on `RecapGeneratedContent` (`playoff_matchup_recaps`,
   `playoff_outlook`, `playoff_storylines`, `playoff_final_line`) — empty for
   a regular-season week, so the existing schema/prompt/UI is unaffected
   outside the playoffs.

**What's deterministic vs. AI, same boundary as the rest of this spec:**
- Round label (Quarterfinals/Semifinals/Championship/Round N), advancing and
  eliminated teams, and next-round pairings are computed server-side
  (`backend/recaps/playoffs.py`) from league settings and this week's decided
  matchups — never inferred by the LLM.
- Next-round pairings are only included once every advancing team appears in
  ESPN's own schedule for that week as a distinct participant; otherwise
  omitted rather than guessed from a reseeding assumption we don't control.
- The LLM writes the four new narrative fields, evidence-bound to the same
  snapshot facts as everything else (matchup evidence IDs, no invented
  transactions/injuries -- that would require the still-open transaction-feed
  item in `docs/ESPN_INTEGRATION_AUDIT.md`).

**Known limitation:** the sample recap that prompted this leaned on
injury-report detail (specific players out, DNPs) that isn't derivable from
the current fact snapshot. That requires the transaction/roster-move feed,
which is a separate, still-open audit item -- playoff mode does not depend on
it and degrades gracefully without it.

---

## Addendum: Recap voice spec + WhatsApp narrative (2026-07-13)

Patrick supplied a full recap-voice specification (distilled from a year of
his prior chatbot workflow). Universal, league-agnostic rules now live in the
structured-recap system prompt (`backend/commentary/prompts.py`); anything
Patriot-Games-specific (rivalries, history, notorious managers) belongs in
the `leagues.recap_voice` column, which the prompt appends verbatim when set.

**WhatsApp format decision (Patrick, 2026-07-13): hybrid.** The old
implementation discarded the model's `whatsapp_summary`/`whatsapp_full` and
rebuilt them as a deterministic bullet digest — complete but report-like.
Now the model writes both fields as flowing prose (per the voice spec's
30-second-read shape), and generation is rejected by a deterministic
backstop (`_validate_whatsapp_completeness` in
`backend/commentary/generate.py`) unless every matchup's team names and
every award winner are actually named in both fields. `format_share_text`
only appends the public URL. This updates acceptance criteria 21-22's
"itemized" reading: completeness is still guaranteed, but by validation
rather than by assembly. On playoff weeks the prompt requires the round,
advancement, and final line to be woven into the same prose — no labeled
bullet sections.

---

## Addendum: Phase 2 execution plan (2026-07-13)

Phase 1 (admin generate → preview → publish) shipped, and the ESPN hardening
detour (E1–E3, F, G) that made generation reliable is complete. Phase 2 — the
public newsroom — was spec'd in §8 but never sequenced. This is the plan.

**Key framing:** every Phase 2 tab renders data the snapshot *already*
persists (`standings`, `power_rankings`, `transactions`, `season_stats`,
`award_candidates`) plus AI text the generator *already* produces but nothing
currently displays (`ranking_explanations`, `award_explanations`). So Phase 2
is overwhelmingly a frontend rendering effort, not new data plumbing — lower
risk than the hardening work that preceded it.

| PR | Scope | Notes |
|---|---|---|
| **F2-1** | Tab scaffold + league-scoped route (`/leagues/:slug/recaps/:season/:week`) + archive/week navigation; move the current single-page recap into the **Weekly Recap** tab; redirect the legacy `/recap` route | Foundation every other tab sits in |
| **F2-2** | **Matchups** tab — compact result cards, expandable to the deterministic 9-category breakdown | data in `snapshot.matchups` |
| **F2-3** | **Power Rankings** tab — frozen weekly rank, prior-published-week movement, record, all-play strength, category strengths, grounded explanation | `ranking_explanations` already generated, currently unused |
| **F2-4** | **Transactions** tab — weekly chronological feed + season activity leaderboard | data in `snapshot.transactions` |
| **F2-5** | **Awards & Stats** tab — render `award_candidates` + `award_explanations` | count-based awards live immediately; Move of the Week / Waiver Wire Wizard render only when the Transaction Intelligence track (below) is enabled |
| **F2-6** | **Standings & Season Stats** tab — its own PR (Patrick, 2026-07-13). NBA.com-style column groups (Overview / Category Stats with season-totals + per-week-avg + category-rank views / Advanced / Activity), pinned team column, sortable | the heaviest single tab; data in `snapshot.standings` + `season_stats` |
| **F2-7** | **OG social previews** — **last** (Patrick, 2026-07-13) | Prerequisite: the app is a SPA, so OG meta tags need SSR or a prerender/edge-render step. That infra decision is made when F2-7 starts, not before |

F2-1 through F2-5 are each small and low-risk (render existing data). F2-6 is
the biggest build. F2-7 has a real infra prerequisite and is deliberately last.

**AI-verdict labeling (cross-cutting, Patrick 2026-07-13):** anywhere a tab
shows an AI-authored verdict next to a hard number — award explanations,
ranking takes, and especially the move-grading below — the AI portion must be
visually marked as an AI take (a badge/label distinct from the deterministic
facts beside it), with a short disclaimer. Deterministic facts and AI opinion
never render as the same kind of thing.

---

## Addendum: Transaction Intelligence track (2026-07-13)

A separate track from the Phase 2 render tabs. Where Phase 2 displays data we
already have, this *produces new* analysis: grading whether a roster move
actually helped, and (later) inferring its motive. Kept out of F2-5 so the
Awards tab ships on time with count-based awards while this develops on its
own schedule, data-source decision, and quality gate.

### Motivation

The current transaction feed (PR #19 `mTransactions2` adapter) gives us
executed adds/drops/trades with `player_id`, `date`, `bid_amount`, and team
attribution — enough for *counts*, not enough to judge a move. Judging a move
needs player performance: the added player's baseline (season/recent average)
vs. their production since the pickup, and — the fun one — the *dropped*
player's production after the drop ("dropped X, then X went off — bad move").

### Data source decision — prefer an external daily-stats source over ESPN

ESPN *can* provide daily player production (NBA fantasy scoring periods are
daily; `Player.stats` carries per-scoring-period splits with dates, and
`get_player_card` fetches them). **But** daily, per-player pulls are exactly
the request fan-out the E-series just eliminated — routing this through ESPN
would re-introduce it. **Decision (Patrick, 2026-07-13): source daily player
stats from an external NBA stats API** (e.g. a stats.nba.com wrapper or
similar) so move-grading costs zero ESPN calls.

- **The real work is the player-ID join**, not finding the source: an external
  source won't share ESPN's `player_id`, so we match on name — and we already
  have that machinery (`normalize_name` / `fuzzy_map_names` in `data_feed.py`,
  the same fuzzy matcher that maps BBM projection names to ESPN players).
- A source scan (licensing, cost, rate limits, ID-mapping quality) is the
  first concrete task before any build.

### Deterministic facts vs. AI verdict

Same boundary as the rest of the newsroom. Code computes and surfaces the
*facts* as evidence — added player's since-pickup production vs. season
average, dropped player's post-drop production, category deltas. The LLM
writes the "great pickup / bad drop" *verdict*, grounded in those numbers.
Deterministic code never hard-declares "bad move." Per the labeling decision
above, the verdict renders with a visible AI-take badge + disclaimer.

### Parked future item — inferred transaction motive

A richer, subjective layer: infer *why* a move was made by intersecting the
added player's category profile with the team's category deficits at
transaction time (e.g. "dead-last in blocks that week, picked up a
shot-blocker → motive: chasing blocks"). Feasible — the all-play / per-category
machinery already tracks weekly category standing, and we know the
transaction's week — but a large build layered on top of the move-grading
engine, and inherently speculative (doubly bound by the AI-take labeling).
**Captured, not scoped into Phase 2.** Candidate for a "subjective motive"
surface in the Transactions tab once the grading engine exists.
