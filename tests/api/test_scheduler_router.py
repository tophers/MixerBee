import pytest
from fastapi import HTTPException

import app_state
import models
from routers import scheduler as scheduler_router


def _daily_request(time_value="07:45"):
    return models.ScheduleRequest(
        job_type="builder",
        playlist_name="Daily Mix",
        user_id="u1",
        schedule_details=models.ScheduleDetails(frequency="daily", time=time_value),
        blocks=[{"type": "movie"}],
    )


def _weekly_request(days=None, time_value="19:00"):
    return models.ScheduleRequest(
        job_type="builder",
        playlist_name="Weekly Mix",
        user_id="u1",
        schedule_details=models.ScheduleDetails(
            frequency="weekly", time=time_value, days_of_week=days
        ),
        blocks=[{"type": "movie"}],
    )


def test_create_schedule_weekly_requires_days(monkeypatch):
    monkeypatch.setattr(app_state, "is_configured", True)

    with pytest.raises(HTTPException) as exc:
        scheduler_router.api_create_schedule(_weekly_request(days=None))

    assert exc.value.status_code == 400
    assert "days_of_week" in exc.value.detail


def test_create_schedule_daily_builds_crontab_and_calls_scheduler(monkeypatch):
    monkeypatch.setattr(app_state, "is_configured", True)
    captured = {}

    def fake_add_schedule(schedule_data):
        captured.update(schedule_data)
        return "sched-123"

    monkeypatch.setattr(
        scheduler_router.scheduler.scheduler_manager, "add_schedule", fake_add_schedule
    )

    res = scheduler_router.api_create_schedule(_daily_request("07:45"))

    assert res["status"] == "ok"
    assert res["id"] == "sched-123"
    assert captured["crontab"] == "45 07 * * *"


def test_update_schedule_invalid_time_returns_400(monkeypatch):
    monkeypatch.setattr(app_state, "is_configured", True)

    with pytest.raises(HTTPException) as exc:
        scheduler_router.api_update_schedule("s1", _daily_request("25:99"))

    assert exc.value.status_code == 400
    assert "Invalid schedule format" in exc.value.detail


def test_update_schedule_returns_404_when_manager_fails(monkeypatch):
    monkeypatch.setattr(app_state, "is_configured", True)
    monkeypatch.setattr(
        scheduler_router.scheduler.scheduler_manager,
        "update_schedule",
        lambda *_args, **_kwargs: False,
    )

    with pytest.raises(HTTPException) as exc:
        scheduler_router.api_update_schedule("s1", _daily_request("10:15"))

    assert exc.value.status_code == 404
    assert "not found" in exc.value.detail.lower()
