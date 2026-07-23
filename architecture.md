# Architecture — MCP-driven network automation lab

Two MCP servers, one agentic host, a swappable-brain design. This document is
the GitHub-renderable version of `mcp_architecture.html` (same content, native
mermaid). Diagrams: high-level AI picture → machine topology → as-built tool
map → one tool call on the wire.

## 00 · The whole AI picture — where everything sits

Human intent on top, an **agentic layer** running the think→act→observe loop,
swappable **LLM brains**, **RAG** as retrievable knowledge, **MCP servers as
the hands**, and the network as the world being acted on. Solid = built and
running; dashed = planned evolution.

```mermaid
%%{init: {'theme':'dark'}}%%
flowchart TB
    YOU(["You — intent in natural language"])

    subgraph AGENTIC["AGENTIC LAYER — the loop: think → act → observe → repeat, with human approval gates"]
        CCODE["Claude Code<br/>MCP host (today)"]
        HITECH["hiTech Automation AI<br/>hand-rolled ReAct loop<br/>agency levels + approval gates"]
        LG["LangGraph (future)<br/>graph orchestrator: state,<br/>checkpoints, interrupts"]
    end

    subgraph BRAINS["REASONING — swappable LLM brains"]
        CLAUDE["Claude API<br/>(Anthropic)"]
        OLLAMA["Ollama — local<br/>gpt-oss · qwen<br/>(W11 GPU)"]
    end

    subgraph KNOW["KNOWLEDGE — RAG"]
        RAG["ChromaDB vector store<br/>YANG models · device docs<br/>retrieved into context per task"]
    end

    subgraph HANDS["HANDS — tools behind one standard protocol (MCP)"]
        MCP1["cml-mcp<br/>lab control plane"]
        MCP2["network-device-mcp<br/>device data plane"]
        MCPF["future domains<br/>tig-mcp · nso-mcp · apic-mcp"]
        INPROC["hiTech in-process tools<br/>NETCONF · RESTCONF · CLI · XPath<br/>(future: exposed as hitech-mcp)"]
    end

    subgraph WORLD["THE NETWORK — the world being acted on"]
        CMLW["CML labs<br/>(TRIANGLE-v11 ...)"]
        DEVW["live devices<br/>cat8Kv71/72 · nx9K73"]
        FUTW["TIG · NSO · APIC ..."]
    end

    YOU --> AGENTIC
    CCODE <-->|"reasoning"| CLAUDE
    HITECH <-->|"reasoning"| CLAUDE
    HITECH <-->|"reasoning"| OLLAMA
    HITECH <-->|"retrieve"| RAG
    CCODE -->|"tools/call"| MCP1
    CCODE -->|"tools/call"| MCP2
    HITECH --> INPROC
    MCP1 --> CMLW
    MCP2 --> CMLW
    MCP2 --> DEVW
    INPROC --> DEVW

    HITECH -.->|"phase 3: becomes MCP host"| MCP1
    HITECH -.->|"phase 3"| MCP2
    LG -.->|"replaces hand-rolled loop"| HITECH
    MCPF -.-> FUTW
    CCODE -.->|"when built"| MCPF

    classDef user fill:#0e2b28,stroke:#2a9d8f,stroke-width:2px,color:#c8ece6
    classDef agent fill:#3a2712,stroke:#d9762b,stroke-width:2px,color:#f2d4b0
    classDef future fill:#1d2733,stroke:#8b96a5,stroke-dasharray:5 4,color:#8b96a5
    classDef brain fill:#332b12,stroke:#e0b060,stroke-width:2px,color:#f2e3b8
    classDef know fill:#2a1e33,stroke:#a06cc9,stroke-width:2px,color:#e4d3f2
    classDef hands fill:#14283d,stroke:#4d80b8,stroke-width:2px,color:#cfe1f5
    classDef world fill:#331715,stroke:#c05a50,stroke-width:2px,color:#f0cbc7

    class YOU user
    class CCODE,HITECH agent
    class LG,MCPF,FUTW future
    class CLAUDE,OLLAMA brain
    class RAG know
    class MCP1,MCP2,INPROC hands
    class CMLW,DEVW world

    style AGENTIC fill:#1c130a,stroke:#d9762b,stroke-width:2px,color:#d9762b
    style BRAINS fill:#241e0c,stroke:#e0b060,stroke-width:1.5px,color:#e0b060
    style KNOW fill:#1e1626,stroke:#a06cc9,stroke-width:1.5px,color:#c9a8e0
    style HANDS fill:#0f1826,stroke:#4d80b8,stroke-width:2px,color:#7fa8d6
    style WORLD fill:#241110,stroke:#c05a50,stroke-width:2px,color:#c05a50
```

**The separation of roles is the design:** brains are swappable (Claude ↔
Ollama per task), orchestrators are swappable (hand-rolled ReAct loop today,
LangGraph when complexity justifies it), and hands are standardized — any MCP
host can drive any MCP server, so tools are written once and reused
everywhere. RAG feeds knowledge into the loop; approval gates keep a human
between decision and destructive action.

## 0b · Machine topology

Three machines, two credential boundaries, one bridged lab network:

