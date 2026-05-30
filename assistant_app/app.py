"""Assembles the whole assistant."""

from qwen_agent.agents import Assistant

from .config import LLM_CFG, SPOTIFY_MCP_CFG, TZ, ALARMS_DB_PATH
from .prompts import SYSTEM_MESSAGE

from assistant_app.domains.alarms.store import AlarmStore
from assistant_app.domains.alarms.service import AlarmService
from assistant_app.domains.alarms.resolver import AlarmResolver
from assistant_app.domains.alarms.tools import configure_alarm_tools

from assistant_app.domains.system.time_tools import configure_time_tools


class AssistantRuntime:
    """Holds long-lived services that require cleanup or shared state."""

    def __init__(self):
        self.alarm_store = AlarmStore(ALARMS_DB_PATH, TZ)
        self.alarm_resolver = AlarmResolver(
            base_url=LLM_CFG["model_server"],
            api_key=LLM_CFG["api_key"],
            model=LLM_CFG["model"]
        )
        self.alarm_service = AlarmService(self.alarm_store, self.alarm_resolver)

    def close(self):
        self.alarm_store.close()


def build_agent() -> tuple[Assistant, AssistantRuntime]:
    runtime = AssistantRuntime()

    # Configure module-scoped tool dependencies
    configure_alarm_tools(runtime.alarm_service)
    configure_time_tools(TZ)

    local_tools = [
        "get_time",
        "set_alarm",
        "list_alarms",
        "cancel_alarm_by_id",
        "update_alarm_by_id",
        "stop_alarm",
        "snooze_alarm",
        "find_alarms"
    ]

    function_list = local_tools + [SPOTIFY_MCP_CFG]

    bot = Assistant(
        llm=LLM_CFG,
        system_message=SYSTEM_MESSAGE,
        function_list=function_list,
        name="Bedside Assistant",
        description="A Qwen-Agent assistant with local alarm tools and MCP integration."
    )

    return bot, runtime