# Task Template

Every issue in the tracker uses these four sections. A task that cannot fill them in is not ready
for an engineer.

```markdown
## Goal

One or two sentences on what should be true when this is done. Written as an outcome, not as a
list of steps.

## Acceptance criteria

- [ ] US1-AC1 — a statement you can check by looking at the result
- [ ] One line per case, including the awkward ones (empty, duplicate, concurrent, limit)
- [ ] Each criterion names the test tag that proves it: `unit`, `integration` or `e2e`

## Out of scope

- Something that does not belong in this task, moved to #TASK-NUMBER
- A tempting adjacent improvement, explicitly deferred

## Constraints

- Files or directories this change should stay inside
- Libraries to use, or not to use
- Prior decisions it must respect (link the document, do not restate it)
- How to prove it: `make test-integration -k reserve`, expected `3 passed`
```

## Why these four

- **Goal** stops the engineer from implementing the steps instead of the outcome.
- **Acceptance criteria** are the only thing QA judges. If QA has to interpret them, they are
  wrong — rewrite them until pointing at the running app answers yes or no.
- **Out of scope** is where scope creep is killed *before* it enters a diff. Anything dropped is
  linked to a follow-up issue, so nothing silently disappears.
- **Constraints** are what keep a 20-hour project coherent: file ownership (so parallel agents do
  not collide), library decisions, and the earlier decisions that are expensive to rediscover.

## Grooming standard

An issue is groomed when an engineer who has never spoken to the person who filed it can implement
it from the issue plus the documents it links, without asking a question.
