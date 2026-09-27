from datetime import datetime, timezone

from src.fieldservice_cleanup import CleanupRequest, select_stale_photos


def test_only_closed_followed_up_orders_past_retention_are_deleted() -> None:
    request = CleanupRequest.model_validate(
        {
            "bucket": "field-photos",
            "retention_days": 30,
            "as_of": "2026-09-26T00:00:00Z",
            "work_orders": [
                {
                    "work_order_id": "wo-stale",
                    "closed_at": "2026-08-01T00:00:00Z",
                    "dispatch_status": "completed",
                    "technician_follow_up": "completed",
                    "photos": [{"object_key": "wo-stale/intake.jpg"}],
                },
                {
                    "work_order_id": "wo-clinician-review",
                    "closed_at": "2026-08-01T00:00:00Z",
                    "dispatch_status": "completed",
                    "technician_follow_up": "pending",
                    "photos": [{"object_key": "wo-clinician-review/site.jpg"}],
                },
                {
                    "work_order_id": "wo-active",
                    "closed_at": None,
                    "dispatch_status": "dispatched",
                    "technician_follow_up": "pending",
                    "photos": [{"object_key": "wo-active/arrival.jpg"}],
                },
            ],
        }
    )

    result = select_stale_photos(request)

    assert result.deleted_photo_keys == ["wo-stale/intake.jpg"]
    assert result.retained_work_order_ids == ["wo-clinician-review", "wo-active"]
    assert request.as_of == datetime(2026, 9, 26, tzinfo=timezone.utc)
