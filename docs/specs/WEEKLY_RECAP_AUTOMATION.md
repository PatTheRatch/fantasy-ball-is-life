# Feature Spec: Weekly Recap Automation

**Status:** Pending Patrick + Aisha review — no implementation until
approved (`docs/AISHA_OPERATING_MANUAL.md` feature gate).
**Author:** Claude Code (implementation engineer)
**Date:** 2026-07-12
**Decision basis:** Patrick / dossier Decision D (2026-07-12): after the
backend package restructure, the next feature is closing the product loop —
schedule + deliver the weekly AI recap to the league group chat. Needed by
season week 1. Generation already ships; scheduling and delivery do not.
Patrick (2026-07-12): v1 channel is **WhatsApp** (how he sends the recap
today). Discord migration and a general “bot companion” are **explicit
non-goals for this feature**, but must still shape the architecture so they
are additive later.

---

## 0. Why now, concretely

- The product loop in [`docs/PROJECT_DOSSIER.md`](../PROJECT_DOSSIER.md) is
  Connect → Decide → Recap → **Deliver**. Steps 1–3 exist. Step 4 is the
  demo that sells the app to the league and the itch that started the
  project — and it is still manual: open Recap, click Generate, copy into
  WhatsApp.
- `POST /league-recap` already writes the newsletter
  (`backend/commentary/generate.py` + `prompts.py`). The React Recap page
  (`frontend/src/pages/Recap.tsx`) and Streamlit tab assemble the same
  payload (standings, power rankings, transactions, scoreboard, week
  dates) and call that endpoint. Automation is “run that pipeline on a
  schedule and push the text somewhere,” not a new AI product.
- Season week 1 is the deadline (Decision D). Draft Room is feature-paused;
  backend restructure PRs #13/#14 cleared the package layout so
  scheduler/delivery code has a natural home.
- Patrick currently pastes into a **WhatsApp** group. He also wants to talk
  the league into **Discord** later (bots become first-class). Longer-term
  product imagination: a **bot companion** other leagues could add to
  *their* chats. Neither Discord nor the companion is in v1 scope — but
  hard-wiring WhatsApp into the orchestrator would make both expensive.

---

## 1. User story

> As the commissioner of my ESPN fantasy basketball league, I want the
> weekly AI recap to generate and land in our WhatsApp group on a schedule
> after each matchup week ends, so I stop clicking Generate and
> copy-pasting — and so the league gets the newsletter whether or not I
> remember Sunday night.

Secondary (architecture / product): as the product owner, I want delivery
behind a small channel adapter so a later Discord (or multi-tenant bot
companion) is a new adapter + config, not a rewrite of scheduling or
generation.

---

## 2. Acceptance criteria

