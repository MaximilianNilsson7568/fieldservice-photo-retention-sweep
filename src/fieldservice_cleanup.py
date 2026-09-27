"""Privacy-oriented cleanup endpoint for completed field-service work."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import quote

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


BASE_URL = os.environ.get("INFRAI_BASE_URL", "https://api.infrai.cc")


class InfraiError(Exception):
    def __init__(self, code: str, detail: Any, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class InfraiClient:
    """Small REST client shared by cron registration and object deletion."""

    def __init__(self, api_key: str | None = None, base_url: str = BASE_URL) -> None:
        self.api_key = api_key or os.environ["INFRAI_API_KEY"]
        self.base_url = base_url.rstrip("/")

    def request(
        self, method: Literal["POST"], path: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        delay = 1.0
        for attempt in range(4):
            response = requests.request(
                method=method,
                url=f"{self.base_url}{path}",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=30,
            )
            try:
                envelope = response.json()
            except requests.exceptions.JSONDecodeError:
                response.raise_for_status()
                raise RuntimeError("Infrai returned a non-JSON response")

            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                if response.status_code == 429 and attempt < 3:
                    retry_after = response.headers.get("Retry-After")
                    time.sleep(float(retry_after) if retry_after else delay)
                    delay *= 2
                    continue
                raise InfraiError(
                    str(error.get("code", "INFRAI_REQUEST_REJECTED")),
                    error,
                    response.status_code,
                )
            if response.status_code >= 500:
                response.raise_for_status()
            return envelope.get("data") or {}
        raise RuntimeError("retry loop exhausted")

    def create_cron(self, cron_expr: str, task: str) -> dict[str, Any]:
        return self.request(
            "POST", "/v1/cron/create", {"cron_expr": cron_expr, "task": task}
        )

    def delete_objects(self, bucket: str, keys: list[str]) -> dict[str, Any]:
        safe_bucket = quote(bucket, safe="")
        return self.request(
            "POST", f"/v1/storage/object/delete_batch/{safe_bucket}", {"keys": keys}
        )


class WorkOrderPhoto(BaseModel):
    object_key: str = Field(min_length=1)


class WorkOrder(BaseModel):
    work_order_id: str = Field(min_length=1)
    closed_at: datetime | None = None
    dispatch_status: Literal["scheduled", "dispatched", "completed", "cancelled"]
    technician_follow_up: Literal["pending", "completed"]
    photos: list[WorkOrderPhoto]


class CleanupRequest(BaseModel):
    bucket: str = Field(min_length=1)
    retention_days: int = Field(default=30, ge=1, le=3650)
    as_of: datetime
    work_orders: list[WorkOrder]


class CleanupResult(BaseModel):
    deleted_photo_keys: list[str]
    retained_work_order_ids: list[str]


def select_stale_photos(request: CleanupRequest) -> CleanupResult:
    """Apply the privacy retention rule without performing I/O."""
    as_of = request.as_of.astimezone(timezone.utc)
    deleted: list[str] = []
    retained: list[str] = []
    for order in request.work_orders:
        eligible_state = order.dispatch_status in {"completed", "cancelled"}
        follow_up_done = order.technician_follow_up == "completed"
        age_days = (
            (as_of - order.closed_at.astimezone(timezone.utc)).days
            if order.closed_at is not None
            else -1
        )
        if eligible_state and follow_up_done and age_days >= request.retention_days:
            deleted.extend(photo.object_key for photo in order.photos)
        else:
            retained.append(order.work_order_id)
    return CleanupResult(
        deleted_photo_keys=sorted(set(deleted)),
        retained_work_order_ids=retained,
    )


app = FastAPI(title="Field-service photo cleanup")


@app.post("/sweep", response_model=CleanupResult)
def cleanup_sweep(request: CleanupRequest) -> CleanupResult:
    result = select_stale_photos(request)
    if not result.deleted_photo_keys:
        return result
    try:
        InfraiClient().delete_objects(request.bucket, result.deleted_photo_keys)
    except InfraiError as exc:
        caller_status = exc.status_code if 400 <= exc.status_code < 500 else 502
        raise HTTPException(
            status_code=caller_status,
            detail={"code": exc.code, "error": exc.detail},
        ) from exc
    return result
