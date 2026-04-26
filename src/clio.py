import anthropic
import json
import tools
from dotenv import load_dotenv

load_dotenv()

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


def main():
    """
    This is the entrypoint for the agent loop
    """
    client = anthropic.Anthropic()
    messages = []

    while True:
        user_input = input("> ").strip()
        if user_input in {"exit", "quit"}:
            break

        messages.append({"role": "user", "content": user_input})

        while True:
            response = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=1024,
                messages=messages,
                tools=TOOLS,
            )

            messages.append({"role": "assistant", "content": response.content})

            tool_uses = [
                block for block in response.content if block.type == "tool_use"
            ]
            if not tool_uses:
                print(
                    "\n".join(
                        block.text for block in response.content if block.type == "text"
                    )
                )
                break

            tool_results = []
            for tool_use in tool_uses:
                if tool_use.name != "bash":
                    result = {"error": f"Unknown tool: {tool_use.name}"}
                else:
                    result = tools.call_tool(tool_use.input)

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": json.dumps(result),
                    }
                )

            messages.append({"role": "user", "content": tool_results})


if __name__ == "__main__":
    main()
