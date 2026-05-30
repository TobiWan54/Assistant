"""Qwen-agent custom tools"""

import json
import re
from datetime import datetime
from typing import Optional

from qwen_agent.tools.base import BaseTool, register_tool

from .service import AlarmService


alarm_service: Optional[AlarmService] = None


def configure_alarm_tools(_service: AlarmService):
    global alarm_service
    alarm_service = _service


def service() -> AlarmService:
    if alarm_service is None:
        raise RuntimeError('Alarm tools not configured. Call configure_alarm_tools(_service) first.')
    return alarm_service


def parse_params(params: str) -> dict:
    if not params:
        return {}
    try:
        return json.loads(params)
    except json.JSONDecodeError:
        return json.loads(params.replace("'", '"'))



def parse_when(value: str, tz, now: datetime | None = None) -> datetime:
    """
    Parse either:
    - full ISO-like datetimes: 2026-05-31T22:00
    - time-only 24h strings: 22:00
    - time-only 12h strings: 10pm / 10:30 pm

    If only a clock time is provided, resolve it to the next future occurrence.
    """
    value = value.strip().lower()
    now = now or datetime.now(tz)

    # -----------------------------
    # 1) Full datetime (existing behaviour)
    # -----------------------------
    try:
        normalized = value.replace(" ", "T")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt.astimezone(tz)
    except ValueError:
        pass

    # -----------------------------
    # 2) 24h time-only, e.g. 22:00
    # -----------------------------
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))

        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"Invalid time: {value}")

        dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # If this time has already passed today, roll to tomorrow
        if dt <= now:
            dt += timedelta(days=1)

        return dt

    # -----------------------------
    # 3) 12h time-only, e.g. 10pm / 10:30 pm
    # -----------------------------
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", value)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or "00")
        ampm = m.group(3)

        if not (1 <= hour <= 12 and 0 <= minute <= 59):
            raise ValueError(f"Invalid time: {value}")

        if ampm == "am":
            if hour == 12:
                hour = 0
        elif ampm == "pm":
            if hour != 12:
                hour += 12

        dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # If already passed today, roll to tomorrow
        if dt <= now:
            dt += timedelta(days=1)

        return dt

    raise ValueError(f"Could not parse datetime/time value: {value}")



@register_tool("set_alarm")
class SetAlarmTool(BaseTool):
    description = """Set an alarm. Input must include `when` as a local ISO-like datetime string
    (for example: 2026-05-31T07:00) and may optionally include `label`."""

    parameters = [
        {
            "name": "when",
            "type": "string",
            "description": "Local alarm time in ISO-like format (for example: 2026-05-31T07:00)",
            "required": True
        },
        {
            "name": "label",
            "type": "string",
            "description": "Optional short human label",
            "required": False
        }
    ]

    def call(self, params: str, **kwargs) -> str:
        data = parse_params(params)
        svc = service()
        when = parse_when(data["when"], svc.store.tz, now=svc.now())
        label = data.get("label", "Alarm")
        alarm = svc.set_alarm(when, label)
        return json.dumps({
            "ok": True,
            "alarm": alarm.to_dict(),
            "message": f"Alarm set for {alarm.when.strftime('%Y-%m-%d %H:%M')}"
        })


@register_tool("list_alarms")
class ListAlarmsTool(BaseTool):
    description = "List all saved alarms."
    parameters = []

    def call(self, params: str, **kwargs) -> str:
        alarms = [a.to_dict() for a in service().list_alarms()]
        return json.dumps({
            "count": len(alarms),
            "alarms": alarms
        })


@register_tool("cancel_alarm_by_id")
class CancelAlarmTool(BaseTool):
    description = "Cancel a specific alarm by an exact alarm_id. Use this tool only when the alarm_id is known."
    parameters = [
        {
            "name": "alarm_id",
            "type": "string",
            "description": "The exact alarm_id to cancel.",
            "required": True
        }
    ]

    def call(self, params: str, **kwargs) -> str:
        data = parse_params(params)
        alarm_id = data["alarm_id"]
        ok = service().cancel_alarm_by_id(alarm_id)
        return json.dumps({
            "ok": ok,
            "alarm_id": alarm_id,
            "message": "Alarm canceled" if ok else "Alarm not found"
        })


