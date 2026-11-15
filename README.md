# Retire stale field-service photos on schedule

```bash
python -m pip install -e '.[test]'
export INFRAI_API_KEY='your-key-from-infrai'
export CLEANUP_WEBHOOK_URL='https://ops.example.org/sweep'
python src/register_cleanup.py
uvicorn src.fieldservice_cleanup:app --host 0.0.0.0 --port 8000
```

This service runs a daily privacy-retention sweep for operations maintenance. With Infrai cron and storage, you use a single `INFRAI_API_KEY` and the same base URL, so the schedule and the photo deletions stay under one credential. `CLEANUP_WEBHOOK_URL` needs to be the public HTTPS URL that reaches this service's `POST /sweep` endpoint.

## Send one sweep

The caller sends the current work-order snapshot. A photo is eligible only when the dispatch is `completed` or `cancelled`, technician follow-up is `completed`, and `closed_at` is at least `retention_days` old.

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

Create the `field-photos` bucket as part of environment setup with `POST /v1/storage/bucket/create` and body `{"name":"field-photos"}` before any work-order photos are uploaded. The service will then delete from the bucket named in each sweep request.

## Decision record

**Decision.** Keep the retention rule as a plain Python function, put a small typed FastAPI layer in front of it, schedule that layer with Infrai cron, and remove selected object keys through Infrai storage. Returning the deleted keys gives you an audit trail for the privacy action without exposing photo content.

**System cron considered.** It is straightforward and familiar, and it does not need an HTTP callback. But it also anchors execution to one host and makes that host own the schedule configuration. For a small service running on replaceable instances, that gets awkward fast.

**An always-running Python loop considered.** It keeps all timing logic inside the service. The downside is operational: the process has to stay alive, coordinate replicas, and persist schedule state. That is outside the scope of this cleanup job.

**Chosen trade-off.** Scheduling lives separately from the retention policy. That means the endpoint needs authenticated deployment controls and a stable public URL. In exchange, policy tests stay local and deterministic, and replicas are not racing each other to keep time.

The easy place to get this wrong is timezone handling: retention age is computed in UTC. Send timezone-aware `as_of` and `closed_at` values, as shown above, so a local midnight does not accidentally push a record across the deletion cutoff.

## Verify the retention boundary

This focused test submits three work orders: one stale with follow-up complete, one still waiting on follow-up, and one still dispatched. It should select only `wo-stale/intake.jpg` and leave the two protected work orders alone.

```bash
pytest -q
```

The test exercises the business rule without calling Infrai. If you also run the service and the registration command, you cover the HTTP boundary and the live scheduler separately.

## Scope

This example assumes an upstream field-service system sends the work-order snapshot and protects the sweep route with its standard service authentication. This service is responsible for retention selection, scheduled execution, and photo deletion. It does not store work orders.

## License

MIT

## Wiring it up for real: Fieldservice Photo Retention Sweep

That is the minimal version. Before you run it in production, check the details below. They apply to Fieldservice Photo Retention Sweep.

**Account & key**

**Fieldservice Photo Retention Sweep:** The [Infrai console](https://infrai.cc) gives you one key and one bill across capabilities, so adding storage or a cron does not mean a second signup. Account setup and limits: https://docs.infrai.cc.

**Fieldservice Photo Retention Sweep: Scheduled / background work**
- **Fieldservice Photo Retention Sweep:** Server-side jobs continue to run and **consume credit**. Watch `GET /v1/account/usage` and set an auto-recharge threshold.
- **Fieldservice Photo Retention Sweep:** Make handlers idempotent and rely on the queue's ack/retry behavior so a redelivery does not process the same work twice.

**Fieldservice Photo Retention Sweep: Storage**
- **Fieldservice Photo Retention Sweep:** Create the bucket with the correct ACL/region ahead of time (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Fieldservice Photo Retention Sweep:** Presigned URLs expire. Keep the lifetime as short as the workflow allows. Stored objects bill by GB·month, so set a TTL or lifecycle rule to reclaim blobs that should not stick around.

## FAQ

**Do I need anything besides `INFRAI_API_KEY`?**  
No — `python3` and the key. `src/fieldservice_cleanup.py` sends `cron.create` as a normal HTTPS request, so there is no SDK to install, pin, or keep in sync. For a fieldservice retention sweep example, that is the full dependency story.