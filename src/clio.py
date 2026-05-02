import json
import time

import anthropic
from dotenv import load_dotenv

import tools
from prompts import CHAT_SYSTEM_PROMPT, IMPROVE_SYSTEM_PROMPT

load_dotenv()


CHAT_MODEL = "claude-haiku-4-5"
IMPROVE_MODEL = "claude-sonnet-4-6"

PROMPT_COLOR = "\u001b[94m"
ASSISTANT_COLOR = "\u001b[93m"
RESET = "\u001b[0m"

BASH_TOOL = {
    "name": "bash",
    "description": "Execute a bash command and return stdout, stderr, and exit code.",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum execution time in seconds.",
                "default": 30,
            },
        },
        "required": ["command"],
    },
}
TOOLS = [BASH_TOOL]

VALIDATION_COMMAND = (
    "uv run python -m py_compile src/clio.py src/tools.py "
    "&& git diff -- src pyproject.toml README.md clio_capabilities.json"
)


class Clio:
    def __init__(self) -> None:
        self.client = anthropic.Anthropic()
        self.messages: list[dict] = []

    def run(self) -> None:
        while True:
            try:
                line = input(f"{PROMPT_COLOR}> {RESET}").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\n再见, goodbye, adiós")
                return

            if not line:
                continue

            if line in {"exit", "quit"}:
                print("If you want to dip, please ctrl+c")
                time.sleep(1)
                continue

            if line == "improve" or line.startswith("improve "):
                focus = line.removeprefix("improve").strip() or None
                self.improve(focus=focus)
                continue

            self.messages.append({"role": "user", "content": line})
            self._turn(self.messages, CHAT_SYSTEM_PROMPT, CHAT_MODEL)

    def improve(self, focus: str | None = None, max_iters: int = 3) -> None:
        focus_text = focus or "choose the most useful next capability yourself"
        messages: list[dict] = [
            {
                "role": "user",
                "content": (
                    "Enter autonomous self-improvement mode.\n"
                    f"Focus: {focus_text}\n"
                    f"Iteration budget: {max_iters}\n\n"
                    "First inspect the project with bash, including current files, "
                    "git status, and any existing clio_capabilities.json backlog. "
                    "Then begin iteration 1."
                ),
            }
        ]

        try:
            for iteration in range(1, max_iters + 1):
                print(
                    f"{ASSISTANT_COLOR}Improvement iteration "
                    f"{iteration}/{max_iters}{RESET}"
                )
                self._turn(
                    messages,
                    IMPROVE_SYSTEM_PROMPT,
                    IMPROVE_MODEL,
                    max_tokens=4096,
                )
                messages.append(_validation_followup())
        except KeyboardInterrupt:
            print("\n\nSelf-improvement stopped.")
            return

        print("Self-improvement budget exhausted.")

    def _turn(
        self,
        messages: list[dict],
        system: str,
        model: str,
        max_tokens: int = 1024,
    ) -> None:
        """Run one agent turn, looping until the model stops requesting tools."""
        while True:
            response = self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                tools=TOOLS,
            )
            messages.append({"role": "assistant", "content": response.content})

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                _print_assistant_text(response)
                return

            messages.append({"role": "user", "content": _run_tool_calls(tool_uses)})


def _run_tool_calls(tool_uses) -> list[dict]:
    results = []
    for tool in tool_uses:
        if tool.name == "bash":
            output = tools.call_tool(tool.input)
        else:
            output = {"error": f"Unknown tool: {tool.name}"}

        results.append(
            {
                "type": "tool_result",
                "tool_use_id": tool.id,
                "content": json.dumps(output),
            }
        )
    return results


def _print_assistant_text(response) -> None:
    text = "\n".join(b.text for b in response.content if b.type == "text")
    if text:
        print(f"{ASSISTANT_COLOR}{text}{RESET}")


def _validation_followup() -> dict:
    result = tools.call_tool({"command": VALIDATION_COMMAND, "timeout": 30})
    print(f"{ASSISTANT_COLOR}Validation exit code: {result['exit_code']}{RESET}")
    return {
        "role": "user",
        "content": (
            "Validation result for the last iteration:\n"
            f"{json.dumps(result, indent=2)}\n\n"
            "If the change is complete and validated, record the outcome in "
            "clio_capabilities.json using bash. Then continue with the next "
            "most useful capability unless the iteration budget is done."
        ),
    }


def main() -> None:
    Clio().run()


if __name__ == "__main__":
    main()
