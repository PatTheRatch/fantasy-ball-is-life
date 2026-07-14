# Aisha Operating Manual

This document defines how the engineering team operates on this basketball web app,
and the standard every feature must meet before it ships.

## Roles

- **Aisha** is the lead implementer. She reads the spec, writes the code, pushes
  branches, and applies review feedback. She owns correctness and delivery.
- **Claude Code** is the code reviewer and scoper. Before each PR, Claude scopes
  the work (what files, what approach, what decisions) — just enough detail for
  Aisha to implement. After each PR, Claude reviews the diff for bugs, edge
  cases, and spec compliance. Claude uses opus for review quality.
- **Patrick** is the CEO and product owner. He makes final product and business
  decisions, owns the specs, and is notified when a feature series completes.
  He does not participate in per-PR review cycles.

## Definition of a feature

Every feature must have:

1. **User story** — who it's for and what they're trying to do.
2. **Acceptance criteria** — the observable conditions that mean it's done.
3. **Data model impact** — new/changed tables, fields, migrations.
4. **API / UI impact** — endpoints added or changed, and the screens they touch.
5. **Test plan** — how correctness is verified.
6. **Rollback or failure considerations** — what happens when it breaks, and how to undo it.

## Default principle

Build the smallest paid-worthy version first. Avoid "cool" features unless they support
subscription value.
