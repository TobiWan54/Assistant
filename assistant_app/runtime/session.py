from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from json import JSONDecodeError
from typing import Any

from .events import AgentEvent, EventSink


class ThinkFilter:
    """
    Streaming-safe filter for removing <think>...</think> blocks.
    """

    def __init__(self):
        self.in_think = False

    def filter(self, text: str) -> str:
        output = ""

        while text:
            if self.in_think:
                end = text.find("</think>")
                if end == -1:
                    return output
                text = text[end + len("</think>"):]
                self.in_think = False
            else:
                start = text.find("<think>")
                if start == -1:
                    output += text
                    return output
                output += text[:start]
                text = text[start + len("<think>"):]
                self.in_think = True

        return output


@dataclass
class SessionConfig:
    """
    Behaviour config for the conversation session.
    """
    retry_on_reasoning_only: bool = True
    max_retries: int = 1
    emit_tool_events: bool = True
    emit_debug_events: bool = False


@dataclass
class SessionTurnResult:
    """
    Full result of a single user turn.
    """
    full_response: list[dict[str, Any]] = field(default_factory=list)
    visible_text: str = ""
    had_tool_call: bool = False
    had_error: bool = False
    retries_used: int = 0


def build_retry_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Build retry messages WITHOUT adding a second system message.
    """
    retry_messages = copy.deepcopy(messages)

    retry_hint = (
        "\n\n[Retry instruction: "
        "Please answer this request now. "
        "If a tool is needed, call it. "
        "Otherwise provide a direct final answer. "
        "Do not return only a <think> block.]"
    )

    for i in range(len(retry_messages) - 1, -1, -1):
        if retry_messages[i].get("role") == "user":
            existing = retry_messages[i].get("content", "")
            retry_messages[i]["content"] = existing + retry_hint
            break

    return retry_messages


def normalise_tool_call(function_call: dict[str, Any]) -> dict[str, Any] | None:
    """
    Turn a function_call dict into a stable printable structure.

    Returns None if the arguments are still incomplete / invalid JSON,
    unless the tool appears to take no args.
    """
    if not function_call:
        return None

    name = function_call.get("name")
    arguments = function_call.get("arguments", "")

    if not name:
        return None

    # Some tools take no args, so "" or "{}" are both acceptable final forms.
    if arguments in ("", "{}"):
        return {"name": name, "arguments": "{}"}

    # Only emit once args are valid JSON
    try:
        parsed = json.loads(arguments)
    except JSONDecodeError:
        return None

    # Re-serialise to a stable canonical form for de-duplication
    stable_args = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
    return {"name": name, "arguments": stable_args}


class AssistantSession:
    """
    Common orchestration layer for Qwen-Agent conversations.
    """

    def __init__(
        self,
        bot: Any,
        sinks: list[EventSink] | None = None,
        config: SessionConfig | None = None,
    ):
        self.bot = bot
        self.sinks = sinks or []
        self.config = config or SessionConfig()
        self.messages: list[dict[str, Any]] = []

    # -----------------------------------------
    # Public API
    # -----------------------------------------

    def ask(self, user_text: str) -> SessionTurnResult:
        self.messages.append({"role": "user", "content": user_text})
        self.emit("user_text", text=user_text)

        retries_used = 0
        result = self.run_once(self.messages)

        while (
            self.config.retry_on_reasoning_only
            and retries_used < self.config.max_retries
            and not result.visible_text.strip()
            and not result.had_tool_call
            and not result.had_error
        ):
            retries_used += 1
            self.emit(
                "retry",
                reason="reasoning_only_or_empty_turn",
                retry_number=retries_used,
            )

            retry_messages = build_retry_messages(self.messages)
            result = self.run_once(retry_messages)

        result.retries_used = retries_used

        # Append only FINALIZED messages, not streaming fragments
        if result.full_response:
            self.messages.extend(result.full_response)

        return result

    # -----------------------------------------
    # Internal helpers for tool-call handling
    # -----------------------------------------

    def emit_tool_call_if_new(
        self,
        function_call: dict[str, Any],
        emitted_signatures: set[str],
    ) -> bool:
        """
        Emit a tool_call event only if:
        - the tool call is complete/stable
        - we have not already emitted the exact same call this turn
        """
        normalised = normalise_tool_call(function_call)
        if normalised is None:
            return False

        sig = json.dumps(normalised, sort_keys=True, ensure_ascii=False)
        if sig in emitted_signatures:
            return False

        emitted_signatures.add(sig)

        if self.config.emit_tool_events:
            self.emit("tool_call", function_call=normalised, raw=function_call)

        return True

    # -----------------------------------------
    # Internal turn runner
    # -----------------------------------------

    def run_once(self, messages: list[dict[str, Any]]) -> SessionTurnResult:
        think_filter = ThinkFilter()

        had_tool_call = False
        had_error = False

        # Track tool calls we have already emitted this turn
        emitted_tool_call_signatures: set[str] = set()

        # For display
        final_visible_text = ""

        # For history
        tool_messages: list[dict[str, Any]] = []
        final_assistant_message: dict[str, Any] | None = None

        for chunk in self.bot.run(messages=messages):
            if self.config.emit_debug_events:
                self.emit("debug_chunk", chunk=chunk)

            if not isinstance(chunk, list):
                chunk = [chunk]

            for msg in chunk:
                if not isinstance(msg, dict):
                    continue

                role = msg.get("role")
                content = msg.get("content", "")

                # -----------------------------
                # Assistant messages
                # -----------------------------
                if role == "assistant":
                    # Handle assistant text
                    if isinstance(content, str) and content:
                        clean = think_filter.filter(content)
                        if clean:
                            final_visible_text = clean
                            self.emit("assistant_text", text=clean, raw=content)

                    # Handle tool calls
                    tool_calls = msg.get("tool_calls")
                    function_call = msg.get("function_call")

                    # If *any* tool-call structure appears, treat the turn as tool-using
                    # immediately, even if the streamed arguments are still incomplete.
                    if tool_calls or function_call:
                        had_tool_call = True

                    # Some backends stream OpenAI-style tool_calls as a list
                    if tool_calls and isinstance(tool_calls, list):
                        for tc in tool_calls:
                            if not isinstance(tc, dict):
                                continue

                            # OpenAI-style nested function call
                            fc = tc.get("function")
                            if isinstance(fc, dict):
                                self.emit_tool_call_if_new(
                                    {
                                        "name": fc.get("name"),
                                        "arguments": fc.get("arguments", ""),
                                    },
                                    emitted_tool_call_signatures,
                                )

                    # Some backends / wrappers use function_call directly
                    if function_call and isinstance(function_call, dict):
                        self.emit_tool_call_if_new(
                            function_call,
                            emitted_tool_call_signatures,
                        )

                    # Save final assistant message candidate
                    if final_visible_text.strip():
                        final_assistant_message = {
                            "role": "assistant",
                            "content": final_visible_text,
                        }

                # -----------------------------
                # Tool messages
                # -----------------------------
                elif role == "tool":
                    # Keep tool messages once for history
                    tool_messages.append(msg)

                    if self.config.emit_tool_events:
                        self.emit(
                            "tool_result",
                            tool_name=msg.get("name") or msg.get("tool_name"),
                            content=content,
                            raw=msg,
                        )

                    if isinstance(content, str) and "An error occurred when calling tool" in content:
                        had_error = True
                        self.emit("tool_error", content=content, raw=msg)

                # -----------------------------
                # Fallback handling
                # -----------------------------
                else:
                    if isinstance(content, str):
                        if "An error occurred when calling tool" in content:
                            had_error = True
                            self.emit("tool_error", content=content, raw=msg)

        # Build compact finalised history messages
        finalized_messages: list[dict[str, Any]] = []
        finalized_messages.extend(tool_messages)

        if final_assistant_message is not None and final_visible_text.strip():
            finalized_messages.append(final_assistant_message)

        self.emit("assistant_text_complete", text=final_visible_text)

        if tool_messages:
            had_tool_call = True

        return SessionTurnResult(
            full_response=finalized_messages,
            visible_text=final_visible_text.strip(),
            had_tool_call=had_tool_call,
            had_error=had_error,
        )

    # -----------------------------------------
    # Event emission
    # -----------------------------------------

    def emit(self, event_type: str, **payload: Any) -> None:
        event = AgentEvent(type=event_type, payload=payload)
        for sink in self.sinks:
            sink.on_event(event)