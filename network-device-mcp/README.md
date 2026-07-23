# network-device-mcp — MCP server for Cisco IOS-XE & NX-OS devices

An [MCP](https://modelcontextprotocol.io) server that lets an LLM agent (Claude
Code, Claude Desktop, or any MCP host) operate live Cisco network devices over
SSH: run show commands, configure interfaces, ACLs, OSPF and BGP, verify
neighborships with parsed results, and audit day-0 bootstrap state — with the
host's tool-approval gate as the human-in-the-loop.

Built with [fastmcp](https://gofastmcp.com) and
[Netmiko](https://github.com/ktbyers/netmiko). Transport: stdio (the MCP host
spawns this server as a child process). Companion server:
[cml-mcp](../cml-mcp/) manages the CML lab control plane; this server manages
the device data plane — deliberately separate credential and API boundaries.

## Architecture

```
Claude Code (MCP host) ──stdio JSON-RPC──▶ device_mcp_server.py (13 tools)
                                               │
                                               ▼
                                        platforms/ drivers
                                        iosxe.py · nxos.py
                                        render_* (syntax) · parse_* (output)
                                               │
                                               ▼
                                        Netmiko ── SSH :22 ──▶ devices
```

Platform differences (command syntax, `feature` prerequisites, output formats)
live entirely in `platforms/`; the tools are platform-agnostic and take
`platform: 'ios-xe' | 'nxos'` as a parameter. Adding a platform = one new
module + one dict entry in `platforms/__init__.py`, zero tool changes.

## Requirements

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- SSH reachability + credentials for the target devices
- An MCP host on the same machine (stdio transport)

## Setup

```bash
cd ~/mcp-servers/network-device-mcp
uv sync          # or: uv init && uv add fastmcp netmiko python-dotenv
cp .env.example .env && chmod 600 .env    # then edit with real credentials
```

`.env` / `.env.example` contents:

```
DEVICE_USER=admin
DEVICE_PASS=changeme
```

One credential pair for all devices (typical lab setup). The server refuses
tool calls with a readable error if these are unset. **Never commit `.env`** —
`.gitignore` must contain `.env`, `.venv/`, `__pycache__/`.

Quick tests:

```bash
uv run python -c "import device_mcp_server; print('imports clean')"
uv run test_device_client.py     # spawn, handshake, tools/list, live tool call
```

Register with Claude Code:

```bash
claude mcp add netdev -- uv --directory /home/<you>/mcp-servers/network-device-mcp run device_mcp_server.py
```

**After editing any file, reconnect the server** (`/mcp` → netdev → Reconnect) —
the running child process never picks up file edits.

## Tools

| Tool | Purpose | Risk |
|---|---|---|
| `check_reachability(host)` | TCP :22 probe (post-boot gate) | read |
| `run_show(host, platform, command)` | Any `show` command, raw output (refuses non-show) | read |
| `get_running_config(host, platform, section?)` | Full or section-filtered running config | read |
| `verify_day0(host, platform)` | One-call bootstrap audit: SSH, hostname, Loopback0, restconf/netconf(/nxapi) | read |
| `check_ospf_neighbors(host, platform)` | Parsed neighbor table + FULL count + raw | read |
| `check_bgp_neighbors(host, platform)` | Parsed BGP summary + Established count + raw | read |
| `send_config(host, platform, commands)` | Freeform config push; echo scanned into `rejected_lines` | write |
| `configure_interface(...)` | IP + no shut (+ `no switchport` on NX-OS Ethernet); self-verifying | write |
| `configure_ospf(...)` | Process/router-id/area/interfaces (`feature ospf` auto on NX-OS) | write |
| `configure_bgp(...)` | ASN/router-id/neighbors/networks (`feature bgp` auto on NX-OS) | write |
| `configure_acl(...)` | Standard/extended ACL from native ACE lines; `replace=true` = atomic redefine; self-verifying | write |
| `apply_acl(...)` | Bind ACL to interface in/out; self-verifying | write |
| `save_config(host, platform)` | copy run start — call only after verification | write |

### Design principles (learned the hard way)

- **Structured tools for common patterns, `send_config` as the escape hatch.**
  Structured tools render correct per-platform syntax so the LLM chooses
  *parameters*, not raw CLI. Anything not covered flows through `send_config`
  under the approval gate.
- **Errors are data.** Tools return `{"error": ...}` dicts with the valid
  options listed; the device echo is scanned for rejection markers
  (`rejected_lines`) so failures are machine-detectable, not buried in text.
- **Self-verification.** Config tools re-read the device and include a
  `verification` field; check tools return both `parsed` and `raw` so the
  agent (and human) can reconcile fields, not just counts.
- **Configure ≠ verified.** Docstrings instruct the agent to confirm
  adjacencies with the check tools rather than assume success.

## Security

- The server holds device credentials (`.env`, mode 600, git-ignored) and can
  push **any** configuration via `send_config` — including changes that break
  routing or lock out management access. Keep the host's approval prompts on
  for all write tools.
- The MCP boundary is a convenience boundary, not a security boundary: an agent
  with shell access on the same machine can read `.env` and bypass the tools.
  Real credential isolation requires an OS boundary (separate user, secrets
  manager).
- Care rules that belong in your host's context file (e.g. `CLAUDE.md`): never
  modify Loopback0 on a running device; never apply ACLs to management
  interfaces without explicit confirmation; never save without instruction.

## Known limitations

- **Screen-scrape parsers.** `parse_ospf_neighbors` / `parse_bgp_summary` are
  regex-based; they handle broadcast and point-to-point state formats
  (`FULL/DR`, `FULL/ -`) but unusual outputs may slip through — the `raw`
  field is always returned for reconciliation. NETCONF-based operational reads
  are the long-term fix.
- Connect-per-call: each tool opens and closes an SSH session (~1–2 s
  overhead). Connection pooling is a future optimization.
- `configure_interface` is not atomic: if one line is rejected (e.g. IP
  overlap) earlier lines (description, no shut) still apply. Read
  `rejected_lines`.
- No IPv6, VRF-aware, or vty/line ACL structured support yet — use
  `send_config`.

## Project layout

```
network-device-mcp/
├── device_mcp_server.py     # the MCP server (13 tools)
├── platforms/
│   ├── __init__.py          # PLATFORMS registry
│   ├── iosxe.py             # IOS-XE syntax + parsers
│   └── nxos.py              # NX-OS syntax + parsers
├── test_device_client.py    # minimal MCP host for protocol-level testing
├── .env.example             # credential template (committed)
└── .env                     # real credentials (never committed, chmod 600)
```
