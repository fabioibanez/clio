import subprocess


def call_tool(args: dict) -> dict:
    print(f"Calling tool: {args}")
    command = args["command"]
    timeout = args.get("timeout", 30)

    result = subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )

    return {
        "command": command,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
