# H-04b · Make route policy executable

**Status:** NEXT (assigned) · **Depends on:** H-04a (merged, `8127b84`) · **PR into:** `v2`
**Branch:** `fix/h-04b-policy-enforcement`
**Backlog:** [`docs/v2/BACKLOG.md`](../v2/BACKLOG.md) §Slice 1 hardening
**Source:** [`research/REDTEAM_TRIAGE.md`](../v2/research/REDTEAM_TRIAGE.md) §10
**Process:** [`CONTRIBUTING.md`](../../CONTRIBUTING.md)

> The enforcement half of H-04, and the close of the tenancy split. H-04a made
> repositories impossible to build unscoped; this makes a route's declared
> policy mean something.

---

## The bug

`api/policy.py:33-36` — `declare_policy` sets an attribute and nothing else:

```python
def decorator(endpoint: _F) -> _F:
    setattr(endpoint, POLICY_ATTR, policy)
    return endpoint
```

`tests/api/test_route_policy_matrix.py:39-54` then asserts only that the
attribute is *present*. So this passes CI today:

```python
@router.get("/leagues/{league_season_id}/secrets")
@declare_policy(RoutePolicy.LEAGUE_SCOPED)     # a label, nothing more
def secrets(league_season_id: uuid.UUID, session: Session = Depends(get_db)):
    ...                                        # no membership check anywhere
```

The declaration is a promise the harness never checks. Charter D26 asks for the
opposite: *"a route-policy test fails CI on any route without an explicit
declared policy."* We built the half that checks a policy exists and never
built the half that checks it is honoured.

**No live hole** — all three current routes are correct. This closes the door
before there are thirty of them. V1 shipped 53 unauthenticated routes, and each
one was a forgetting.

## The fix

Extend the existing matrix test to walk each route's **dependency graph** and
assert the policy's required dependency is present.

### The map, and why it must be total

```
PUBLIC           → nothing required
AUTHENTICATED    → get_current_user
LEAGUE_SCOPED    → require_league_member
MANAGER_PRIVATE  → no dependency exists yet
```

`MANAGER_PRIVATE` is the interesting one. No route declares it and no gate
exists for it. **Do not skip it or map it to `None`.** Make the map total over
`RoutePolicy` and fail when a policy has no enforcement rule defined, so that
the first person to declare `MANAGER_PRIVATE` before writing its gate is
stopped by CI rather than shipping a label. A policy the harness cannot enforce
must not be declarable.

That is two distinct assertions, and both belong in this bite:

1. every route satisfies its policy's rule;
2. every `RoutePolicy` member has a rule.

### Walking the graph

FastAPI exposes `APIRoute.dependant`, a `Dependant` with `.call` (the function)
and `.dependencies` (child `Dependant`s). Recurse and collect every `.call`,
then check membership.

Three things about the walk:

- **It must be transitive, not direct.** `require_league_member` itself depends
  on `get_current_user`, so a `LEAGUE_SCOPED` route satisfies `AUTHENTICATED`
  through it. Requiring the dependency directly on the endpoint would reject
  correct routes.
- **Duplicates are expected.** After H-04a, `get_standings_service` depends on
  `require_league_member`, and the standings route also declares it directly —
  so it appears twice in the tree. Collect into a set.
- **Keep a `seen` set on `id()`.** The graph is a DAG in practice; a defensive
  guard costs one line and turns a hypothetical infinite recursion into a
  non-event.

### Where the map lives: the test, not `policy.py`

Put the policy→dependency map in the test module.

`policy.py` currently imports nothing from the application — it is a pure
declaration module, which is why routers can import it freely. Moving the map
there would make it import `deps.py`, dragging the DB session, repositories and
services into every module that just wants to name a policy. There is no import
cycle today (`deps.py` does not import `policy.py`), so this is a weight and
layering argument rather than a correctness one — but it is the right side to
err on.

**Do not make `declare_policy` inject the dependency at runtime.** It is
tempting and it is stronger in principle, but it means the decorator has to
reach into `deps.py`, it fights FastAPI's dependency resolution order, and
charter D26 names *a test* as the mechanism. The CI gate is what the charter
asked for. If runtime injection is ever wanted, it is a separate decision with
its own bite — not a quiet addition here.

## Files

- `tests/api/test_route_policy_matrix.py` — the map, the graph walk, the new
  assertions, the negative tests. Keep the existing declaration checks; this
  adds to them.
- `backend/api/policy.py` — docstring only. It currently says the matrix test
  is "the structural half of charter D26"; that is now true rather than
  aspirational, and the docstring should say what the test actually enforces.

Nothing else. **No route changes** — if a route needs editing to pass, that is
a real finding: say so in the PR rather than quietly fixing it, because it
means a live gap existed.

## Tests

**Positive:** `create_app()` passes both new assertions (it should today —
all three routes are correct; if not, see above).

**Negative — the tests that prove the gate bites.** The existing
`test_undeclared_route_is_detected` is the pattern to follow: build a throwaway
`FastAPI()` app, not the real one.

1. A route declaring `LEAGUE_SCOPED` with no `require_league_member` anywhere in
   its dependency graph is flagged.
2. A route declaring `AUTHENTICATED` with no `get_current_user` is flagged.
3. A route satisfying its policy **transitively** — the dependency reached only
   through an intermediate like `get_standings_service` — is **not** flagged.
   This is the false-positive guard, and it is the one that fails if the walk
   is written as a direct-dependency check.
4. A `RoutePolicy` member with no entry in the map is flagged. Drive this from
   the enum itself (iterate `RoutePolicy`) rather than hardcoding a list, so
   adding a policy member is what triggers it.

## Acceptance criteria

- [ ] A `LEAGUE_SCOPED` route without a membership dependency fails CI.
- [ ] A policy with no defined enforcement rule fails CI.
- [ ] Transitive satisfaction is accepted; direct-only checking is not.
- [ ] `pytest && ruff check backend tests && mypy` clean.
- [ ] No route or dependency behaviour changed; `openapi.json` untouched.

## Data model / API impact

None. Test and docstring only.

## Rollback

Test-only change; the squash commit reverts cleanly.

## What this does not catch — state it in the PR

A route **mislabeled** `PUBLIC` that should have been protected still passes,
because the harness cannot know what a route ought to be. This bite guarantees
that a declared policy is honoured, not that the declaration is correct. That
gap is a review concern and belongs in the PR description so nobody reads the
green CI as broader than it is.

## Out of scope

Runtime dependency injection (see above), `H-05` (database constraints),
`S1-11c`, `H-09`, `H-10`.

## Notes for review

Claude will check: that the map is driven from the `RoutePolicy` enum rather
than a hand-listed set, that the walk is transitive (test 3 is the one that
catches a direct-only implementation), that the negative tests use throwaway
apps rather than mutating the real one, and that no production route changed —
a route edit in this diff means a live gap was found and needs saying out loud.