@register_tool("update_alarm_by_id")
class UpdateAlarmTool(BaseTool):
    description = """Update an alarm by using an exact alarm_id. Use this tool only when the alarm_id is known.
    You can change the time (`when`), label (`label`) or active state (`active`)."""

    parameters = [
        {
            "name": "alarm_id",
            "type": "string",
            "description": "The exact alarm_id to update.",
            "required": True
        },
        {
            "name": "when",
            "type": "string",
            "description": "Optional new time in local ISO-like format (for example: 2026-05-31T07:00)",
            "required": False
        },
        {
            "name": "label",
            "type": "string",
            "description": "Optional new label for this alarm.",
            "required": False
        },
        {
            "name": "active",
            "type": "boolean",
            "description": "Optional active/inactive state.",
            "required": False
        }
    ]

    def call(self, params: str, **kwargs) -> str:
        data = parse_params(params)
        alarm_id = data.get("alarm_id")

        if not alarm_id:
            return json.dumps({
                "ok": False,
                "status": "missing_alarm_id",
                "message": "update_alarm_by_id requires an exact existing alarm_id"
            })

        when_str = data.get("when")
        when = None
        if when_str:
            when = parse_when(str(when_str), service().store.tz)

        label = data.get("label")
        active = data.get("active")

        updated = service().update_alarm_by_id(alarm_id=str(alarm_id), when=when, label=label, active=active)

        if updated is None:
            return json.dumps({
                "ok": False,
                "status": "not_found",
                "message": f"No alarm found for id {alarm_id}."
            })

        return json.dumps({
            "ok": True,
            "alarm": updated.to_dict(),
            "message": f"Updated alarm {alarm_id} successfully."
        })


@register_tool("stop_alarm")
class StopAlarmTool(BaseTool):
    description = "Stop the currently ringing alarm."
    parameters = []

    def call(self, params: str, **kwargs) -> str:
        ok = service().stop_alarm()
        return json.dumps({
            "ok": ok,
            "message": "Stopped current alarm" if ok else "No alarm is ringing"
        })


@register_tool("snooze_alarm")
class SnoozeAlarmTool(BaseTool):
    description = """Snooze the currently ringing alarm, or a specific alarm by alarm_id
    (only if an alarm_id is already known). If minutes is omitted, use 10 minutes as the default."""

    parameters = [
        {
            "name": "minutes",
            "type": "integer",
            "description": "Snooze duration in minutes.",
            "required": False
        },
        {
            "name": "alarm_id",
            "type": "string",
            "description": "Optional alarm id to snooze.",
            "required": False
        }
    ]

    def call(self, params: str, **kwargs) -> str:
        data = parse_params(params)
        minutes = int(data.get("minutes", 10))
        alarm_id = data.get("alarm_id")
        alarm = service().snooze_alarm(minutes=minutes, alarm_id=alarm_id)
        if alarm is None:
            return json.dumps({
                "ok": False,
                "message": "No alarm found to snooze."
            })
        return json.dumps({
            "ok": True,
            "alarm": alarm.to_dict(),
            "message": f"Snoozed for {minutes} minutes until {alarm.when.strftime('%Y-%m-%d %H:%M')}"
        })

@register_tool("find_alarms")
class FindAlarmsTool(BaseTool):
    description = """Find an alarm using natural-language reference, such as
        'my 7am alarm', 'the gym alarm', 'the one for tomorrow morning', or 'the alarm in 5 minutes'.
        Returns either a matched alarm_id, ambiguity information, or no_match."""

    parameters = [
        {
            "name": "reference",
            "type": "string",
            "description": "Natural-language description of the alarm to search for.",
            "required": True
        }
    ]

    def call(self, params: str, **kwargs) -> str:
        data = parse_params(params)

        reference = data.get("reference")
        if not reference:
            # fallback if the model emitted raw text instead of JSON params
            reference = params.strip() if params and params.strip() else None

        if not reference:
            return json.dumps({
                "reference": "",
                "candidate_count": 0,
                "candidates": [],
                "status": "no_match",
                "ok": False,
                "message": "No natural-language reference, e.g. 7am gym alarm, was provided.",
            })

        result = service().find_alarms(reference)
        return json.dumps(result)