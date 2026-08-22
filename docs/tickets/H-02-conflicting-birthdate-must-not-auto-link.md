# H-02 · Conflicting birthdate must not auto-link

**Status:** NEXT (assigned) · **Depends on:** nothing · **PR into:** `v2`
**Branch:** `fix/h-02-dob-conflict-queues`
**Backlog:** [`docs/v2/BACKLOG.md`](../v2/BACKLOG.md) §Slice 1 hardening
**Source:** [`research/REDTEAM_TRIAGE.md`](../v2/research/REDTEAM_TRIAGE.md) §2
**Process:** [`CONTRIBUTING.md`](../../CONTRIBUTING.md)

---

## The bug

`services/resolution.py:124-136`. The ladder tries `exact_name_dob` first:

```python
if birthdate is not None:
    dob_matches = [c for c in candidates
                   if c.normalized_name == needle and c.birthdate == birthdate]
    if dob_matches:
        return _auto_link(MatchMethod.EXACT_NAME_DOB, ...)   # 0.950

exact = [c for c in candidates if c.normalized_name == needle]
if len(exact) == 1:
    return _auto_link(MatchMethod.EXACT_NAME, ...)           # 0.850
```

When the birthdates *disagree*, `dob_matches` is empty and control **falls
through** to `exact_name`, which auto-links on the name alone.

Concretely: the provider sends `"Marcus Williams", b. 1999-01-01`. The pool
holds exactly one `"marcus williams"`, born `1995-12-03`. The ladder links them
at 0.850 — using the *presence* of a birthdate to strengthen a match and
ignoring it entirely when it refutes one.

Charter D18 is "prefer unknown over confidently wrong." This is the confidently
wrong case, and it is worse than a bad read: the link is **durable**. Once
written, `resolve_and_link` short-circuits on the active link for every
subsequent ingest and never reconsiders the evidence.

`tests/services/test_resolution.py` covers matching DOB and absent DOB. It never
covers contradictory DOB, which is why this shipped.

## The rule

**Only a two-sided disagreement is a conflict.** Both the provider record and
the candidate must have a birthdate, and they must differ.

This is the whole subtlety of the bite. A candidate with `birthdate=None` is
*missing* evidence, not *contradicting* evidence, and must stay eligible —
`PlayerCandidate.birthdate` is nullable and most candidates will have no
birthdate at all. Treating absent as conflicting would queue nearly every
resolution and break `test_exact_unique_name_auto_links`.

|  | provider has DOB | provider has none |
|---|---|---|
| **candidate has DOB, same** | `exact_name_dob`, 0.950 (unchanged) | eligible |
| **candidate has DOB, differs** | **conflict → queue** | eligible |
| **candidate has none** | eligible | eligible |

## The fix

In `resolve_identity`, partition the exact-name matches before the length
checks rather than adding a special case after them:

1. Compute `exact` as today.
2. Split into `exact_ok` (no two-sided disagreement) and `exact_conflict`.
3. `len(exact_ok) == 1` → auto-link `EXACT_NAME` (as today).
4. `len(exact_ok) > 1` → queue `"ambiguous"` (as today).
5. `exact_ok` empty **and** `exact_conflict` non-empty → queue
   `"dob_conflict"`, passing the conflicting candidates as `QueueCandidate`
   evidence so a reviewer can act without re-deriving.
6. Otherwise fall through to fuzzy (as today).

Step 5 is why this is a partition and not a filter: if the conflicting
candidate were merely dropped, control would reach the fuzzy branch, match the
same name at score 100, and queue it as `"fuzzy_name"` — the right outcome
recorded under a reason that hides *why*. A reviewer needs to see "the name
matches but the birthdate says no."

Add `dob_conflict` to the reason list in the `ResolutionDecision.reason`
comment (line 68). Leave `EXACT_NAME_DOB` and the `CONFIDENCE` table alone — a
positive birthdate match is still the strongest name-based signal, and no
confidence value changes in this bite.

## Files

- `backend/services/resolution.py` — the partition, the new queue reason, and
  the docstring for step 4 of the ladder (it currently says "but only if
  unique"; it now also means "and only if not refuted").
- `tests/services/test_resolution.py` — the cases below.

Nothing else. No migration, no schema change, no confidence retuning.

## Tests

The bug is a fall-through, so the tests must pin both what changes and what
must not.

**Must change:**
1. Exact unique name + contradictory birthdate → **queues** with reason
   `dob_conflict`, and does not auto-link.
2. That queue decision carries the conflicting candidate's `fcp_entity_id` as
   evidence.

**Must not change** — these are the regression guards, and each should fail if
the rule is implemented as "any birthdate difference":
3. Exact unique name + *matching* birthdate → still auto-links at 0.950 via
   `EXACT_NAME_DOB`.
4. Exact unique name + candidate has `birthdate=None`, provider has one → still
   auto-links at 0.850. **The most important test in this bite.**
5. Exact unique name + provider has no birthdate, candidate has one → still
   auto-links at 0.850.
6. Neither side has a birthdate → still auto-links at 0.850.
7. Two same-named candidates → still queues `ambiguous`, regardless of
   birthdates (the existing `len(exact) > 1` path is unaffected).

Cite the origin per `CONTRIBUTING.md`:
`# charter D18: prefer unknown over confidently wrong`

## Acceptance criteria

- [ ] A contradicting birthdate queues instead of auto-linking, with a reason
      that names the cause.
- [ ] Every case in the eligibility table above behaves as specified.
- [ ] `pytest && ruff check backend tests && mypy` clean.
- [ ] No migration, no confidence-value changes in the diff.

## Data model / API impact

None. Pure domain/service logic.

## Rollback

Single-file logic change plus tests; the squash commit reverts cleanly.

## Out of scope — and one thing to know about it

**This fix prevents new wrong links. It does not repair existing ones.**
`resolve_and_link` returns any active link unchanged without re-evaluating
evidence, and `IdentityLinkRepository` exposes only `add()` and `find_active()`
— there is no supersede or correction path, despite its docstring claiming "a
wrong link is superseded, never deleted." So any wrong link already written
stays wrong and stays authoritative.

That is real, and it is **H-10**, not this bite: correcting a link means
superseding it, recording the verifier, and re-resolving the canonical facts
that depended on it. Do not start it here. Say in the PR description that
existing links are untouched, so nobody reads this fix as more than it is.

Also out of scope: `H-09` (all-play still folds `Result.UNKNOWN` into ties) and
anything touching the fuzzy floor or the review-queue schema (`H-05`).

## Notes for review

Claude will check: that absent-vs-conflicting is genuinely distinguished (test 4
is the one that catches a wrong implementation), that the queue reason is
`dob_conflict` rather than a fuzzy fall-through, that evidence carries entity
ids, and that no confidence constant moved.
