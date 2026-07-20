# Onboarding & Growth (N-series): landing, join, create-a-league

Design for how a stranger becomes a signed-up user, a leaguemate joins
Patriot Games without hand-provisioning, and (later) anyone sets up their
own ESPN league. Decisions resolved with Patrick 2026-07-19.

## Resolved decisions

1. **Public league semantics — "view open, join = claim a team."** Anyone
   with the link can VIEW a public league. Joining requires claiming an
   **unclaimed ESPN team** (first-come; admins can remove impostors and
   free the team). This soft-gates joining to actual leaguemates with no
   invite friction. Private leagues: invite link only, no self-join.
2. **League creation — open but capped.** Any signed-up user may own at
   most **2 leagues**. Cap enforced server-side at creation. (Each league
   costs real money: 15-min ESPN refreshes + Anthropic recap calls.)
3. **Email confirmation — required.** Supabase "Confirm email" turns on;
   unconfirmed accounts can't sign in. Redirect allowlist already covers
   the confirm flow.
4. **Landing demo — the live Patriot Games league.** The landing page
   links straight into `/leagues/patriot-games` (already `visibility=
   public`) as the "see it live" example.

## The journey

- **Logged-out `/`** → marketing landing (replaces today's redirect into
  the league): what FCP is, feature highlights (AI weekly recaps, power
  rankings, live matchups, awards), **"ESPN leagues only — Yahoo/Sleeper
  coming soon"** callout, live-demo link, Sign up / Log in CTAs.
- **Sign up** (P-5 pages, invite-param gate removed at N-2) → email
  confirm → log in.
- **Lobby** (signed in, zero memberships): "Join your league" (paste a
  league link, or you arrived via invite) · "Set up a new league" (N-4;
  hidden/disabled until then).
- **Join public league:** league page shows "Join this league" to signed-in
  non-members → pick an unclaimed team → membership row created, team
  claimed, done.
- **Join private league:** invite link (`/join?invite=<token>`) → redeem →
  member. No other path.
