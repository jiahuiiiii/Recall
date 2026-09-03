"""Probe the calendar backend before trusting it. Writes nothing, ever.

    uv run check_calendar.py

Same shape as 00_check_bedrock.py: it *probes* rather than reports config, because
"RECALL_CALENDAR=mcp is set" and "an event would actually land on a calendar" are
different claims and only the second one matters on stage.

Deliberately does NOT import recall.mcp_client. A diagnostic that shares its
handshake with the code it is diagnosing cannot detect that handshake being
wrong -- it would fail identically and tell you nothing. The protocol below is a
second implementation on purpose.

Four things can be broken independently, so each is checked and reported alone:

  1. the server binary does not start           -> you get a stderr dump here,
                                                   which recall/mcp_client.py
                                                   swallows entirely
  2. it starts but does not speak MCP           -> handshake times out
  3. it speaks MCP but has no tool by that name -> GCAL_MCP_TOOL is wrong
  4. the tool exists but wants different args   -> the silent one. write_event()
                                                   sends summary/start/end/
                                                   description and gets back an
                                                   ERROR string that the graph
                                                   records and moves past.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from dotenv import load_dotenv

    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parent / ".env"):
        if candidate.exists():
            load_dotenv(candidate)
            break
except ImportError:
    pass

PROTOCOL_VERSION = "2024-11-05"

# What recall/tools/calendar.py::_write_mcp actually sends. Hardcoded here so a
# change there shows up as a mismatch rather than being followed silently.
RECALL_SENDS = {"summary", "start", "end", "description"}

OK, BAD, INFO = "  OK  ", " FAIL ", "  ..  "


def say(mark: str, text: str) -> None:
    print(f"[{mark}] {text}")


def probe_tools(command: str, timeout: float = 45.0) -> list[dict] | str:
    """Spawn the server, handshake, and ask what tools it has.

    Returns the tool list, or an error string. `tools/list` is a read -- nothing
    reaches a calendar from this script under any code path.
    """
    argv = shlex.split(command)
    if not shutil.which(argv[0]):
        return f"'{argv[0]}' is not on PATH"

    proc = None
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
            proc.stdin.write(json.dumps(payload) + "\n")
            proc.stdin.flush()

        def read(expect_id: int) -> dict:
            while True:
                line = proc.stdout.readline()
                if not line:
                    err = (proc.stderr.read() or "").strip()
                    raise RuntimeError(
                        "server closed the connection"
                        + (f"\n\n--- its stderr ---\n{err}" if err else
                           " and printed nothing to stderr")
                    )
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("id") == expect_id:
                    return msg

        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                         "clientInfo": {"name": "recall-probe", "version": "0.1.0"}}})
        info = read(1)
        server = info.get("result", {}).get("serverInfo", {})
        say(OK, f"handshake — {server.get('name', '?')} {server.get('version', '')}".rstrip())

        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        msg = read(2)
        if "error" in msg:
            return f"tools/list failed: {msg['error']}"
        return msg.get("result", {}).get("tools", [])
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"
    finally:
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                proc.kill()


def main() -> int:
    backend = os.environ.get("RECALL_CALENDAR", "local").lower()
    ledger = Path(os.environ.get("RECALL_CALENDAR_PATH", "data/calendar.json"))

    print(f"\nbackend      RECALL_CALENDAR={backend}")
    print(f"ledger       {ledger}  ({'exists' if ledger.exists() else 'not created yet'})\n")

    if backend != "mcp":
        say(OK, "local JSON ledger — offline, free, nothing to test.")
        print("\n     To test the MCP path, set in .env:")
        print("       RECALL_CALENDAR=mcp")
        print("       GCAL_MCP_COMMAND=npx -y @cocal/google-calendar-mcp")
        print("       GCAL_MCP_TOOL=create-event")
        return 0

    command = os.environ.get("GCAL_MCP_COMMAND")
    if not command:
        say(BAD, "RECALL_CALENDAR=mcp but GCAL_MCP_COMMAND is unset.")
        print("\n     Every write returns ERROR and the run continues past it.")
        return 1
    say(INFO, f"spawning: {command}")

    tools = probe_tools(command)
    if isinstance(tools, str):
        say(BAD, tools)
        print("\n     recall/mcp_client.py captures stderr and never reads it, so this")
        print("     failure reaches the graph as one line and no detail. Run the command")
        print("     by hand to see what the server is complaining about:")
        print(f"       {command}")
        return 1

    names = [t.get("name", "") for t in tools]
    say(OK, f"{len(names)} tool(s): {', '.join(names) or '(none)'}")

    wanted = os.environ.get("GCAL_MCP_TOOL", "create-event")
    match = next((t for t in tools if t.get("name") == wanted), None)
    if match is None:
        say(BAD, f"GCAL_MCP_TOOL={wanted!r} is not one of them.")
        print("\n     Pick the creating tool from the list above and set GCAL_MCP_TOOL to it.")
        return 1
    say(OK, f"GCAL_MCP_TOOL={wanted!r} exists")

    schema = (match.get("inputSchema") or {}).get("properties") or {}
    required = set((match.get("inputSchema") or {}).get("required") or [])
    accepted = set(schema)

    unknown = RECALL_SENDS - accepted if accepted else set()
    missing = required - RECALL_SENDS

    print(f"\n     tool accepts : {', '.join(sorted(accepted)) or '(no schema published)'}")
    print(f"     tool requires: {', '.join(sorted(required)) or '(nothing)'}")
    print(f"     recall sends : {', '.join(sorted(RECALL_SENDS))}\n")

    if not accepted:
        say(INFO, "no input schema published — cannot check the arguments statically.")
    elif unknown or missing:
        say(BAD, "argument mismatch — this is the failure that looks like success.")
        if missing:
            print(f"       required but never sent: {', '.join(sorted(missing))}")
        if unknown:
            print(f"       sent but not accepted:   {', '.join(sorted(unknown))}")
        print("\n     Fix the arguments dict in recall/tools/calendar.py::_write_mcp.")
        return 1
    else:
        say(OK, "argument names line up with what _write_mcp sends")

    print("\n     Protocol, tool name and arguments all check out. What this does NOT")
    print("     prove: that OAuth is authorised, or that the event lands on the calendar")
    print("     you expect. For that, do one real write and go look:")
    print("       RECALL_CALENDAR_PATH=/tmp/cal-test.json uv run run_demo.py\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
