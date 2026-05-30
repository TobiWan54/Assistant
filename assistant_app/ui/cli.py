import sys

from assistant_app.app import build_agent
from assistant_app.runtime.events import AgentEvent, BaseEventSink
from assistant_app.runtime.session import AssistantSession, SessionConfig


class CLIEventSink(BaseEventSink):
    """
    CLI renderer.
    """

    def __init__(self, show_tools: bool = False, show_debug: bool = False):
        self.show_tools = show_tools
        self.show_debug = show_debug
        self._started_assistant_line = False
        self._assistant_printed_text = ""

    def _ensure_assistant_prefix(self) -> None:
        if not self._started_assistant_line:
            print("Assistant:", end=" ", flush=True)
            self._started_assistant_line = True

    def _reset_turn(self) -> None:
        self._started_assistant_line = False
        self._assistant_printed_text = ""

    def on_event(self, event: AgentEvent) -> None:
        if event.type == "user_text":
            self._reset_turn()
            return

        elif event.type == "assistant_text":
            # Just buffer the latest full text, don't print yet
            full_text = event.payload.get("text", "")
            if full_text.strip():
                self._assistant_printed_text = full_text

        elif event.type == "assistant_text_complete":
            text = self._assistant_printed_text.strip()
            if text:
                print(f"Assistant: {text}")
            self._reset_turn()

        elif event.type == "tool_call" and self.show_tools:
            if self._started_assistant_line:
                print()
                self._started_assistant_line = False
            print("[TOOL CALL]")
            content = event.payload.get("content")
            function_call = event.payload.get("function_call")
            tool_calls = event.payload.get("tool_calls")
            raw = event.payload.get("raw")
            if function_call:
                print(function_call)
            elif tool_calls:
                print(tool_calls)
            elif content:
                print(content)
            else:
                print(raw)
            sys.stdout.flush()

        elif event.type == "tool_result" and self.show_tools:
            if self._started_assistant_line:
                print()
                self._started_assistant_line = False
            print("[TOOL RESULT]")
            tool_name = event.payload.get("tool_name")
            content = event.payload.get("content")
            if tool_name:
                print(f"Tool: {tool_name}")
            print(content)
            sys.stdout.flush()

        elif event.type == "tool_error":
            if self._started_assistant_line:
                print()
                self._started_assistant_line = False
            print("[TOOL ERROR]")
            print(event.payload.get("content", ""))
            sys.stdout.flush()

        elif event.type == "retry":
            if self._started_assistant_line:
                print()
                self._started_assistant_line = False
            print(f"[Retrying turn: {event.payload.get('reason')}]")
            sys.stdout.flush()

        elif event.type == "debug_chunk" and self.show_debug:
            if self._started_assistant_line:
                print()
                self._started_assistant_line = False
            print("[DEBUG CHUNK]")
            print(event.payload.get("chunk"))
            sys.stdout.flush()


def run_cli():
    bot, runtime = build_agent()

    sink = CLIEventSink(
        show_tools=True,   # Control visibility of tool traces in the CLI
        show_debug=False   # Control visibility of raw chunk debugging information
    )

    session = AssistantSession(
        bot=bot,
        sinks=[sink],
        config=SessionConfig(
            retry_on_reasoning_only=True,
            max_retries=1,
            emit_tool_events=True,
            emit_debug_events=False,
        ),
    )

    print(
        """Bedside Assistant started!
          Try:
          - Wake me up tomorrow at 07:00
          - What alarms have I set?
          - Snooze for 5 minutes
          - Stop my alarm
          - Play my focus playlist on Spotify
         Quit with: exit
        """
    )

    try:
        while True:
            query = input("\nYou: ").strip()
            if query.lower() in {"exit", "quit"}:
                break

            result = session.ask(query)

            if not result.visible_text.strip() and not result.had_tool_call:
                print("Assistant: Sorry — I didn't produce a usable response.")
                if result.retries_used:
                    print(f"[Tried {result.retries_used} retry/retries]")

    finally:
        runtime.close()


if __name__ == "__main__":
    run_cli()
