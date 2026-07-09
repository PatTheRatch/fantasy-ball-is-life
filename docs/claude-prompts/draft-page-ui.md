## Task: Build the Draft Optimizer page (DraftPage.tsx)

Replace the placeholder `frontend/src/pages/DraftPage.tsx` with a fully functional auction draft optimizer UI for mobile-first fantasy basketball.

### What already exists
- `frontend/src/api.ts` has `postOptimizerOptimize(body, bbmFile?)` — already wired up
- `frontend/src/components/Card.tsx` — reusable card wrapper (`rounded-[12px] border-pg-border bg-pg-card p-4`)
- Design tokens in `frontend/src/index.css`: `--color-pg-bg: #0d1117`, `--color-pg-card: #161b22`, `--color-pg-border: #30363d`, `--color-pg-accent: #e03131` (red), DM Sans font
- Backend endpoint `POST /optimizer/optimize` accepts `OptimizeBody` with fields: `exclude_players`, `games_per_week` (3 default), `initial_budget` (200), `roster_size` (13), `minimum_value_players` (3), `favorite_team`, `favorite_team_representation` (1), `minimum_game_threshold` (55), `value_col` ("$"), `categories` (optional list), `percentile` (0.75), `stat_to_maximize` ("PTS"), `draft_picks` (list of `{name, bid}`). Returns a list of player dicts with columns: Name, Pos, Team, $, g, pts/g PW, reb/g PW, ast/g PW, stl/g PW, blk/g PW, 3pm/g PW.

### What to build

The DraftPage should have these sections:

1. **Drafted Players card** — Add player name + bid via input fields. List drafted players with remove button. Show spent/remaining budget and open roster spots. Budget turns red if overspent.

2. **Settings card** (collapsible with chevron toggle) — Budget, roster size, games/week, min games threshold inputs. "Maximize" dropdown (PTS, REB, AST, STL, BLK, 3PM, TO). Category toggle chips for all 9 categories. File upload button for optional BBM projections (.xls/.xlsx).

3. **Optimize button** — Full-width red button. Shows spinner while loading. Calls `postOptimizerOptimize` with the form state and optional BBM file.

4. **Results** — On mobile: player cards showing name, position, team, cost, and stat row (PTS/REB/AST/STL/BLK per week). On desktop (md+): sortable table with Player, Pos, Team, Cost, GP, PTS/w, REB/w, AST/w, STL/w, BLK/w, 3PM/w columns. Sort arrows on column headers.

5. **Error state** — Red-bordered card with error message.

### Requirements
- Use the existing Card component
- Use lucide-react icons (already in deps): Plus, Trash2, Upload, Zap, ChevronUp, ChevronDown, ArrowUp, ArrowDown
- Format numbers: integers = no decimals, floats = 2 decimal places, null = "—"
- Mobile first — card layout on small screens, table on large
- Use React state (no need for react-query since this is a manual trigger, not automatic loading)
- Import types from `../api`: `OptimizeBody`, `DraftPick`, `JsonRecord`, `formatApiError`, `postOptimizerOptimize`

### Command
```
cd /opt/fantasy-ball-is-life/frontend && claude -p '<paste the task above>' --max-turns 20 --permission-mode acceptEdits --allowedTools "Read,Edit,Write" --output-format text
```

### After Claude completes
Restart the Vite dev server (or it should hot-reload) and verify the Draft tab at `http://100.105.64.94:5173`.