- **Create league (N-4 wizard):** ESPN league ID + season → cookies ONLY
  if the ESPN league is private (with sensitivity + "encrypted, we cannot
  read them" note — true via pgcrypto) → **live validation** against ESPN
  ("Found 'Patriot Games', 14 teams — is this yours?") → name/slug/accent
  (prefilled) + FCP visibility → claim your team → creator becomes
  owner/admin; league enrolls in the refresh worker.

## Data model & policy changes

- **`league_invites`**: `id, league_id, token (unique, random ≥128-bit),
  email (nullable), role default 'member', expires_at, created_by,
  used_by, used_at`. Admins manage via RLS (`is_league_admin`). Redemption
  via a **security-definer function** `redeem_league_invite(token)` that
  validates (unused, unexpired), inserts the membership for `auth.uid()`,
  and marks the invite used — so the token is never readable client-side.
- **Self-join INSERT policy** on `league_memberships`: authenticated may
  insert **their own** row (`user_id = auth.uid()`, `role = 'member'`)
  only when the target league has `visibility = 'public'`. (Today there is
  NO insert policy — nobody can join except via service role.)
- **Team-claim uniqueness**: unique partial index on
  `(league_id, lower(team_name)) where team_name is not null` — first
  claim wins; a second claimer gets a clean conflict error. Known
  fragility: claims are by team-name string; an ESPN rename orphans the
  claim (admin fixes in Settings). Acceptable v1.
- **Admin member management**: DELETE policy — admins may remove members
  of their league (`is_league_admin`), members may remove themselves.
  Removing a member frees their team claim.
- **Creation cap**: enforced in the backend create-league endpoint
  (count of `leagues.owner_user_id = user` ≥ 2 → 403). Creation MUST go
  through the backend (service role) anyway: pgcrypto RPCs are
  service-role-only and ESPN validation needs server-side fetch.
- **Credential health (N-5)**: per-league `last_refresh_ok_at` /
  `last_refresh_error`; worker writes them; league page shows an
  admin-only "Reconnect ESPN" banner when auth fails. Creds are
  write-only after save — display "Connected ✓ last verified <date>",
  never echo values.

## Phases

| Phase | Scope | Done when |
|---|---|---|
| **N-1** | Landing page at `/` for logged-out users (replaces redirect); minimal lobby for zero-membership users; HomeResolver wiring | Logged-out `/` shows landing w/ demo link + ESPN-only note; logged-in no-membership `/` shows lobby; existing members unaffected |
| **N-2** | Real invites + public self-join: `league_invites` migration, redeem function, self-join INSERT policy + claim-a-team join UI, admin "Invite members" in Settings, remove-member, signup gate opens (`VITE_SIGNUP_OPEN=true`), Supabase email-confirm ON | A stranger with the Patriot Games link signs up, confirms email, claims an unclaimed team, sees League Home as a member — zero manual DB work. Admin can mint/revoke invite links and remove a member |
| **N-3** | Multi-league de-rooting: remove baked `VITE_RECAP_LEAGUE_SLUG` from nav/API-client/resolver (active league from route/context); per-league season from `leagues.espn_season` (not `VITE_RECAP_SEASON`); worker loops ALL leagues (per-league failure isolation) | App works for a second seeded league end-to-end with no rebuild; worker refreshes both |
| **N-4** | Create-league wizard + backend endpoint: live ESPN validation, cookies-only-if-private branch, encrypted cred storage, cap=2, auto owner/admin + team claim, worker enrollment | A new user creates a working league solo; invalid ID/cookies rejected with clear errors at the validation step |
| **N-5** | Credential health: worker writes refresh status, admin reconnect banner + re-entry flow | Expired cookies surface a reconnect prompt within one refresh cycle instead of silent stale data |

Sequencing rationale: N-2 before N-3 because it delivers the immediate
value (Patrick's leaguemates join TODAY on the single hardcoded league);
de-rooting is the riskiest refactor and shouldn't block that. N-4 depends
on N-3 (a created league is useless while the frontend is pinned to one
slug).

## Security & cost notes

- Tokens: random ≥128-bit, single-use, expiring; redemption only through
  the definer function. Invite links may be sent over WhatsApp — treat
  possession as bearer auth for ONE membership, nothing more.
- The self-join policy's `with check` must pin `role = 'member'` so nobody
  self-promotes via the insert path.
- ESPN cookie handling unchanged from P-4: encrypted at rest, key in
  backend env, service-role-only RPCs. The wizard never round-trips them.
- Cost bounding: cap (2/user) + private-league invites keep worker/LLM
  spend proportional to real leagues. Revisit if it ever opens up.

## Out of scope (deliberately)

Yahoo/Sleeper adapters (landing says "coming soon"), ownership transfer,
league deletion/archival, public league directory/search (share-the-link
only), custom domains per league.

---

## Addendum: signup gate + email delivery (2026-07-20)

Two onboarding blockers found while trying to test the N-2b join flow.
Neither is a code defect in N-2/N-2b — both are configuration gaps that
make real onboarding impossible.

### Finding 1 — the "invite only" signup gate is cosmetic

`frontend/src/pages/Signup.tsx` reveals the form when `?invite=` is any
non-empty string; the value is **never validated** against anything.
Combined with Supabase `disable_signup: false` (verified live), signup is
**already open to the public** — anyone appending `?invite=x` can create an
account. The label is an illusion, which is the worst of both worlds:
no real protection, but a UX that tells legitimate users they can't join.

**Resolved (Patrick, 2026-07-20): genuinely open signup.** Set
`VITE_SIGNUP_OPEN=true` so `/signup` is honestly self-serve. This matches
the N-series plan (public leagues are join-by-team-claim; private leagues
are protected by real invite tokens at the DB layer, not by hiding the
signup form). Access control lives in RLS + `league_invites`, never in a
cosmetic query-param gate.

Rejected alternatives: validating `?invite=` against `league_invites`
before showing the form (adds friction for public-league self-join, which
by design needs no invite), and `disable_signup` at Supabase (blocks the
N-series entirely).

### Finding 2 — transactional email is unconfigured (the real blocker)

Supabase reports `mailer_autoconfirm: false`, so every new user must click
a confirmation link. The project is still on Supabase's **built-in SMTP**,
which is rate-limited to a few messages/hour and commonly spam-foldered —
Supabase documents it as unsuitable for production. Consequence: real
users cannot complete signup, and password reset (already shipped in P-5)
is equally affected. This is the single thing standing between "the app
works" and "a friend can actually join."

**Required:** configure a real SMTP provider (Resend / Postmark /
SendGrid) in Supabase Auth, with a verified sending domain and SPF/DKIM,
then verify confirm-signup and reset-password both deliver to a real
inbox (not spam). See the N-2c task.

### Ordering note

Opening signup (Finding 1) without working email (Finding 2) produces
accounts that can never confirm. Land the SMTP work first, or at minimum
land both together.
