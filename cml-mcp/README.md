# cml-mcp — MCP server for Cisco Modeling Labs

An [MCP](https://modelcontextprotocol.io) server that lets an LLM agent (Claude
Code, Claude Desktop, or any MCP host) drive a **Cisco CML 2.8** controller
end-to-end: build topologies from scratch, render and apply proven day-0
bootstrap configs (IOS-XE and NX-OS), manage lab/node lifecycle, edit configs
surgically, change node RAM safely, and delete nodes or labs — all through
natural-language prompts, with the host's tool-approval gate as the
human-in-the-loop.

Built with [fastmcp](https://gofastmcp.com) and the official
[virl2_client](https://pubhub.devnetcloud.com/media/virl2-client/docs/latest/)
library. Transport: stdio (the MCP host spawns this server as a child process).
Companion server: [network-device-mcp](../network-device-mcp/) operates the
booted devices (SSH/OSPF/BGP/ACL) — deliberately separate credential and API
boundaries: this server manages the lab control plane, that one the device
data plane.

## Requirements

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Cisco CML 2.8 controller reachable over HTTPS
- CML **application** credentials (the web-GUI login, not the cockpit/system
  account)
- An MCP host on the same machine (stdio transport)

## Setup

```bash
cd ~/mcp-servers/cml-mcp
uv sync        # or: uv init && uv add fastmcp virl2-client python-dotenv jinja2
cp .env.example .env && chmod 600 .env    # then edit with real values
```

`.env` / `.env.example` contents:

```
CML_URL=https://192.168.1.10
CML_USER=admin
CML_PASS=changeme
DAY0_USER=admin
DAY0_PASS=changeme
DAY0_PASS_HASH_NXOS=$5$replace$with-a-type5-hash-from-a-real-nxos-device
```

- `CML_*` — controller URL and application-admin credentials (JWT auth).
- `DAY0_USER` / `DAY0_PASS` — default device account rendered into day-0
  configs by `apply_day0_config` (overridable per call).
- `DAY0_PASS_HASH_NXOS` — **type-5 hash** of the same password, used for
  NX-OS day-0. NX-OS mis-ingests cleartext `password 0` during config replay
  (found the hard way — cleartext works interactively but not at boot), so
  the template renders `password 5 <hash>` instead. Get a portable hash by
  creating the user once on any live NX-OS box and copying the `$5$...`
  string from its running config.

The server loads `.env` from its own directory, so it works regardless of the
host's working directory. **Never commit `.env`** — `.gitignore` must contain
`.env`, `.venv/`, `__pycache__/`.

## Quick test (no MCP host needed)

```bash
uv run test_cml.py            # raw connectivity: CML version + lab list
uv run python -c "import cml_mcp_server; print('imports clean')"
uv run test_mcp_client.py     # full MCP round-trip: spawn, handshake, tools/list, tools/call
```

## Register with Claude Code

```bash
claude mcp add cml -- uv --directory /home/<you>/mcp-servers/cml-mcp run cml_mcp_server.py
```

**After editing server code, reconnect** (`/mcp` → cml → Reconnect) — the
running child process never picks up file edits.

## Tools (23)

| Group | Tools | Risk |
|---|---|---|
| Read | `list_labs` · `get_lab` · `get_lab_topology` · `check_lab_ready` · `get_node_config` · `list_node_definitions` | read |
| Build | `create_lab` · `add_node` · `add_link` · `apply_day0_config` | write |
| Lifecycle | `start_lab` · `stop_lab` · `start_node` · `stop_node` | write |
| Config surgery | `update_node_config` · `replace_in_node_config` · `extract_configs` | write |
| Duplicate | `duplicate_lab` (download → import) | write |
| Destructive | `wipe_node(confirm)` · `set_node_ram` · `delete_node` · `delete_lab(confirm)` | **destructive** |

Highlights:

- **`apply_day0_config`** renders a complete bootstrap (hostname, local user,
  SSH, NETCONF/RESTCONF, http(s), mgmt IP + default route — mgmt VRF on NX-OS —
  Loopback0, NTP, timezone) from proven Jinja templates in
  `day0_templates.py`, seeded from working device configs. Rendering happens
  server-side; the returned config is for review only.
- **`replace_in_node_config`** does find/replace server-side so bulk config
  text (cert blobs, 15 KB+ configs) never passes through the LLM — the safe
  way to make small edits to large day-0 configs.
- **`set_node_ram`** embeds the mandatory safety sequence (CML only allows RAM
  changes in wiped state): stop-check → extract config → verify non-empty →
  wipe → patch. The LLM cannot reorder or skip steps.
- **`add_link`** creates interfaces on demand and requires FULL interface
  labels (`GigabitEthernet2`, `Ethernet1/1`) — never shorthand — to kill
  cross-platform ambiguity.

## Design principles

- Dangerous sequences are atomic tools; every check aborts *before* anything
  irreversible.
- Errors are data (`{"error": ..., "Available": [...]}`) so the agent
  self-corrects in one step; the client connects lazily so a down controller
  is a readable per-call error, not a dead server.
- Docstrings steer the agent: usage order, warnings (mgmt-IP conflicts when
  cloning bridged labs), and refusal instructions (`delete_lab` demands
  explicit human confirmation).
- All destructive operations log at WARNING to stderr (stdout is the JSON-RPC
  channel); httpx request logging gives a per-REST-call audit trail in the
  host's MCP logs.

## CML behaviors worth knowing (discovered in anger)

- Day-0 config edits require the node in `DEFINED_ON_CORE` (wiped) state and
  only take effect on boot from wiped state — a stopped-but-booted node boots
  from its disk and ignores day-0.
- RAM (and other sim attributes) can only be modified in `DEFINED_ON_CORE` —
  a plain stop returns HTTP 400.
- Cloned labs keep the source's management IPs; starting source and clone on
  the same bridged network causes IP conflicts.
- External connectors default to NAT; set the connector config to `bridge0`
  to bridge into your LAN.
- nxosv9000 needs 5–8 minutes to boot and can need 1–2 more before SSH
  accepts logins.

## Security

- This server wields full CML application-admin power (can wipe/delete every
  lab). Credentials in `.env` (mode 600, git-ignored).
- The MCP boundary is a convenience boundary, not a security boundary: an
  agent with shell access on the same machine can read `.env` and drive the
  API directly. Real isolation needs an OS boundary.
- `confirm` parameters are steering, not fences — keep the host's approval
  prompts on for destructive tools.
- TLS verification is disabled (`ssl_verify=False`) for self-signed lab
  controllers; fix before pointing at anything that matters.

## Known limitations

- No client-side REST timeout (virl2_client 2.8 doesn't expose its HTTP
  session publicly) — a hung controller hangs the tool call until the host's
  own timeout fires.
- `start_lab`/`stop_lab`/`start_node`/`stop_node` return immediately
  (`wait=False`); poll with `check_lab_ready`.

## Project layout

```
cml-mcp/
├── cml_mcp_server.py     # the MCP server (23 tools)
├── day0_templates.py     # Jinja day-0 templates (ios-xe, nxos) + renderer
├── test_cml.py           # raw CML connectivity check
├── test_mcp_client.py    # minimal MCP host for protocol-level testing
├── .env.example          # credential template (committed)
└── .env                  # real credentials (never committed, chmod 600)
```