1. **Scheduled run.** After a matchup week ends, a job runs without human
   intervention (exact fire time and “week is final” signal = open question
   §Open questions #3). For the configured league, it produces one recap for
   that week.
2. **Server-side assembly.** The job gathers the same inputs the Recap page
   already sends to `POST /league-recap` (week, league settings, standings,
   power rankings, transactions, scoreboard, week dates) **on the server**.
   The browser is not required. Prefer reusing existing `backend.league` /
   commentary helpers over duplicating Recap.tsx fetch logic.
3. **Generate via existing path.** Recap text comes from the existing
   commentary stack (`generate_league_recap` / equivalent). No parallel
   prompt or model path in v1.
4. **Deliver to WhatsApp.** The resulting text is delivered to the
   configured WhatsApp destination (mechanism = open question §Open
   questions #1). A successful run leaves an observable record that the
   week was delivered.
5. **No silent skips.** If assembly, generation, or delivery fails, the
   failure is visible (structured log + run-log entry with error). Alert
   path for “Patrick should look” is TBD in open questions but “only
   stdout on a forgotten VPS” is not enough.
6. **Manual escape hatch.** An authenticated “run now for week N”
   path (CLI and/or admin API) supports missed weeks, regenerates, and
   dry-runs without waiting for the schedule.
7. **Channel adapter.** Delivery goes through a `DeliveryChannel`
   interface (e.g. `send(text, destination) -> DeliveryResult`). WhatsApp
   is the v1 implementation. Orchestrator and scheduler must not import
   WhatsApp SDKs directly.
8. **Kill switch.** Scheduling can be disabled via env/config without
   undeploying. Manual Recap page remains fully usable (today’s workflow
   is the rollback).
9. **Idempotency.** Re-running the same week does not spam the group by
   default (e.g. skip if a successful delivery already exists for that
   week+league, unless the operator forces regenerate). Exact policy =
   open question detail under #4 / #5.

---

## 3. Data model impact

No database in v1 (consistent with projection-framework and current
repo). Propose on-disk / env config:

**Delivery config** (env + optional `data/recap/delivery.json`, gitignored
secrets in env only):

| Field | Notes |
|---|---|
| `league_id` | ESPN league (already in `backend.config`) |
| `channel` | `whatsapp` for v1; reserved: `discord`, `log` (dry-run) |
| `destination` | channel-specific handle (group id, chat id, …) |
| `schedule_enabled` | bool kill switch |
| `timezone` | for cron / fire-time interpretation |

**Run log** (append-only JSONL or one JSON file per week under
`data/recap/runs/`, gitignored):

| Field | Notes |
|---|---|
| `week` | matchup period |
| `league_id` | |
| `started_at` / `finished_at` | ISO timestamps |
| `status` | `success` \| `failed` \| `skipped` \| `dry_run` |
| `channel` / `destination` | what we aimed at |
| `error` | null or message |
| `recap_chars` / optional hash | enough to prove generation happened without storing full PII-heavy text if we choose not to |

When a real DB lands later, these two shapes become the first delivery
tables. **Do not store WhatsApp credentials in the run log.**

---

## 4. API / UI impact

### Package layout (proposed)

```
backend/
  commentary/     # already exists — prompts + generate (unchanged contract)
  delivery/       # NEW — DeliveryChannel protocol + WhatsApp adapter (+ LogChannel dry-run)
  jobs/           # NEW — assemble week payload → generate → deliver; schedule entrypoint
  api/
    routers/
      commentary.py   # existing /league-recap
      # optional: thin admin trigger under commentary or a small recap router
```

This is the home the restructure spec said recap scheduling wanted
(`docs/specs/BACKEND_RESTRUCTURE.md` §0).

### API

| Surface | Role |
|---|---|
| Existing `POST /league-recap` | Unchanged. Human Recap page keeps calling it. |
| Proposed `POST /recap/run` (or CLI `python -m backend.jobs.recap_weekly --week N`) | Authenticated/manual: assemble → generate → deliver (or `--dry-run` = log channel only). |
| Optional `GET /recap/runs` | List recent run-log entries for ops / a tiny status strip. |

Auth model for `/recap/run` is an open question (#4) — Patrick-only shared
secret is enough for v1 if we do not expose it to the league UI yet.

### UI

- **Recap page stays** the human preview / regenerate tool. No requirement
  to build a scheduling UI in v1.
- Optional later: a “last automated delivery” status line on Recap. Not a
  v1 acceptance criterion.

### Wire format

Zero change to `LeagueRecapBody` / `{ "recap": "..." }` unless assembly
discovers a missing server-side field the browser was inventing — if so,
extend carefully and keep the Recap page working.

---

## 5. Test plan

- **Week selection / “which week to run”** unit tests (given fake “now” and
  league settings, assert week N vs skip).
- **Payload assembly** unit tests against fixtures (no live ESPN): output
  matches the shape `LeagueRecapBody` expects.
- **Orchestrator** tests with mocked generate + mocked `DeliveryChannel`:
  success writes run log; failure records error and does not mark success;
  second run without `--force` skips when success already logged.
- **WhatsApp adapter** tests with a mocked HTTP/client layer — no live
  Meta/bridge calls in CI.
- **Dry-run / LogChannel** proves the schedule path can run in CI without
  credentials.
- Full suite remains green; no live Anthropic or WhatsApp in the default
  CI job.

Manual smoke (post-merge, Patrick): dry-run for last completed week →
inspect log → one real WhatsApp delivery to a test destination before
pointing at the league group.

---

## 6. Rollback / failure considerations

- **`schedule_enabled=false`** (or equivalent env) stops automated runs
  immediately; no code revert required.
- **Manual Recap page** remains the full fallback (generate + copy to
  WhatsApp by hand) — same workflow as today.
- **Adapter failure** must not corrupt ESPN or commentary state; run log
  records the failure; optional alert (open question) notifies Patrick.
- **Bad / half-final scoreboard:** prefer failing loud or delaying the
  run over posting a wrong “final” recap (ties to open question #3).
- **Credential leak risk:** WhatsApp tokens only in env / secret store,
  never in run logs or client bundles.
- Revert of an implementation PR returns to manual-only; on-disk run logs
  are disposable.

---

## Design sketch (for review, not binding)

```
                    ┌─────────────┐
  cron / APScheduler│  jobs/      │
  or HTTP trigger ─►│ recap_weekly│
                    └──────┬──────┘
                           │ assemble(week) via backend.league.*
                           ▼
                    ┌─────────────┐
                    │ commentary/ │  generate_league_recap(body)
                    └──────┬──────┘
                           │ text
                           ▼
                    ┌─────────────┐
                    │ delivery/   │  DeliveryChannel.send(text, dest)
                    │  WhatsApp*  │  (*v1)  LogChannel (dry-run)
                    │  Discord†   │  (†later — not this feature)
                    └─────────────┘
```

**Recommended phasing after approval** (Aisha may adjust):

- **PR A** — `jobs/` orchestrator + server-side assembly + `LogChannel`
  dry-run + run log + manual CLI/`POST /recap/run`. Prove “week N → text
  → log” without WhatsApp credentials.
- **PR B** — WhatsApp `DeliveryChannel` adapter + schedule host wiring +
  kill switch. Point at a test destination, then the league group.

---

## Non-goals (this feature)

1. **Discord league migration.** Patrick wants to move the fantasy chat to
   Discord eventually so bots are first-class. Out of scope here. v1 must
   not hard-code WhatsApp types into the orchestrator so a Discord adapter
   is a follow-up PR, not a redesign.
2. **Bot companion product.** Longer-term: a bot other managers could add
   to *their* fantasy chats (multi-tenant). Out of scope. The
   `DeliveryChannel` + league-scoped config in §3/§4 is the seam that keeps
   that door open; do not build OAuth, bot install flows, or multi-league
   delivery UI now.
3. **Rewriting recap voice / prompts.** Prompt quality work is separate;
   this feature schedules and delivers what already exists.
4. **Replacing the Recap page.** Automation complements it; it does not
   remove human preview/regenerate.

---

## Open questions (Patrick + Aisha)

1. **WhatsApp delivery mechanism (blocks PR B).** Personal **group** chats
   are the hard constraint. Options to pick explicitly:
   - **(a) WhatsApp Business Cloud API** — official, but poorly suited to
     joining an existing personal group as a peer; often means a business
     number messaging individuals, not “post in the group like Patrick
     does.”
   - **(b) Unofficial bridge / automation** (e.g. linked-device style) —
     can target groups; fragile, ToS risk, ops burden.
   - **(c) Deliver to Patrick only** (Business API or email/SMS) for
     **one-tap forward** into the group — least elegant, most honest for
     “keep using today’s WhatsApp group” without a shady bridge.
   - Recommendation for review: prefer **(c) for v1** unless Aisha signs
     off on (b); treat true group-native posting as a Discord-era win.
2. **Schedule host.** Always-on process (APScheduler in the API
   process or a worker) vs system cron on a VPS vs GitHub Actions cron vs
   external scheduler hitting authenticated `POST /recap/run`. Constraint:
   needs ESPN cookies + Anthropic key + delivery secrets at runtime; GHA
   is cheap but awkward for long-lived secrets and ESPN session health.
3. **Fire time / “week is final.”** When is a matchup week safe to recap?
   Wall-clock after ESPN week end? After `effective_current_week`
   advances? Delay buffer for late games / scoring corrections? How do we
   avoid posting mid-week as if it were final?
4. **Who may trigger / re-send.** Patrick-only shared secret vs any
   authenticated league user. Affects whether `/recap/run` is admin-only.
5. **Message formatting.** Post Claude’s raw markdown-ish text, or a
   WhatsApp-oriented plain-text formatter (length limits, no broken
   markdown)? Section headers from the existing prompt (HEADLINE, RESULTS,
   …) should remain readable either way.
6. **Alert on failure.** Email? Push to Patrick’s WhatsApp DM? Rely on
   checking `GET /recap/runs` / logs? Minimum bar for week-1 reliability.

---

## Resolved inputs (Patrick, 2026-07-12)

1. **Channel for v1:** WhatsApp (current manual destination).
2. **Discord / bot companion:** Not in this feature’s scope; architecture
   must keep them additive (`DeliveryChannel` + league-scoped config).
3. **Process:** Spec first for Patrick + Aisha review; implement only after
   approval (same gate as Draft Room / backend restructure).
