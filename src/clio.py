import json
import pathlib
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

# Branch where every validated self-improvement iteration is committed.
AGENT_BRANCH = "agent"

# Maximum number of messages to keep in the rolling chat history.
# Each full exchange is 2 messages (user + assistant); tool round-trips add
# more.  Keeping the 40 most recent messages gives ~20 full turns of context
# without risking a context-window overflow.
MAX_CHAT_MESSAGES = 40

# Maximum times _auto_commit will retry after a validation failure before
# giving up and moving on to the next iteration.
MAX_VALIDATION_RETRIES = 2


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
            _trim_messages(self.messages, MAX_CHAT_MESSAGES)

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
                followup = _validation_followup(iteration)
                messages.append(followup)
                # Retry loop: if validation failed give the agent extra turns to fix it.
                for _retry in range(MAX_VALIDATION_RETRIES):
                    if _is_validation_ok(followup):
                        break
                    print(
                        f"{ASSISTANT_COLOR}[retry {_retry + 1}/{MAX_VALIDATION_RETRIES}] "
                        f"Validation failed — giving agent a repair turn.{RESET}"
                    )
                    self._turn(
                        messages,
                        IMPROVE_SYSTEM_PROMPT,
                        IMPROVE_MODEL,
                        max_tokens=4096,
                    )
                    followup = _validation_followup(iteration)
                    messages.append(followup)
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
        """Run one agent turn, looping until the model stops requesting tools.

        Text responses are streamed token-by-token for immediate feedback.
        Tool-use rounds also stream, but only text deltas are printed live;
        the final message is used to dispatch tool calls as usual.
        """
        while True:
            with self.client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                tools=TOOLS,
            ) as stream:
                printed_any = False
                for text_delta in stream.text_stream:
                    print(f"{ASSISTANT_COLOR}{text_delta}{RESET}", end="", flush=True)
                    printed_any = True
                if printed_any:
                    print()  # newline after streamed text
                response = stream.get_final_message()

            messages.append({"role": "assistant", "content": response.content})

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                return

            messages.append({"role": "user", "content": _run_tool_calls(tool_uses)})


def _trim_messages(messages: list[dict], max_messages: int) -> None:
    """Drop the oldest messages when the list exceeds *max_messages*.

    Messages are always dropped in pairs (user + assistant) from the front so
    the list stays structurally valid (starts with a user message, alternates
    roles).  At least 2 messages are always preserved.
    """
    floor = max(max_messages, 2)
    while len(messages) > floor:
        # Remove the two oldest messages as a pair.
        messages.pop(0)
        if len(messages) > floor:
            messages.pop(0)


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


def _is_validation_ok(followup_msg: dict) -> bool:
    """Return True when a _validation_followup message indicates success.

    We check the content string for absence of the FAILED sentinel so we
    do not have to thread the raw exit-code through extra call-sites.
    """
    content = followup_msg.get("content", "")
    return "validation FAILED" not in content


def _validation_followup(iteration: int = 0) -> dict:
    result = tools.call_tool({"command": VALIDATION_COMMAND, "timeout": 30})
    exit_code = result["exit_code"]
    print(f"{ASSISTANT_COLOR}Validation exit code: {exit_code}{RESET}")

    if exit_code == 0:
        _auto_commit(iteration)

    extra = (
        ""
        if exit_code == 0
        else (
            "\n\nThe validation FAILED (non-zero exit code). "
            "Please inspect the error above, fix the issue, and re-validate "
            "before moving on."
        )
    )
    return {
        "role": "user",
        "content": (
            "Validation result for the last iteration:\n"
            f"{json.dumps(result, indent=2)}\n\n"
            "If the change is complete and validated, record the outcome in "
            "clio_capabilities.json using bash. Then continue with the next "
            "most useful capability unless the iteration budget is done."
            + extra
        ),
    }


def _auto_commit(iteration: int) -> None:
    """Stage all tracked modified files + clio_capabilities.json and commit to AGENT_BRANCH."""
    # Ensure we are on the agent branch (switch if needed, stashing nothing – we just commit)
    branch_result = tools.call_tool({"command": "git rev-parse --abbrev-ref HEAD", "timeout": 10})
    current_branch = branch_result.get("stdout", "").strip()

    if current_branch != AGENT_BRANCH:
        switch = tools.call_tool(
            {"command": f"git checkout {AGENT_BRANCH} 2>&1 || git checkout -b {AGENT_BRANCH} 2>&1", "timeout": 10}
        )
        if switch.get("exit_code") != 0:
            print(f"{ASSISTANT_COLOR}[auto-commit] Could not switch to {AGENT_BRANCH}: {switch.get('stderr', '')}{RESET}")
            return

    stage = tools.call_tool(
        {"command": "git add src/clio.py src/tools.py src/prompts.py pyproject.toml README.md clio_capabilities.json 2>&1", "timeout": 10}
    )
    if stage.get("exit_code") != 0:
        print(f"{ASSISTANT_COLOR}[auto-commit] git add failed: {stage.get('stderr', '')}{RESET}")
        return

    # Check if there is anything to commit
    status = tools.call_tool({"command": "git diff --cached --stat", "timeout": 10})
    if not status.get("stdout", "").strip():
        print(f"{ASSISTANT_COLOR}[auto-commit] Nothing staged – skipping commit for iteration {iteration}.{RESET}")
        return

    diff_stat = status.get("stdout", "").strip()
    subject = f"feat(agent): self-improvement iteration {iteration}"
    body = f"Changed files:\n{diff_stat}"
    # Write commit message to a temp file (avoids shell-quoting issues with multiline text)
    msg_file = pathlib.Path("/tmp/clio_commit_msg.txt")
    msg_file.write_text(f"{subject}\n\n{body}\n")
    commit = tools.call_tool({"command": f"git commit -F /tmp/clio_commit_msg.txt 2>&1", "timeout": 15})
    if commit.get("exit_code") == 0:
        print(f"{ASSISTANT_COLOR}[auto-commit] Committed iteration {iteration} to branch '{AGENT_BRANCH}'.{RESET}")
        # Push the branch so the remote stays in sync with every validated improvement.
        push = tools.call_tool(
            {"command": f"git push origin {AGENT_BRANCH} 2>&1", "timeout": 30}
        )
        if push.get("exit_code") == 0:
            print(f"{ASSISTANT_COLOR}[auto-commit] Pushed branch '{AGENT_BRANCH}' to origin.{RESET}")
        else:
            print(f"{ASSISTANT_COLOR}[auto-commit] Push failed: {push.get('stdout', '')} {push.get('stderr', '')}{RESET}")
    else:
        print(f"{ASSISTANT_COLOR}[auto-commit] Commit failed: {commit.get('stdout', '')} {commit.get('stderr', '')}{RESET}")


def main() -> None:
    Clio().run()


if __name__ == "__main__":
    main()
