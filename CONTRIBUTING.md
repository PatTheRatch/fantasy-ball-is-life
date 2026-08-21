# Contributing — FCP V2

How work gets onto the `v2` branch. This document is the mechanics; the
product and architecture decisions it serves live in
[`docs/FCP_V2_Product_Architecture_Charter.md`](docs/FCP_V2_Product_Architecture_Charter.md).

Two agents and one human follow this literally. Where it is ambiguous, say so
rather than guessing — an ambiguity fixed once here is cheaper than two agents
diverging quietly.

---

## Roles

| | Who | Does |
|---|---|---|
| **Patrick** | Product owner | Owns the charter and the product. **Starts each bite.** Not in the per-bite review loop. |
| **Claude** | Delegator + reviewer | Decides what is next, scopes it, reviews the result, approves or sends it back. Maintains the backlog. Writes no feature code. |
| **Aisha** | Implementer | Builds the assigned bite, opens the PR, applies review feedback, merges on approval. |

**Claude does not implement and Aisha does not choose.** That separation is the
point: a reviewer who wrote the code is not a reviewer, and an implementer who
picks their own scope drifts from the plan.

---

## The loop

One bite at a time. Always.

```
   Patrick: "start the next one"
        │
        ▼
   1. Aisha  →  Claude:  "what's next on the list?"
        │
        ▼
   2. Claude →  Aisha:   ONE bite, scoped:
                         what to build, which files, key decisions,
                         which charter clauses apply, done-when
        │
        ▼
   3. Aisha:  branch, build, push, open PR into v2
        │
        ▼
   4. Aisha  →  Claude:  "ready for review: <PR link>"
        │
        ▼
   5. Claude: review the PUSHED diff + CI result
        │
        ├── changes needed ──► Aisha fixes, pushes, back to 4
        │
        └── approved
             │
             ▼
   6. Aisha:  squash-merge into v2, delete the branch
        │
        ▼
   7. Claude: tick the bite in docs/v2/BACKLOG.md
        │
        ▼
   STOP. Wait for Patrick.
```

**Step 7 is not optional and step 8 does not exist.** After a merge the loop
halts until Patrick starts the next bite. Aisha does not roll straight into the
following item, and Claude does not assign one unprompted.

---

## The list

[`docs/v2/BACKLOG.md`](docs/v2/BACKLOG.md) is the single source of what is next.

- **Claude maintains it.** Status changes are part of approval, not a separate
  chore.
- **Aisha never edits it.** If a bite turns out to be two bites, Aisha says so
  and Claude re-cuts the list.
- One item is marked `NEXT`. That is the only thing anyone is working on.

Design documents (`docs/v2/schema/`, the ingestion design, the classification)
are **inputs** to the backlog, not the backlog. They describe the target; the
backlog describes the order.

---

## Branches

Every bite gets a branch off `v2` and lands by pull request. **No direct
commits to `v2`.**

```
feat/<bite-id>-<short-name>     new capability      feat/s1-02-espn-gateway
fix/<bite-id>-<short-name>      correcting a bug    fix/s1-04-scope-leak
chore/<bite-id>-<short-name>    tooling, deps       chore/s1-03-alembic
docs/<short-name>               docs only
```

**`main` is V1 and is still deployed.** Nothing from V2 goes there until
cutover. The only commits to `main` are V1 fixes and design documents.

**One carve-out:** syncing `main` → `v2` (`git merge origin/main`) is
maintenance, not a bite. It carries already-reviewed design documents across
and needs no PR. It is the only direct write to `v2`, and it must never carry
code — if a merge from `main` brings anything under `backend/` or `frontend/`,
stop, because something has gone wrong.

---

## Definition of done

A bite is not ready for review until all of these hold. Aisha checks them
before asking; Claude verifies rather than trusting.

- [ ] `pytest` green — the whole suite, not just the new tests
- [ ] `ruff check backend tests` clean
- [ ] `mypy` clean (strict; it is configured that way in `pyproject.toml`)
- [ ] Architecture tests pass — `tests/test_architecture.py`
- [ ] CI green on the pushed branch
- [ ] New behaviour has tests; ported behaviour cites its origin (below)
- [ ] No new dependency without saying why in the PR body
- [ ] Docs updated if the bite changed a documented contract

### Porting from V1

When a bite carries a behaviour forward from V1, the test that proves it names
its origin:

```python
# V1: test_category_result_turnovers_lower_wins
def test_turnovers_fewer_wins() -> None:
    ...
```

The register in [`docs/v2/V1_CLASSIFICATION.md`](docs/v2/V1_CLASSIFICATION.md)
§7 lists 44 such invariants. Each was paid for with a production bug. Porting
the code without the test loses the reason it is shaped that way.

V1 is readable without switching branches:

```bash
git show main:backend/league/scoreboard.py     # one file
git worktree add ../fcp-v1 main                # a full working copy
```

---

## What Claude checks in review

Beyond correctness and the gate above:

| Check | Against |
|---|---|
| Charter compliance | The specific decisions the bite touches, named in the scope |
| Non-negotiables | Charter §10 — all ten, every time |
| Schema conventions | [`docs/v2/schema/README.md`](docs/v2/schema/README.md) if the bite touches schema |
| Layering | Domain imports nothing; business logic is not in a router |
| Tenancy | Any data access is scope-bound; no route without a declared policy |
| Silent degradation | Failures produce a status and a reason, never an absence |
| Unknown vs zero | Missing values stay `None`, never default to `0` |
| Test honesty | Tests assert behaviour, not the implementation restated |
| Scope | The bite did what was assigned, and not more |

**Claude verifies claims rather than accepting them.** "Tests pass" is checked
against the CI run. A comment asserting something about V1 is checked against
V1. This is not distrust — it is that a wrong claim in a comment outlives the
person who wrote it.

---

## When to stop and ask

Aisha should halt mid-bite and go back to Claude when:

- The bite is larger than scoped, or is really two bites.
- The scope conflicts with a charter decision or a design doc.
- Implementing it needs a decision the documents do not answer.
- Something in a design document appears wrong once implemented against.
- A dependency, migration, or external service is needed that was not scoped.

Stopping to ask is never the wrong call. Guessing and building the wrong thing
costs a whole review cycle; a discovered design flaw is worth more than a
finished bite.

## Disagreement

If Aisha thinks a review comment is wrong, say so with the reasoning rather
than complying silently. Claude either shows the evidence or withdraws the
comment. Neither agent defers on the grounds of role.

Anything that turns out to be a **product** question — not a correctness
question — stops and goes to Patrick. Neither agent decides product.

---

## Commit messages

- Imperative subject, ~50 characters. `feat(domain): port all-play scoring`
- Body explains **why**, not just what. A reviewer can read the diff for what.
- Note deliberate deviations from V1 and the reason.
- Reference the bite id: `S1-02`.
- Agent commits carry their trailer:

```
Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

PR bodies state: the bite id, what changed, which charter decisions apply,
how it was verified, and anything deliberately left out.

---

## Environment

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

pytest                        # full suite
ruff check backend tests
mypy
```

Secrets live in `.env`, which is gitignored and **never** committed or pasted
into a document. `tests/conftest.py` scrubs deployment secrets from the
environment before every test, so a local run matches clean CI — do not defeat
that by setting them in a test.

---

## The rules that do not bend

1. No direct commits to `v2`. PR only.
2. No V2 code on `main`.
3. One bite at a time; stop after merge.
4. Aisha does not pick the next item; Claude does not write feature code.
5. No secret in any tracked file, ever.
6. A failing gate is not merged, and is not argued around.
