"""Minimal stdio MCP client.

Only what the calendar tool needs: spawn the server, initialize, call one tool,
shut down. Kept dependency-free so the graph does not need the whole adapter
stack to write a single event.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from typing import Any

PROTOCOL_VERSION = "2024-11-05"


def call_mcp_tool(
    *, command: str, tool_name: str, arguments: dict[str, Any], timeout: float = 30.0
) -> str:
    """Call one tool on a stdio MCP server. Returns text, or "ERROR: ..."."""
    argv = shlex.split(command)
    proc: subprocess.Popen | None = None
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        def send(payload: dict) -> None:
            assert proc.stdin
            proc.stdin.write(json.dumps(payload) + "\n")
            proc.stdin.flush()

        def read_result(expect_id: int) -> dict:
            assert proc.stdout
            while True:
                line = proc.stdout.readline()
                if not line:
                    raise RuntimeError("MCP server closed the connection")
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue  # servers log to stdout; skip non-JSON chatter
                if msg.get("id") == expect_id:
                    return msg

        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "recall", "version": "0.1.0"},
                },
            }
        )
        read_result(1)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            }
        )
        msg = read_result(2)

        if "error" in msg:
            return f"ERROR: MCP tool {tool_name} failed: {msg['error']}"
        content = msg.get("result", {}).get("content", [])
        text = " ".join(c.get("text", "") for c in content if c.get("type") == "text")
        return text or json.dumps(msg.get("result", {}))
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: MCP call failed ({type(exc).__name__}): {exc}"
    finally:
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                proc.kill()