![Lab topology](lab_topology.svg)

## 01 · One prompt, end to end

What happens on `duplicate lab DEVEXPERT as DEVEXPERT-lite`:

1. **Startup (once):** the host reads its MCP config, spawns each server as a
   child process, sends `initialize`, then `tools/list` — servers reply with
   every tool's name, description and JSON schema.
2. Prompt + tool schemas go to the LLM, which decides the first call
   (`list_labs` to resolve title → id).
3. Host sends `tools/call` over **stdio** to the server.
4. Server calls the backing API (CML REST with cached JWT / Netmiko SSH) and
   returns the result as tool output.
5. The LLM chains further calls; **write tools pause at the host's approval
   gate** — the human-in-the-loop.
6. Result feeds back; loop repeats until the LLM writes the final answer.

Same ReAct loop as any agent framework — over a standard protocol.

## 02 · MCP protocol — the wire itself

JSON-RPC 2.0 over the child process's stdin/stdout:

| Method | Direction | Purpose |
|---|---|---|
| `initialize` | host → server | Handshake: protocol version, capabilities, identities |
| `notifications/initialized` | host → server | Handshake complete |
| `tools/list` | host → server | Tool catalog: name, description, `inputSchema` (generated by fastmcp from type hints + docstrings) |
| `tools/call` | host → server | Execute one tool: `{name, arguments}` → result content or `isError` |
| `resources/*` · `prompts/*` | host → server | Optional extras — unused here |

## 03 · As-built architecture — both servers, all 36 tools

**cml-mcp v1.3** (23 tools, lab control plane) and **network-device-mcp v0.4**
(13 tools, device data plane). One host, two credential boundaries. Tool
groups are color-coded by risk: green = read, blue = lifecycle/protocols,
orange = build, purple = config surgery, red = destructive.

```mermaid
%%{init: {'theme':'dark'}}%%
flowchart LR
    USER(["You — natural-language prompt"])
    ANTH["Anthropic API<br/>Claude = brain<br/>(decides which tool, with what args)"]

    subgraph UBUNTU["UbuntuPro VM — 192.168.89.98"]
        CC["Claude Code — MCP HOST<br/>spawns servers as child processes<br/>runs agentic loop + approval gates"]

        subgraph CMLMCP["cml-mcp v1.3 — 23 tools (child process)"]
            C_READ["READ<br/>list_labs · get_lab · get_lab_topology<br/>check_lab_ready · get_node_config<br/>list_node_definitions"]
            C_BUILD["BUILD<br/>create_lab · add_node · add_link<br/>apply_day0_config (Jinja day-0)"]
            C_LIFE["LIFECYCLE<br/>start_lab · stop_lab<br/>start_node · stop_node"]
            C_CFG["CONFIG SURGERY<br/>update_node_config<br/>replace_in_node_config<br/>extract_configs"]
            C_DANGER["DESTRUCTIVE<br/>wipe_node · set_node_ram<br/>delete_node · delete_lab(confirm)"]
            VC["virl2_client<br/>lazy singleton · JWT from .env"]
        end

        subgraph NETDEV["network-device-mcp v0.4 — 13 tools (child process)"]
            N_READ["READ<br/>check_reachability · run_show<br/>get_running_config · verify_day0"]
            N_CFG["CONFIG<br/>send_config · configure_interface<br/>configure_acl · apply_acl · save_config"]
            N_PROTO["PROTOCOLS<br/>configure_ospf · configure_bgp"]
            N_VERIFY["VERIFY<br/>check_ospf_neighbors<br/>check_bgp_neighbors"]
            DRV["platforms/ drivers<br/>iosxe.py · nxos.py<br/>render_* (syntax) · parse_* (output)"]
            NM["Netmiko ConnectHandler<br/>creds from .env"]
        end
    end

    subgraph CMLVM["CML 2.8 VM — 192.168.89.100"]
        API["REST API /api/v0<br/>Bearer JWT"]
        TRI["Lab TRIANGLE-v11<br/>router1 .181 (ios-xe)<br/>router2 .182 (ios-xe)<br/>sw1 .183 (nxos)"]
    end

    LIVE["Live VMware devices<br/>cat8Kv71 .71 · cat8Kv72 .72<br/>nx9K73 .73"]

    USER --> CC
    CC <-->|"HTTPS — reasoning +<br/>tool decisions"| ANTH
    CC <-->|"stdio JSON-RPC 2.0<br/>initialize → tools/list → tools/call"| CMLMCP
    CC <-->|"stdio JSON-RPC 2.0<br/>initialize → tools/list → tools/call"| NETDEV

    C_READ --> VC
    C_BUILD --> VC
    C_LIFE --> VC
    C_CFG --> VC
    C_DANGER --> VC
    VC -->|"HTTPS /api/v0"| API
    API --> TRI

    N_READ --> DRV
    N_CFG --> DRV
    N_PROTO --> DRV
    N_VERIFY --> DRV
    DRV --> NM
    NM -->|"SSH :22"| TRI
    NM -->|"SSH :22"| LIVE

    classDef user fill:#0e2b28,stroke:#2a9d8f,stroke-width:2px,color:#c8ece6
    classDef brain fill:#332b12,stroke:#e0b060,stroke-width:2px,color:#f2e3b8
    classDef host fill:#3a2712,stroke:#d9762b,stroke-width:2px,color:#f2d4b0
    classDef read fill:#16351f,stroke:#3fae6a,color:#c9efd8
    classDef build fill:#3a2712,stroke:#d9762b,color:#f2d4b0
    classDef life fill:#14283d,stroke:#4d80b8,color:#cfe1f5
    classDef cfgc fill:#2a1e33,stroke:#a06cc9,color:#e4d3f2
    classDef danger fill:#3a1512,stroke:#e05252,stroke-width:2px,color:#f2c4c0
    classDef plumb fill:#1d2733,stroke:#8b96a5,color:#d7dde5
    classDef cml fill:#0e2b28,stroke:#2a9d8f,color:#c8ece6
    classDef dev fill:#331715,stroke:#c05a50,stroke-width:2px,color:#f0cbc7

    class USER user
    class ANTH brain
    class CC host
    class C_READ,N_READ,N_VERIFY read
    class C_BUILD build
    class C_LIFE life
    class C_CFG,N_CFG cfgc
    class N_PROTO life
    class C_DANGER danger
    class VC,DRV,NM plumb
    class API cml
    class TRI,LIVE dev

    style UBUNTU fill:#1c130a,stroke:#d9762b,stroke-width:2px,color:#d9762b
    style CMLMCP fill:#0c1e1b,stroke:#2a9d8f,stroke-width:1.5px,color:#2a9d8f
    style NETDEV fill:#0f1826,stroke:#4d80b8,stroke-width:1.5px,color:#7fa8d6
    style CMLVM fill:#0c1e1b,stroke:#2a9d8f,stroke-width:2px,color:#2a9d8f

    linkStyle 1 stroke:#e0b060,stroke-width:2px
    linkStyle 2,3 stroke:#2a9d8f,stroke-width:2px
    linkStyle 9,10 stroke:#4d80b8,stroke-width:2px
    linkStyle 16,17 stroke:#e05252,stroke-width:2px
```

