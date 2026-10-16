# Friction log

Entries are real issues hit while building CareCircle. **Section B is intentionally left for you**: the hackathon
asks for feedback on every Amazon tool you actually used, and that must come from your own hands-on experience with
the Alexa+ / MCP developer tooling.

Severity: **S1** blocker · **S2** significant slowdown · **S3** papercut.

## A. MCP Python SDK (observed while building)

| # | Task | What I expected | What happened | Sev | Workaround | Suggestion |
|---|---|---|---|---|---|---|
| A1 | Create a server following common tutorials | `from mcp.server.fastmcp import FastMCP` works | `pip install mcp` now resolves to 2.x where `FastMCP` is `MCPServer`; the import raises a helpful message but nearly every tutorial and blog post still shows the v1 API | S2 | Read the v2 migration guide; use `mcp.server.mcpserver.MCPServer` | Pin guidance in quick-start docs; show both import paths side by side |
| A2 | Add an auth header to the HTTP client | Pass `headers=` to the client | The client takes an `httpx2.AsyncClient`, a package name I had never seen; undiscoverable from the error when I passed `httpx` | S3 | Inspect the function signature | Document an auth example for `streamable_http_client` |
| A3 | Test the server in pytest | An async fixture can yield a connected `Client` | Opening the client's task group in a fixture and closing it in teardown raised cancel-scope errors (different tasks) | S3 | Open `async with Client(server)` inside each test | Note in the testing docs that clients must be entered and exited in the same task |
| A4 | Serve extra routes (health, UI, JSON API) next to `/mcp` | One obvious way | `custom_route` works well but the relationship with `streamable_http_app()` (routes must be registered *before* building the app) is only discoverable by reading source | S3 | Register routes first | Mention the ordering in docs |
| A5 | Return structured results | Plain `dict` return becomes `structured_content` | Works. Noted as a positive: no extra schema code needed | n/a | n/a | n/a |

## B. Amazon tools (fill in from your own experience)

For each Amazon tool, API or SDK you use (Alexa+ developer console / MCP registration, simulators, docs, sample
code, office hours), record:

| # | Task attempted | Steps taken | Expected | Actual | Sev | Workaround | Suggestion |
|---|---|---|---|---|---|---|---|
| B1 | *e.g. register an MCP server with Alexa+* | | | | | | |
| B2 | | | | | | | |

Submissions with friction logs can earn up to a 10% judging bonus, so be specific and actionable.
