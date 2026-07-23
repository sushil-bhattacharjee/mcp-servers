# mcp-servers — MCP servers for network automation

LLM-agent tooling for Cisco lab automation via the Model Context Protocol:

- **[cml-mcp](cml-mcp/)** — Cisco Modeling Labs control plane: build topologies,
  render day-0 bootstrap configs (IOS-XE/NX-OS), manage lab lifecycle. 23 tools.
- **[network-device-mcp](network-device-mcp/)** — live device data plane over SSH:
  show/config, interfaces, OSPF, BGP, ACLs, parsed verification. 13 tools.

Architecture and design doctrine: [architecture.md](architecture.md)
