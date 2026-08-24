# H-11 · Wire Supabase auth end-to-end

**Status:** NEXT (assigned) · **Depends on:** D-04 (`abb78e8`) · **PR into:** `v2`
**Branch:** `fix/h-11-auth-wiring`
**Backlog:** [`docs/v2/BACKLOG.md`](../v2/BACKLOG.md) §Slice 1 hardening
**Source:** [`RUNBOOK.md`](../v2/RUNBOOK.md) §6 findings
**Process:** [`CONTRIBUTING.md`](../../CONTRIBUTING.md)

---

## Why this is ahead of the schema hardening

**Nothing authenticated runs.** `create_app(keyset=…, session_factory=…)` takes
both as *test* injectables, and nothing anywhere loads the JWKS from
`SUPABASE_JWKS_URL` or builds a session from `DATABASE_URL`. So the command the
runbook documents produces an app with `jwks_keyset=None` and
`session_factory=None`, and `GET /api/v1/me` with a valid bearer token returns
**500** — verified by D-04, not inferred.

The application has only ever run under test wiring. Hardening the schema of a
system that cannot serve a logged-in request is the wrong order, so H-05b waits.

**Two independent defects, both required for a single successful request.**

## Defect 1 — there is no production entry point

`create_app()` builds an app that cannot authenticate and cannot reach a
database, and does so *silently*, because both parameters default to `None`.

**Preserve the runbook's command.** D-04 documented
`uvicorn backend.api.app:create_app --factory --reload`, and it walked that
path. Do not move to a module-level `app` or a differently-named factory and
leave the runbook lying — if you have a strong reason to change the invocation,
update `RUNBOOK.md` in the same PR.

Make the defaults honest instead:

```python
def create_app(
    *,
    keyset: JwksKeyset | None = None,
    session_factory: sessionmaker[Session] | None = None,
    load_from_env: bool = True,
) -> FastAPI:
```

- Bare `create_app()` → loads the JWKS and builds the session factory from the
  environment. This is the production path and the runbook's command.
- Explicit values take precedence; `load_from_env` governs only what was not
  supplied.
- `create_app(load_from_env=False)` → the current no-config behaviour, for the
  route-policy matrix test, which enumerates routes and must keep working with
  **no database and no network**.

The point of the flag is that "no config" becomes a deliberate choice rather
than a silent default. That silence is the whole defect.

**Fail fast.** If a required variable is missing or the JWKS cannot be fetched,
raise during construction. Do not start an app that answers `/health` happily
while 500ing every authenticated route — that is exactly the silent degradation
D28 forbids.

**The fetch needs an explicit timeout** and a typed failure, per S1-02's
transport lesson. An unbounded request at startup is a hang, not an error.

## Defect 2 — the verifier rejects the tokens Supabase actually issues

`platform/auth.py` hardcodes `RSAAlgorithm.from_jwk(jwk)` and
`algorithms=["RS256"]`. **Supabase signs ES256 on P-256** (D-04 confirmed
against the real project). So even with the JWKS loaded, a real token 401s.

Support EC keys alongside RSA, dispatching on the JWK's `kty`.

### The security rule this bite must not get wrong

**Derive the permitted algorithm from the JWK in the trusted keyset — never
from the token header.**

Taking `alg` from the header is the classic algorithm-confusion vulnerability:
an attacker sets `alg: HS256` and signs with the public key as the HMAC secret,
and a verifier that trusts the header accepts it. The keyset is trusted input;
the token is not.

So:

- Look up the JWK by `kid` (already correct — keep it).
- Determine the algorithm from that JWK (`kty`, and `alg` if present, validated
  against an allowlist).
- Pass **exactly that one algorithm** to `jwt.decode(algorithms=[...])`, not
  the full set of supported ones.
- The allowlist is `{"RS256", "ES256"}`. **Never `HS256`, never `none`.**

`cast("RSAPublicKey", key)` becomes a union covering EC public keys. Keep the
typed errors — `UnknownKey`, `ExpiredToken`, `InvalidToken` — exactly as they
are; an unsupported `kty` is an `InvalidToken`, not a crash.

## Files

- `backend/api/app.py` — the `load_from_env` path and the loaders.
- `backend/platform/auth.py` — algorithm dispatch.
- `backend/platform/settings.py` — only if a helper is genuinely missing; the
  three `SUPABASE_*` accessors already exist.
- `tests/api/test_route_policy_matrix.py` — pass `load_from_env=False`.
- `docs/v2/RUNBOOK.md` — remove the §6 finding once it is no longer true, and
  fold whatever it said into the working instructions.

## Tests

- **ES256 end to end:** generate a P-256 keypair in the test, build a JWKS from
  the public key, sign a token, and verify it. This is the test that proves the
  actual bug is fixed.
- RS256 still verifies — the existing coverage must not regress.
- **Algorithm confusion is rejected:** a token whose header claims `HS256`,
  signed using the public key as an HMAC secret, must raise `InvalidToken`.
  Write this one deliberately; it is the reason the algorithm comes from the
  keyset.
- An unsupported `kty` raises `InvalidToken` rather than propagating a library
  error.
- `create_app(load_from_env=False)` builds with no environment, no database and
  no network — the matrix test's precondition.
- Bare `create_app()` with a **mocked** fetch wires both pieces; with a missing
  variable or a failing fetch it raises during construction rather than
  returning a broken app.
- **No test performs a real network call.** Mock the JWKS fetch.

## Acceptance criteria

- [ ] `uvicorn backend.api.app:create_app --factory` serves an app that
      authenticates a real Supabase token.
- [ ] `GET /api/v1/me` returns 200 with a valid token and 401 with a bad one —
      **never 500**.
- [ ] ES256 and RS256 both verify; HS256 and `none` are rejected.
- [ ] The algorithm is derived from the keyset, never the token header.
- [ ] Missing config or a failed JWKS fetch fails at construction.
- [ ] `pytest && ruff check backend tests scripts && mypy` clean; no migration;
      `openapi.json` untouched.

## Data model / API impact

None. No schema change, no new endpoint, no wire change.

## Rollback

Code-only. Reverting restores the state where nothing authenticated works, so
this is a demo-breaking rollback rather than a cosmetic one.

## Out of scope — including one thing worth naming

**JWKS rotation.** The keyset is loaded once at startup, so if Supabase rotates
signing keys, every token fails `UnknownKey` until the process restarts. That is
a real operational hazard and it is **not** in this bite: rotation is manual and
rare, and there is no deployment yet (local only), so the current exposure is
zero. Note the limitation in the module docstring and file it as a follow-up
(bounded refetch on `UnknownKey`, with a cooldown so a flood of bad tokens
cannot cause a fetch storm). Do not build it here.

Also out: `H-05b`/`c`, `H-06`, `H-08`, `H-09`, `H-10`, `S1-11d`, deployment.

**No auth weakening**, restating D-04's rule because this is the bite where the
temptation is real: no mock verifier, no bypass flag, no skip-JWKS-in-dev
branch, no HS256 fallback. If a real token cannot be made to work, stop and
report.

## Notes for review

Claude will check: that the algorithm-confusion test exists and genuinely uses
the public key as an HMAC secret, that `algorithms=` receives one algorithm
derived from the JWK rather than a permissive list, that `load_from_env=False`
keeps the matrix test network-free, that construction fails loudly on bad
config, that no test reaches the network, and that the runbook no longer
documents a finding that has been fixed.
