You are AIsha, Patrick's long-term collaborator and operator. Summarize everything we accomplished in our last session moving Full Court Press off Render and onto Patrick's VPS at fcp.patrickmcdowell.dev.

Cover these workstreams:

**Supabase / Database work**
- Reconciled two competing migration directories (supabase/migrations/ vs migrations/) — resolved espn_league_id type conflict (text vs bigint), kept text since backend casts via int(). Moved 003/004 into supabase/migrations/ with proper timestamps (20260717220000, 20260717230000). All 4 migrations synced local↔remote.
- Created pgp_sym_encrypt/pgp_sym_decrypt RPC functions in migration 20260717230000 — these were missing and both seed_league.py and credentials.py depend on them. Service-role only grants.
- Fixed bare-string RPC response bug in both _encrypt() and _decrypt() — they expected {pgp_sym_encrypt: "..."} dict but the RPC returns a bare encrypted string.
- Seeded ESPN SWID/S2 credentials encrypted into the leagues table via seed_league.py. Verified decryption round-trip works via resolve_league_context().
- Fixed PostgREST upsert: added ?on_conflict=league_id,season,phase query param — resolution=merge-duplicates alone silently fails with 409.
- Fixed refresh worker: P-3b flipped league_api.* endpoints to read from stored snapshots, but the worker IS what populates those snapshots. Rewrote refresh_league() to call live ESPN (data_feed.*, _live_power_rankings) directly. Added aggressive NaN/Inf scrubbing for JSON serialization.

**Self-hosting — Docker + Caddy on VPS**
- Created Dockerfile (Python 3.11-slim, non-root app user, HEALTHCHECK), docker-compose.yml (backend + Caddy, only Caddy publishes 80/443), Caddyfile (auto-HTTPS via Let's Encrypt, /api/* proxy with prefix strip, static file server with SPA fallback, security headers)
- Created .github/workflows/deploy.yml — push to main → tests → build frontend → scp to VPS → ssh docker compose up -d --build. Deploy key generated, installed on VPS as deploy user with narrowly-scoped sudo (/usr/bin/docker only).
- Created systemd timer (deploy/fcp-snapshot-refresh.{service,timer}) — fires every 15 min, curls admin refresh with WORKER_SECRET from EnvironmentFile.
- VPS bootstrap: fcp-svc user (nologin), app at /srv/fullcourtpress/, deploy user for CI, UFW (22/80/443 only), SSH hardened (no root login, no password auth), fail2ban, unattended-upgrades. .env 600 owned by fcp-svc.
- DNS: fcp.patrickmcdowell.dev A record → 178.105.181.43, Cloudflare grey cloud (DNS-only, no proxy — Caddy needs direct Let's Encrypt validation).
- Supabase Auth: Site URL = https://fcp.patrickmcdowell.dev, redirect allowlist includes /update-password, /reset-password, /login, /signup + localhost:5173 equivalents.
- Branding: "Patriot Games" → "Full Court Press" in frontend <title>, FastAPI title, Newsroom header, Weekly Recap header. Repo name and Supabase project ref left untouched.
- docs/DEPLOY.md runbook: bootstrap steps, deploy flow, rollback, logs, verification checklist.
- Known issue: Season Stats tab returns empty — the all_play computation path was also broken by P-3b read-path flip. Deferred to follow-up.

**Tooling**
- Created docs/claude-prompts/review-template.md — structured Claude review output (summary, issues by severity with file/line references, confidence score 1-10, APPROVED or CHANGES_REQUESTED).
- Created scripts/review.sh — one-command review helper: pipes git diff against main to Claude with the template, saves to /tmp.

Respond as if Patrick just asked "what did we do?" — conversational, no markdown headers, your voice. Hit the key points, skip the obvious. End with what's still pending.
