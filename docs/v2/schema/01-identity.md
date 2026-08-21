# 01 · Identity

**Domain:** login accounts, fantasy manager personas, and who owned which team when.
**Depends on:** nothing. Foundation.
**Charter:** Decisions 9 (co-managers), 13 (User ≠ Manager), 8 (identity persists across seasons).

> Read [`README.md`](README.md) first. Conventions there are binding.

---

## The central distinction

Charter Decision 13: *"A login User is not the same thing as a fantasy Manager. Manager identity survives team changes, co-management and historical ownership."*

This matters more than it first appears, and it is the one modelling choice in this domain that everything else leans on:

- A **user** is an authentication subject. It exists because someone signed up.
- A **manager** is a persona in a league's history. It exists because someone played.

They are not the same because **a manager can exist without a user.** If a league joined FCP in 2026 and imported four prior seasons, the managers from 2023 are real historical entities — they owned teams, made trades, won titles — but most of them will never create an account. Modelling ownership on `users` would make that history unrepresentable, and the product thesis is league history.

The reverse also holds: one user may claim more than one manager (rare, but it happens when someone has played under two identities across leagues), and a manager may be claimed later, retroactively linking a real person to history that already exists.

---

## Tables

### `users`

**Scope:** `user` · **Freshness:** `synced` (mirrors the identity provider)

```sql
create table users (
  id              uuid primary key,
  auth_subject    text not null unique,     -- IdP subject claim (Supabase `sub`)
  email           citext not null unique,
  display_name    text not null,
  is_active       boolean not null default true,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
```

Notes:

- `auth_subject` is the join to the identity provider. FCP does not store passwords; authentication is delegated, authorization is ours.
- `citext` on email so `Pat@x.com` and `pat@x.com` cannot both exist.
- Deactivation is a flag, never a delete — a deleted user would orphan authored history (published recaps, resolved identity links).

### `managers`

**Scope:** `global` (a manager may play in several leagues) · **Freshness:** `reference`

```sql
create table managers (
  id              uuid primary key,
  display_name    text not null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
```

Notes:

- Deliberately thin. A manager is an identity, not a profile; anything league-specific belongs on the team-season link.
- **No `user_id` column.** The relationship is many-to-many and optional in both directions — see `manager_user_links`.
- Created two ways: when a user claims a team, or when ingestion encounters a historical owner with no FCP account.

### `manager_user_links`

**Scope:** `user` · **Freshness:** `reference`

```sql
create table manager_user_links (
  id              uuid primary key,
  manager_id      uuid not null references managers(id),
  user_id         uuid not null references users(id),
  is_primary      boolean not null default true,
  linked_at       timestamptz not null default now(),
  linked_by_user_id uuid null references users(id),  -- admin claim on someone's behalf
  unique (manager_id, user_id)
);

create unique index manager_user_links_one_primary_idx
  on manager_user_links (manager_id) where is_primary;
```

Notes:

- An unclaimed manager simply has no row here. That is a valid, expected state.
- A manager has at most one primary user. Additional links exist for shared/legacy access.
- `linked_by_user_id` records an admin linking a historical manager to a real account, which is an auditable act.

### `fantasy_team_season_managers`

**Scope:** `league_season` · **Freshness:** `synced`

Who managed a given team in a given season, including co-managers.

```sql
create type manager_role as enum ('owner', 'co_manager');

create table fantasy_team_season_managers (
  id                      uuid primary key,
  fantasy_team_season_id  uuid not null references fantasy_team_seasons(id),
  manager_id              uuid not null references managers(id),
  role                    manager_role not null default 'owner',
  from_date               date null,          -- null = from season start
  to_date                 date null,          -- null = through season end
  created_at              timestamptz not null default now(),
  unique (fantasy_team_season_id, manager_id, from_date)
);

create index ftsm_manager_idx on fantasy_team_season_managers (manager_id);
create index ftsm_team_season_idx on fantasy_team_season_managers (fantasy_team_season_id);
```

Notes:

- **Attached to `fantasy_team_seasons`, not `fantasy_teams`.** Ownership changes between seasons; that is the normal case, not an edge case. This makes "who owned the Ballers in 2024?" a single indexed lookup with no date arithmetic.
- Charter Decision 9 (co-managers) is the multiple-rows case, distinguished by `role`.
- `from_date`/`to_date` handle mid-season handover, which does happen (someone abandons a team and it is taken over). Both null is the common case.
- No unique constraint forcing exactly one `owner` — a team genuinely can be co-owned with no single primary. If a league wants one, that is a league rule, not a schema rule.

---

## Privacy boundary

Charter Decision 12 and non-negotiable #1. **`manager_id` is the private-scope key for the entire platform.** Every private table in [`06-intelligence.md`](06-intelligence.md) — draft sessions, watchlists, notes, do-not-draft lists, projection preferences — keys off `manager_id`, not `user_id`.

Why manager rather than user: co-managers must see each other's private strategy for the team they share (Decision 9 is meaningless otherwise), and that grouping is a property of the manager-team relationship, not of the login.

The resulting access rule, which the repository layer enforces:

```
a user may read private data for manager M
  iff  a manager_user_link exists for (M, user)
       OR the user co-manages a team-season that M also manages
```

A league admin is **not** exempt. Charter §3: another manager must not see these, and an admin is another manager.

---

## Requests against other foundation domains

- `02-fantasy` must define `fantasy_team_seasons(id)` — referenced above.

---

## Open questions

1. **Manager merge.** Two provider identities may turn out to be the same person a season later (someone rejoins under a different display name). Merging managers means repointing team-season links and private data. Recommend a `merged_into_manager_id` column and a supersession approach rather than a destructive merge — but the private-data implications (whose watchlist survives?) need a product decision before it is built. Not slice 1.
2. **Cross-league manager identity.** `managers` is global, so the same person in two FCP leagues could be one manager or two. Recommend: one manager per person per *provider identity*, unified only by explicit user claim. Automatic cross-league identity merging violates "prefer unknown over confidently wrong."
