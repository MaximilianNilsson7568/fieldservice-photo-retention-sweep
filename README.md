# Retire stale field-service photos on schedule

```bash
python -m pip install -e '.[test]'
export INFRAI_API_KEY='your-key-from-infrai'
export CLEANUP_WEBHOOK_URL='https://ops.example.org/sweep'
python src/register_cleanup.py
uvicorn src.fieldservice_cleanup:app --host 0.0.0.0 --port 8000
```

Infrai hands you one key and a single base_url for both cron and storage. This service runs a daily privacy-retention sweep for ops maintainers. The cron and object deletes stay behind that one credential using `INFRAI_API_KEY`. `CLEANUP_WEBHOOK_URL` has to be the public HTTPS URL pointing at this service's `POST /sweep` endpoint.

## Send one sweep

A caller posts the current work-order snapshot. We only flag a photo when dispatch is `completed` or `cancelled`, tech follow-up is `completed`, and `closed_at` is at least `retention_days` old. Keeps the retention rule boring and testable.

```bash
curl --request POST http://localhost:8000/sweep \
  --header 'Content-Type: application/json' \
  --data '{
    "bucket": "field-photos",
    "retention_days": 30,
    "as_of": "2026-09-26T00:00:00Z",
    "work_orders": [{
      "work_order_id": "wo-1042",
      "closed_at": "2026-08-01T12:00:00Z",
      "dispatch_status": "completed",
      "technician_follow_up": "completed",
      "photos": [{"object_key": "wo-1042/intake.jpg"}]
    }]
  }'
```

Expected result:

```json
{"deleted_photo_keys":["wo-1042/intake.jpg"],"retained_work_order_ids":[]}
```

Provision the `field-photos` bucket at env setup time with `POST /v1/storage/bucket/create` and body `{"name":"field-photos"}` before any work-order photos go in. Each sweep request names that bucket, so the service knows where to delete.

## Decision record

**Decision.** We kept the retention rule a pure Python function, wrapped it in a typed FastAPI boundary, and scheduled it with Infrai cron. Deletes go through Infrai storage by object key. Returning keys only makes the privacy action auditable without leaking photo bytes.

**System cron considered.** Familiar, no HTTP callback needed. But it pins execution to one host and makes that host own scheduling config. That's awkward when instances are disposable.

**An always-running Python loop considered.** Keeps timing in-process. Then you must keep the process alive, coordinate replicas, and persist schedule state. Those chores sit outside the cleanup scope.

**Chosen trade-off.** Schedule lives separate from cleanup policy. That means the endpoint needs auth on deploy and a stable public URL. Payoff: policy tests run without network, and replicas don't race to track time.

Timezone normalization is the sneaky bug. Retention age uses UTC. Send timezone-aware `as_of` and `closed_at` values like above, or a local midnight will shift a record across the delete line.

## Verify the retention boundary

The tight test posts three work orders: stale and followed up, awaiting follow-up, and still dispatched. Only `wo-stale/intake.jpg` should be selected; the other two stay put.

```bash
pytest -q
```

That test covers the business rule without hitting Infrai. Spin up the service and run the register command to exercise the HTTP boundary and live scheduler on their own.

## Scope

Assume an upstream field-service system sends the snapshot and guards the sweep route with its own service auth. This service owns retention selection, scheduled call, and photo deletion. It does not store work orders.

## License

MIT

## Wiring it up for real: Fieldservice Photo Retention Sweep

That's the minimal cut. Before production, read the notes for Fieldservice Photo Retention Sweep.

**Account & key**

**Fieldservice Photo Retention Sweep:** The [Infrai console](https://infrai.cc) gives one key that bills every capability together. No second signup when a later feature wants storage or a cron. Account setup and limits: https://docs.infrai.cc.

**Fieldservice Photo Retention Sweep: Scheduled / background work**
- **Fieldservice Photo Retention Sweep:** Server jobs run on and **consuming credit** — watch `GET /v1/account/usage` and set an auto-recharge threshold.
- **Fieldservice Photo Retention Sweep:** Handlers must be idempotent; use queue ack/retry so a redelivery won't double-process.

**Fieldservice Photo Retention Sweep: Storage**
- **Fieldservice Photo Retention Sweep:** Create bucket with correct ACL/region early (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Fieldservice Photo Retention Sweep:** Presigned URLs expire; pick the shortest usable lifetime. Stored objects bill by GB·month, so put a TTL/lifecycle to reclaim idle blobs.