# ProcessDefinition and ResultReview

Every newly created task stores an immutable `ProcessDefinition` snapshot in
`tasks.process_snapshot`. The initial office process is deliberately narrow:

- `autonomy_level` is `review_required`;
- analysis and drafting are permitted actions;
- payments and autonomous external actions are forbidden;
- the task owner is the result owner and an `owner` or `admin` may review it.

This makes the process contract available to future graph execution without
changing the FastAPI, PostgreSQL, Celery, or agent-provider foundations.
Existing tasks without a snapshot remain readable but are not reviewable.

## Result review API

`GET /api/v1/processes` returns the process available to the current user.

`GET /api/v1/tasks/{task_id}/result-review` returns the stored contract, a
SHA-256 hash of the completed task result, eligibility, and the immutable
review when it exists.

`POST /api/v1/tasks/{task_id}/result-review` accepts:

```json
{
  "decision": "accepted",
  "reason": "Evidence reviewed",
  "result_hash": "<64-character SHA-256>"
}
```

Only an owner/admin authorized by the task's stored contract can submit a
review. The task must be completed; the supplied hash must still match its
result. One review per task is enforced by a database unique constraint.
An identical retry returns the existing review; a changed decision, reason,
or hash is rejected. Reviewing only records an audit event (`result_reviewed`)
and never creates a payment draft, changes task state, or authorizes an action.

## Quality feedback loop

`GET /api/v1/processes/quality?days=30` returns aggregate review coverage for
the authenticated owner over a 1–90 day window. It includes completed results,
reviewed and pending counts, decision distribution, review rate, and average
review latency in seconds. It deliberately excludes task text, attachments,
financial details, and model output from the metrics payload.
