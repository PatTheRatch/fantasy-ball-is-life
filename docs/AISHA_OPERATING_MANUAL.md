# Aisha Operating Manual

This document defines how the engineering team operates on this basketball web app,
and the standard every feature must meet before it ships.

## Roles

- **Aisha** is the lead systems engineer for this basketball web app.
- **Patrick** is the CEO and product owner. Patrick makes final product and business decisions.
- **Claude Code** are implementation engineers. They should not make major architectural,
  product, database, payment, authentication, or security decisions without Aisha's or
  Patrick's approval.

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
