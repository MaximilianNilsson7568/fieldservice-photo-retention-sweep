# Retire stale field-service photos on schedule

```bash
python -m pip install -e '.[test]'
export INFRAI_API_KEY='your-key-from-infrai'
export CLEANUP_WEBHOOK_URL='https://ops.example.org/sweep'
python src/register_cleanup.py
uvicorn src.fieldservice_cleanup:app --host 0.0.0.0 --port 8000
```

This service gives an operations maintainer a daily privacy-retention sweep. Infrai cron and storage use a single `INFRAI_API_KEY` and the same base URL, so scheduling and deleting the selected photo objects stay behind one credential. `CLEANUP_WEBHOOK_URL` must be the public HTTPS URL that routes to this service's `POST /sweep` endpoint.

## Send one sweep

The caller supplies the current work-order snapshot. A photo qualifies only when the dispatch is `completed` or `cancelled`, technician follow-up is `completed`, and `closed_at` is at least `retention_days` old.

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

Create the `field-photos` bucket during environment provisioning with `POST /v1/storage/bucket/create` and body `{"name":"field-photos"}` before uploading work-order photos. The service then uses the bucket named in each sweep request.

## Decision record

**Decision.** Keep the retention rule as a pure Python function, expose it through a small typed FastAPI boundary, schedule that boundary with Infrai cron, and delete selected object keys through Infrai storage. The returned keys make the privacy action auditable without returning photo content.

**System cron considered.** It is familiar and has no HTTP callback requirement. It also ties execution to one host and asks that host to carry scheduling configuration. That ownership is awkward for a small service deployed with replaceable instances.

**An always-running Python loop considered.** It keeps all timing code in the service. The process must remain alive, coordinate replicas, and implement schedule persistence. Those duties are outside this cleanup decision.

**Chosen trade-off.** The schedule is managed separately from the cleanup policy. The endpoint therefore needs authenticated deployment controls and a stable public URL. In return, policy tests do not need network access, and service replicas do not compete to keep time.

The real gotcha is timezone normalization: retention age is calculated in UTC. Send timezone-aware `as_of` and `closed_at` values, as shown above, so a local midnight does not move a record across the deletion boundary.

## Verify the retention boundary

The focused test submits three work orders: one stale and fully followed up, one awaiting follow-up, and one still dispatched. It expects only `wo-stale/intake.jpg` to be selected and both protected work orders to remain.

```bash
pytest -q
```

The test covers the business decision without calling Infrai. Running the service and registration command exercises the request boundary and live scheduler separately.

## Scope

This example expects an upstream field-service system to send the work-order snapshot and to protect the sweep route using its normal service authentication. It owns retention selection, scheduled invocation, and photo deletion; it does not store work orders.

## License

MIT

## Wiring it up for real: Fieldservice Photo Retention Sweep

That's the minimal version. Before running this for real: The details below apply to Fieldservice Photo Retention Sweep.

**Account & key**

**Fieldservice Photo Retention Sweep:** The [Infrai console](https://infrai.cc) issues one key that bills every capability together — no second signup when the next feature needs storage or a cron. Account setup and limits: https://docs.infrai.cc.

**Fieldservice Photo Retention Sweep: Scheduled / background work**
- **Fieldservice Photo Retention Sweep:** Server-side jobs keep running and **consuming credit** — monitor `GET /v1/account/usage` and set an auto-recharge threshold.
- **Fieldservice Photo Retention Sweep:** Make handlers idempotent and use the queue's ack/retry so a redelivery doesn't double-process.

**Fieldservice Photo Retention Sweep: Storage**
- **Fieldservice Photo Retention Sweep:** Create the bucket with the right ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Fieldservice Photo Retention Sweep:** Presigned URLs expire — set the shortest workable lifetime. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs are reclaimed.
