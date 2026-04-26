import anthropic
import json
import tools
import time
from dotenv import load_dotenv

load_dotenv()

YOU_COLOR = "\u001b[94m"
ASSISTANT_COLOR = "\u001b[93m"
RESET_COLOR = "\u001b[0m"

TOOLS = [
    {
        "name": "bash",
        "description": "Execute a bash command and return stdout, stderr, and exit code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute.",
                },
                "args": {"type": "array", "items": {"type": "string"}},
                "timeout": {
                    "type": "integer",
                    "description": "Maximum execution time in seconds.",
                    "default": 30,
                },
            },
            "required": ["command"],
        },
    }
]


class clio:
    def __init__(self):
        self.client = anthropic.Anthropic()
        self.messages = []
        self.tools = TOOLS

    def _call_tools(self, tool_uses: list[dict]) -> list[dict]:
        tool_results = []
        for tool in tool_uses:
            result = tools.call_tool(tool)
            tool_results.append(result)
        return tool_results

    # want to understand the format of the content first
    def _add_to_context(self, role: str, content):
        pass

    def run(self):
        while True:
            try:
                user_input = input(f"{YOU_COLOR}> {RESET_COLOR}").strip()
            except KeyboardInterrupt:
                print(f"{RESET_COLOR}\ 再见, goodbye, adiós")
                break

            if user_input in {"exit", "quit"}:
                print(f"{RESET_COLOR}If you want to dip, please ctrl+c")
                time.sleep(1)
                continue

            self.messages.append({"role": "user", "content": user_input})

            # tool calling loop
            while True:
                response = self.client.messages.create(
                    model="claude-haiku-4-5",
                    max_tokens=1024,
                    messages=self.messages,
                    tools=self.tools,
                )

                # add to context
                self.messages.append({"role": "assistant", "content": response.content})
                tool_uses = [
                    block for block in response.content if block.type == "tool_use"
                ]
                if not tool_uses:
                    # simply print the response
                    print(
                        f"{ASSISTANT_COLOR}"
                        + "\n".join(
                            block.text
                            for block in response.content
                            if block.type == "text"
                        )
                    )
                    break

                tool_result = self._call_tools(tool_uses)

                self.messages.append({"role": "user", "content": tool_result})


def main():
    agent = clio()
    agent.run()


if __name__ == "__main__":
    main()
