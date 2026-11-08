# Batch Cancellation

### API Endpoints
- `POST /api/v1/batches/{32lowerhex}/cancel` (with session and `X-CSRF-Token`)
- `POST /queue/tasks/{id}/cancel-batch` (with CSRF form)

### Behavior
- **Demo Environment**: Returns `403`.
- **Running Task**: The API returns `202` with `cancellation_requested: true` until the end of the current offer. The parent stays `running` so deployment cannot interrupt an active writer.
- **Queued Task**: The API returns `200` with terminal status `cancelled`. The form redirects to the task page (`303`).
- **Idempotency**: Repeated cancellation is idempotent.
- **Analysis/Export**: Current analysis/export completes within its budget. Cancellation during extraction does not start the model, and the remaining tasks do not start. Saved results are kept; no autoretry occurs.
- **Persistent Marker**: `tasks/id.cancel` is robust to old JSON writes. Recovery does not repeat tasks.
- **Deployment Telemetry**: Real flock is used. Metadata only includes phase and times; no batch ETA is provided.

### IMPORTANT: Operational Migration
The deployment image alone does not update the root-owned `/usr/local/sbin/cvtailor-deploy` or the runtime `ConfigMap`. Separate authorization is required. Comparison and merging of local processor rollback fixes in the installed deployer are necessary; **DO NOT overwrite it blindly**.
No deployment, restart, or production data migration is performed as part of this change. Older task JSON remains readable; new consumers must accept `cancelled` and `cancellation_requested`. Existing cancellation markers remain local to the account. After an unexpected restart, existing recovery marks interrupted work as failed without replaying offers, retaining saved results and the cancellation request.

The authenticated read-only `GET /deployment/status` and task polling report the actual admission lock. A stale `.deployment-status.json` never proves a deployment is active. Older deployers without metadata still report the lock, with timing unavailable. Metadata contains only `phase`, `started_at`, and `drain_deadline_at`, is atomically written with mode `0600`, and is removed on normal completion or drain failure. A drain timeout refuses deployment rather than interrupting active work.

`MAX_PENDING_TASKS=12` is a separate future change; this patch does not change queue capacity.
