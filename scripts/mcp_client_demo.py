#!/usr/bin/env python3
"""Walk a CareCircle scenario using a real MCP client over Streamable HTTP.

Useful for the demo video and as proof that any MCP client (not just our simulator) can drive it.

    python -m carecircle serve --demo                       # terminal 1
    python scripts/mcp_client_demo.py                       # terminal 2
    python scripts/mcp_client_demo.py --url https://my.tunnel/mcp --token secret
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os

import httpx2  # installed as a dependency of the MCP SDK
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

SCENARIO = [
    ("Amma says good morning", "log_checkin", {"person": "Amma", "note": "Good morning, I feel fine", "mood": "good"}),
    ("A caregiver sets a routine", "create_reminder",
     {"person": "Amma", "title": "Evening walk", "time": "18:00", "days": "daily", "requested_by": "Priya"}),
    ("Rahul leaves a message", "leave_message",
     {"sender": "Rahul", "recipient": "Amma", "message": "I will call at 7"}),
    ("Amma asks what is waiting", "get_pending_items", {"person": "Amma"}),
    ("Amma feels unwell", "log_checkin", {"person": "Amma", "note": "I feel dizzy and my knee hurts"}),
    ("Amma falls", "log_checkin", {"person": "Amma", "note": "I fell down in the bathroom"}),
    ("A caregiver reads the day", "get_daily_summary", {"person": "Amma"}),
]


def show(title: str, tool: str, args: dict, result: dict) -> None:
    print(f"\n\u25b6 {title}\n  {tool}({json.dumps(args, ensure_ascii=False)})")
    for line in json.dumps(result, indent=2, ensure_ascii=False).splitlines():
        print("  " + line)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=os.environ.get("CARECIRCLE_URL", "http://127.0.0.1:8000/mcp"))
    parser.add_argument("--token", default=os.environ.get("CARECIRCLE_MCP_TOKEN"))
    args = parser.parse_args()

    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    http = httpx2.AsyncClient(headers=headers)
    async with Client(streamable_http_client(args.url, http_client=http)) as client:
        print(f"Connected to {client.server_info.name} {client.server_info.version} "
              f"(MCP protocol {client.protocol_version})")
        tools = (await client.list_tools()).tools
        print(f"{len(tools)} tools: " + ", ".join(t.name for t in tools))
        for title, tool, arguments in SCENARIO:
            result = await client.call_tool(tool, arguments)
            show(title, tool, arguments, result.structured_content or {})


if __name__ == "__main__":
    asyncio.run(main())
