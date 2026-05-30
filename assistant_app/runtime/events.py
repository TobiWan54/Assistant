# assistant_app/runtime/events.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class AgentEvent:
    """
    Generic event emitted by the conversation session.
    """
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


class EventSink(Protocol):
    """
    Protocol for anything that wants to consume conversation events.
    """

    def on_event(self, event: AgentEvent) -> None:
        ...


class BaseEventSink:
    """
    Default no-op base class.
    Override only the events you care about.
    """

    def on_event(self, event: AgentEvent) -> None:
        ...