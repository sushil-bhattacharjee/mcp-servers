# mcp-servers — MCP servers for network automation

LLM-agent tooling for Cisco lab automation via the Model Context Protocol:

- **[cml-mcp](cml-mcp/)** — Cisco Modeling Labs control plane: build topologies,
  render day-0 bootstrap configs (IOS-XE/NX-OS), manage lab lifecycle. 23 tools.
- **[network-device-mcp](network-device-mcp/)** — live device data plane over SSH:
  show/config, interfaces, OSPF, BGP, ACLs, parsed verification. 13 tools.

Architecture and design doctrine: [architecture.md](architecture.md)

# mcp-servers — drive a Cisco lab with natural language

Two [MCP](https://modelcontextprotocol.io) servers that let an LLM agent
(Claude Code, or any MCP host) build, bootstrap, configure and verify a Cisco
network lab end-to-end from prompts like:

> *"Create a lab with 2 IOS-XE routers and an NX-OS switch in a triangle,
> apply day-0 configs with mgmt IPs, boot it, configure OSPF and a full eBGP
> mesh, and prove every adjacency is FULL/Established."*

| Server | Role | Tools |
|---|---|---|
| [cml-mcp](cml-mcp/) | Cisco Modeling Labs control plane: topology building, day-0 bootstrap (IOS-XE/NX-OS), lab lifecycle, safe wipe/RAM/delete | 23 |
| [network-device-mcp](network-device-mcp/) | Live device data plane over SSH: show/config, interfaces, OSPF, BGP, ACLs, parsed verification | 13 |

Architecture, diagrams and design doctrine: **[architecture.md](architecture.md)** ·
Repo internals and who-calls-whom: **[PROJECT.md](PROJECT.md)**

## Requirements

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Cisco CML 2.8 controller (for cml-mcp) and/or SSH-reachable IOS-XE / NX-OS
  devices (for network-device-mcp)
- An MCP host on the same machine — instructions below use
  [Claude Code](https://docs.claude.com/en/docs/claude-code)

## Installation

```bash
git clone https://github.com/sushil-bhattacharjee/mcp-servers.git
cd mcp-servers

# 1) cml-mcp
cd cml-mcp
uv sync
cp .env.example .env && chmod 600 .env     # edit: CML URL/credentials, day-0 creds
cd ..

# 2) network-device-mcp
cd network-device-mcp
uv sync
cp .env.example .env && chmod 600 .env     # edit: device SSH credentials
cd ..
```

Smoke-test each server without any MCP host:

```bash
cd cml-mcp            && uv run test_cml.py && uv run test_mcp_client.py && cd ..
cd network-device-mcp && uv run test_device_client.py && cd ..
```

## Register with Claude Code

```bash
claude mcp add cml    -- uv --directory /path/to/mcp-servers/cml-mcp            run cml_mcp_server.py
claude mcp add netdev -- uv --directory /path/to/mcp-servers/network-device-mcp run device_mcp_server.py
claude mcp list        # both should show ✓ Connected
```

Inside a `claude` session, `/mcp` lists both servers and their tools.
After editing any server file, reconnect it (`/mcp` → server → Reconnect) —
running child processes never pick up file edits.

## Quick start — first prompts

```
List my CML labs and show the node details of one of them.

Create a lab called DEMO with two cat8000v routers linked Gi2-to-Gi2,
apply day-0 configs (hostnames r1/r2, mgmt 192.168.89.191-192/24,
gateway 192.168.89.1), start it and poll until booted.

Check SSH reachability of 192.168.89.191, run verify_day0 on it (ios-xe),
then show its version.
```

Write/destructive tools pause at Claude Code's approval prompt — review the
call before approving. Lab-destroying tools additionally require explicit
confirmation in your prompt.

## Safety notes

- Credentials live only in each server's git-ignored `.env` (mode 600).
- These servers wield full CML-admin and device-config power. Point them only
  at labs you own; keep approval prompts enabled for write tools.
- Never modify Loopback0 on a running device; never apply ACLs to management
  interfaces without explicit intent — see each server's README for the full
  care list.

## License

MIT (see [LICENSE](LICENSE)).