## 04 · One tool call on the wire — configure + verify

The full round trip for "enable OSPF on router1 and verify": brain decision,
approval gate, stdio JSON-RPC, platform renderer, SSH push, echo scan, then
the chained verification call with parsed results.

```mermaid
%%{init: {'theme':'dark'}}%%
sequenceDiagram
    autonumber
    box rgba(42,157,143,0.15) operator
    participant U as You
    end
    box rgba(217,118,43,0.15) UbuntuPro — host
    participant CC as Claude Code<br/>(MCP host)
    end
    box rgba(224,176,96,0.12) cloud brain
    participant AN as Anthropic API<br/>(Claude brain)
    end
    box rgba(77,128,184,0.15) UbuntuPro — server
    participant NS as netdev server<br/>(child process)
    end
    box rgba(192,90,80,0.15) lab device
    participant R1 as router1<br/>192.168.89.181
    end

    Note over CC,NS: Session start (once): spawn child → initialize handshake → tools/list returns 13 schemas (docstrings + type hints)

    U->>CC: "Enable OSPF 1 area 0 on router1, then verify"
    CC->>AN: prompt + all tool schemas
    AN-->>CC: tool_use: configure_ospf(host=.181, platform=ios-xe, process_id=1, area=0, ...)
    CC->>U: approval gate (write tool)
    U-->>CC: approve
    CC->>NS: tools/call configure_ospf {args}
    NS->>NS: iosxe.render_ospf() → command list
    NS->>R1: Netmiko SSH — config mode, push commands
    R1-->>NS: device echo
    NS->>NS: scan echo → rejected_lines
    NS-->>CC: result {echo, rejected_lines: []}
    CC->>AN: tool_result
    AN-->>CC: tool_use: check_ospf_neighbors(host=.181, platform=ios-xe)
    CC->>NS: tools/call check_ospf_neighbors
    NS->>R1: show ip ospf neighbor
    R1-->>NS: raw table
    NS->>NS: parse_ospf_neighbors() → structured list
    NS-->>CC: {neighbors, full_count: 2, raw}
    CC->>AN: tool_result
    AN-->>CC: final answer text
    CC-->>U: "OSPF up — 2 FULL adjacencies (10.0.0.82, 10.0.0.83)"
```

## Design doctrine (extracted from the build)

- Dangerous sequences are **atomic tools** — the LLM cannot reorder or skip
  safety steps (`set_node_ram`: extract → verify → wipe → patch).
- **Bulk data stays server-side** (`replace_in_node_config`) — agents route
  around tools that force large payloads through the model.
- **Errors are data**: structured `{"error": ...}` results with valid
  options listed let the agent self-correct in one step.
- **Docstrings are the agent-facing API** — usage order, warnings and refusal
  instructions live there.
- **Verify, don't assume**: config tools self-verify; check tools return
  parsed *and* raw so fields can be reconciled, not just counts.
- The MCP boundary is a **convenience boundary, not a security boundary** —
  credential isolation requires an OS boundary; the real gates are host
  approval prompts.
