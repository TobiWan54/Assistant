import json
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from qwen_agent.tools.base import BaseTool, register_tool


tz: Optional[ZoneInfo] = None


def configure_time_tools(_tz: ZoneInfo):
    global tz
    tz = _tz


def get_tz() -> ZoneInfo:
    if tz is None:
        raise RuntimeError("time tools not configured. Call configure_time_tools(_tz) first.")
    return tz


@register_tool("get_time")
class GetTimeTool(BaseTool):
    description = "Get the current local date and time."
    parameters = []

    def call(self, params: str, **kwargs) -> str:
        _tz = get_tz()
        now = datetime.now(_tz)
        return json.dumps({
            "now_iso": now.isoformat(),
            "timezone": str(_tz),
            "human": now.strftime("%A %d %B %Y, %H:%M")
        })