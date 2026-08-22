# Full Court Press — frontend

React 19 + Vite + TypeScript + Tailwind + TanStack Query + React Router.

## The generated client is the contract

The API client is **generated**, never hand-written. The backend's OpenAPI
schema is exported to a committed snapshot and the client types are generated
from it:

```
scripts/export-openapi.py        # backend: app.openapi() -> frontend/openapi.json
npm run generate:client          # openapi-typescript openapi.json -> src/shared/api/openapi.d.ts
```

Both `openapi.json` and `openapi.d.ts` are committed, and CI regenerates them
and `git diff --exit-code`s — a backend contract change without a regenerated
snapshot fails CI. Do not edit `openapi.d.ts` by hand.

## Auth (dev-only shim for now)

There is no Supabase login flow yet. The app attaches a bearer token read from
`VITE_DEV_TOKEN` (or `localStorage["fcp.devToken"]`). The backend still verifies
the token end-to-end — this shim never bypasses auth, it only supplies the token.

```
# .env.local
VITE_DEV_TOKEN=<a real Supabase-issued JWT>
```

## Same-origin assumption (load-bearing — do not add CORS)

The SPA and the API are served **same-origin**, so there is no CORS surface:

- **dev:** `vite dev` proxies `/api` → `http://localhost:8000` (override with
  `VITE_API_PROXY_TARGET`).
- **prod:** Caddy serves `dist/` and reverse-proxies `/api` to the API container.

If you run the SPA on a different origin than the API without the proxy, every
request fails CORS. The fix is a proxy, **not** `CORSMiddleware` — keep only
public config in the bundle and no permissive CORS policy.

## Scripts

| Command | What |
|---|---|
| `npm run dev` | dev server (proxies `/api`) |
| `npm run build` | type-safe production bundle → `dist/` |
| `npm run typecheck` | `tsc --noEmit` |
| `npm test` | vitest (jsdom + testing-library) |
| `npm run lint` | eslint |
| `npm run generate:client` | regenerate the typed client from `openapi.json` |

## Structure

```
src/
  app/            router, providers, layout shell
  features/me/    one vertical slice (query + page) — the pattern to copy
  shared/
    api/          generated openapi.d.ts + the typed openapi-fetch client
    lib/          pure helpers (auth shim)
    ui/           the design system (Card, Button, Spinner, StateMessage)
  test/           vitest setup
```

The empty/stale-state vocabulary lives in `shared/ui/StateMessage`: `loading`,
`error`, `empty` (`data: []`), `not-synced` (`as_of: null`). `stale: true` is
rendered as a banner over real numbers, not as an empty state.
