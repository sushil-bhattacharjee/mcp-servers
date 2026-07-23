"""CML MCP server — v1.3: lab lifecycle + config tools."""
import os
import urllib3
import sys
import logging

urllib3.disable_warnings()
from fastmcp import FastMCP
from virl2_client import ClientLibrary
from pathlib import Path
from dotenv import load_dotenv
from day0_templates import render_day0

logging.basicConfig(
    stream=sys.stderr,          # NEVER stdout — that's the protocol channel
    level=logging.INFO,
    format="%(asctime)s cml-mcp %(levelname)s %(message)s",
)
log = logging.getLogger("cml-mcp")
load_dotenv(Path(__file__).parent / ".env")

mcp = FastMCP("cml")

_client = None
def cml():
    """Lazy singleton — connect on first tool call, not at import."""
    global _client
    if _client is None:
        _client = ClientLibrary(
            os.environ["CML_URL"],
            os.environ["CML_USER"],
            os.environ["CML_PASS"],
            ssl_verify=False,
        )
        #_client.session.timeout = 30   # seconds, applies to all REST calls
        log.info("Connected to CML at %s", os.environ["CML_URL"])
    return _client

@mcp.tool()
def list_labs() -> list[dict]:
    """List all labs on the CML controller with id, title, state and node count."""
    out = []
    for lab in cml().all_labs():
        lab.sync()
        out.append({
            "id": lab.id,
            "title": lab.title,
            "state": lab.state(),
            "node_count": len(lab.nodes()),
        })
    return out

@mcp.tool()
def get_lab(lab_id: str) -> dict:
    """Get details of one lab: title, state, and per-node label/type/state/ram/cpus/ips.
    Use list_labs first to resolve a title to a lab_id."""
    lab = cml().join_existing_lab(lab_id)
    lab.sync()
    nodes = []
    for n in lab.nodes():
        nodes.append({
            "label": n.label,
            "node_definition": n.node_definition,
            "state": n.state,
            "ram_mb": n.ram,
            "cpus": n.cpus,
        })
    return {"id": lab.id, "title": lab.title, "state": lab.state(), "nodes": nodes}

@mcp.tool()
def duplicate_lab(lab_id: str, new_title: str) -> dict:
    """Duplicate an existing lab under a new title. Returns the new lab's id.
    The copy is created in DEFINED_ON_CORE state (not started).
    WARNING: the copy keeps the same device management IPs as the source —
    starting both labs at once will cause IP conflicts on the bridged network."""
    src = cml().join_existing_lab(lab_id)
    yaml_text = src.download()
    log.info("Duplicating lab %s as '%s'", lab_id, new_title)
    new_lab = cml().import_lab(yaml_text, title=new_title)
    return {"new_lab_id": new_lab.id, "title": new_lab.title, "state": new_lab.state()}

@mcp.tool()
def start_lab(lab_id: str) -> dict:
    """Start all nodes in a lab. Returns immediately without waiting for boot
    (cat8000v/nx9000v take several minutes). Poll with get_lab to check node states."""
    lab = cml().join_existing_lab(lab_id)
    lab.start(wait=False)
    lab.sync()
    return {"id": lab.id, "title": lab.title, "state": lab.state()}

@mcp.tool()
def stop_lab(lab_id: str) -> dict:
    """Stop all nodes in a lab. A plain stop preserves disks and configs
    (only wipe destroys them). Returns immediately; poll with get_lab."""
    lab = cml().join_existing_lab(lab_id)
    lab.stop(wait=False)
    lab.sync()
    return {"id": lab.id, "title": lab.title, "state": lab.state()}

@mcp.tool()
def delete_node(lab_id: str, node_label: str) -> dict:
    """Delete one node (and its links) from a lab, identified by its label
    (e.g. 'cat8Kv74'). The node must be stopped first. This is irreversible."""
    lab = cml().join_existing_lab(lab_id)
    lab.sync()
    matches = [n for n in lab.nodes() if n.label == node_label]
    if not matches:
        labels = [n.label for n in lab.nodes()]
        return {"error": f"No node labeled '{node_label}'. Available: {labels}"}
    node = matches[0]
    if node.state not in ("STOPPED", "DEFINED_ON_CORE"):
        return {"error": f"Node '{node_label}' is {node.state} — stop it first."}
    log.warning("Deleting node '%s' from lab %s", node_label, lab_id)
    node.remove()
    lab.sync()
    return {"deleted": node_label, "remaining_nodes": [n.label for n in lab.nodes()]}

@mcp.tool()
def extract_configs(lab_id: str) -> dict:
    """Extract running configs from all STOPPED nodes into the lab definition,
    so they survive wipe/export. Skips nodes that are running or have no config.
    Run this BEFORE any wipe operation."""
    lab = cml().join_existing_lab(lab_id)
    lab.sync()
    results = {}
    for n in lab.nodes():
        if n.state == "STOPPED":
            try:
                n.extract_configuration()
                results[n.label] = "extracted"
            except Exception as e:
                results[n.label] = f"failed: {e}"
        else:
            results[n.label] = f"skipped ({n.state})"
    return results

@mcp.tool()
def set_node_ram(lab_id: str, node_label: str, ram_mb: int) -> dict:
    """Change a node's RAM (in MB, e.g. 6144 for 6GB). CML only allows this in
    DEFINED_ON_CORE (wiped) state, so this tool runs a safety sequence:
    stop check -> extract config -> verify config non-empty -> wipe -> set RAM.
    The node is NOT restarted automatically — start the lab/node afterwards.
    The extracted config becomes day-0, so the device boots with its old config
    but loses non-config disk state (certs regenerate, bootflash files are lost)."""
    lab = cml().join_existing_lab(lab_id)
    lab.sync()
    matches = [n for n in lab.nodes() if n.label == node_label]
    if not matches:
        return {"error": f"No node labeled '{node_label}'. Available: {[n.label for n in lab.nodes()]}"}
    node = matches[0]

    # 1. Must be stopped (a running node can't be wiped safely)
    if node.state == "STARTED" or node.state == "BOOTED":
        return {"error": f"'{node_label}' is {node.state} — stop it first (stop_lab or GUI)."}

    # 2. Extract config unless already wiped
    if node.state == "STOPPED":
        try:
            node.extract_configuration()
        except Exception as e:
            return {"error": f"Config extraction failed: {e} — aborting, nothing wiped."}
        lab.sync()
        node = [n for n in lab.nodes() if n.label == node_label][0]
        # 3. Verify we actually captured something
        cfg = node.configuration
        if not cfg or len(cfg.strip()) < 50:
            return {"error": "Extracted config is empty/tiny — aborting before wipe. "
                            "Check the node console and extract manually."}
        # 4. Wipe — destroys disk, config we saved becomes day-0
        log.warning("Wiping node '%s' in lab %s (config extracted, %d chars)", node_label, lab_id, len(cfg))
        node.wipe()
        lab.sync()
        node = [n for n in lab.nodes() if n.label == node_label][0]

    # 5. Now DEFINED_ON_CORE — RAM change is allowed
    node.update({"ram": ram_mb}, exclude_configurations=True)
    lab.sync()
    node = [n for n in lab.nodes() if n.label == node_label][0]
    return {"label": node.label, "ram_mb": node.ram, "state": node.state,
            "note": "Config preserved as day-0. Start the node when ready."}

@mcp.tool()
def get_node_config(lab_id: str, node_label: str) -> dict:
    """Read a node's day-0 configuration text. Use this before update_node_config
    to see the current interface/IP layout."""
    lab = cml().join_existing_lab(lab_id)
    lab.sync()
    matches = [n for n in lab.nodes() if n.label == node_label]
    if not matches:
        return {"error": f"No node labeled '{node_label}'. Available: {[n.label for n in lab.nodes()]}"}
    return {"label": node_label, "config": matches[0].configuration or ""}

@mcp.tool()
def update_node_config(lab_id: str, node_label: str, config: str) -> dict:
    """Replace a node's day-0 configuration text (full replacement, not a patch).
    Node must be DEFINED_ON_CORE (wiped/never-booted) for the new config to take
    effect on next boot. Workflow: get_node_config -> modify text -> this tool.
    For small edits to large configs, prefer replace_in_node_config instead.
    For a booted node, config changes belong on the device itself (NETCONF/CLI),
    not here."""
    lab = cml().join_existing_lab(lab_id)
    lab.sync()
    matches = [n for n in lab.nodes() if n.label == node_label]
    if not matches:
        return {"error": f"No node labeled '{node_label}'. Available: {[n.label for n in lab.nodes()]}"}
    node = matches[0]
    if node.state not in ("DEFINED_ON_CORE", "STOPPED"):
        return {"error": f"'{node_label}' is {node.state} — config edits need a non-running node."}
    node.configuration = config
    lab.sync()
    return {"label": node_label, "state": node.state,
            "config_length": len(config), "note": "Applied as day-0; takes effect on next boot from wiped state."}

@mcp.tool()
def replace_in_node_config(lab_id: str, node_label: str, old: str, new: str) -> dict:
    """Find/replace a string in a node's day-0 config server-side (e.g. swap a
    management IP). The config text never passes through the LLM, so this is the
    safe way to make small edits to large configs. Returns the match count and
    the changed lines. Node must be DEFINED_ON_CORE or STOPPED."""
    lab = cml().join_existing_lab(lab_id)
    lab.sync()
    matches = [n for n in lab.nodes() if n.label == node_label]
    if not matches:
        return {"error": f"No node labeled '{node_label}'. Available: {[n.label for n in lab.nodes()]}"}
    node = matches[0]
    if node.state not in ("DEFINED_ON_CORE", "STOPPED"):
        return {"error": f"'{node_label}' is {node.state} — config edits need a non-running node."}
    cfg = node.configuration or ""
    count = cfg.count(old)
    if count == 0:
        return {"error": f"'{old}' not found in {node_label}'s config — nothing changed."}
    node.configuration = cfg.replace(old, new)
    lab.sync()
    log.info("Config replace on '%s': '%s' -> '%s' (%d occurrences)", node_label, old, new, count)
    changed = [l.strip() for l in (node.configuration or "").splitlines() if new in l]
    return {"label": node_label, "replacements": count, "changed_lines": changed}

@mcp.tool()
def delete_lab(lab_id: str, confirm: bool = False) -> dict:
    """PERMANENTLY delete an entire lab and all its nodes. Irreversible.
    The lab must be stopped or wiped first.
    Safety: requires confirm=true. Always ask the human user for explicit
    confirmation before calling this with confirm=true — never set it on
    your own initiative."""
    if not confirm:
        return {"error": "Refused: confirm=false. Ask the user to explicitly "
                        "confirm deletion, then call again with confirm=true."}
    lab = cml().join_existing_lab(lab_id)
    lab.sync()
    title = lab.title
    if lab.state() == "STARTED":
        return {"error": f"Lab '{title}' is running — stop it first."}
    log.warning("DELETING lab %s ('%s')", lab_id, title)
    lab.remove()
    return {"deleted": lab_id, "title": title}

@mcp.tool()
def list_node_definitions() -> list[str]:
    """List node definition ids available on this controller (e.g. cat8000v,
    nxosv9000, external_connector, unmanaged_switch). Use these exact ids
    when calling add_node."""
    defs = cml().definitions.node_definitions()
    return sorted(d["id"] for d in defs)

@mcp.tool()
def create_lab(title: str) -> dict:
    """Create a new empty lab. Returns its id. Add nodes with add_node,
    connect them with add_link, set day-0 configs, then start_lab."""
    lab = cml().create_lab(title)
    log.info("Created lab %s ('%s')", lab.id, title)
    return {"lab_id": lab.id, "title": lab.title}

@mcp.tool()
def add_node(lab_id: str, label: str, node_definition: str, x: int = 0, y: int = 0) -> dict:
    """Add a node to a lab. node_definition must be an exact id from
    list_node_definitions (e.g. 'cat8000v', 'nxosv9000', 'external_connector').
    x/y are canvas coordinates — spread nodes ~200 apart for readability.
    The node is created with no interfaces; add_link creates them on demand."""
    lab = cml().join_existing_lab(lab_id)
    node = lab.create_node(label, node_definition, x, y)
    log.info("Added node '%s' (%s) to lab %s", label, node_definition, lab_id)
    return {"label": node.label, "node_definition": node_definition, "state": node.state}

def _get_or_create_interface(lab, node, iface_label: str):
    """Find an interface by label, creating slots until it appears.
    CML names interfaces automatically per node definition
    (cat8000v: GigabitEthernet1, 2, ...; nxosv9000: mgmt0 then Ethernet1/1, ...)."""
    for i in node.interfaces():
        if i.label == iface_label:
            return i
    for _ in range(48):
        new = lab.create_interface(node)
        if new.label == iface_label:
            return new
    return None

@mcp.tool()
def add_link(lab_id: str, node_a: str, iface_a: str, node_b: str, iface_b: str) -> dict:
    """Connect two nodes with a link on specific interfaces, by node label and
    FULL interface label (e.g. 'GigabitEthernet2' on cat8000v, 'Ethernet1/1' on
    nxosv9000 — NOT shorthand like 'G2'). Interfaces are created on demand.
    Call get_lab_topology afterwards to verify. Nodes must not be running."""
    lab = cml().join_existing_lab(lab_id)
    lab.sync()
    nodes = {n.label: n for n in lab.nodes()}
    for lbl in (node_a, node_b):
        if lbl not in nodes:
            return {"error": f"No node '{lbl}'. Available: {list(nodes)}"}
    ia = _get_or_create_interface(lab, nodes[node_a], iface_a)
    if ia is None:
        return {"error": f"Could not create '{iface_a}' on {node_a}. "
                        f"Existing: {[i.label for i in nodes[node_a].interfaces()]}"}
    ib = _get_or_create_interface(lab, nodes[node_b], iface_b)
    if ib is None:
        return {"error": f"Could not create '{iface_b}' on {node_b}. "
                        f"Existing: {[i.label for i in nodes[node_b].interfaces()]}"}
    lab.create_link(ia, ib)
    log.info("Linked %s:%s <-> %s:%s in lab %s", node_a, iface_a, node_b, iface_b, lab_id)
    return {"link": f"{node_a}:{iface_a} <-> {node_b}:{iface_b}"}

@mcp.tool()
def get_lab_topology(lab_id: str) -> dict:
    """Show a lab's full topology: every node with its interfaces, and every
    link as nodeA:ifaceA <-> nodeB:ifaceB. Use to verify after building."""
    lab = cml().join_existing_lab(lab_id)
    lab.sync()
    nodes = {n.label: [i.label for i in n.interfaces()] for n in lab.nodes()}
    links = []
    for l in lab.links():
        a, b = l.interface_a, l.interface_b
        links.append(f"{a.node.label}:{a.label} <-> {b.node.label}:{b.label}")
    return {"title": lab.title, "nodes": nodes, "links": links}

@mcp.tool()
def check_lab_ready(lab_id: str) -> dict:
    """Report per-node boot status. A lab is ready when all nodes are BOOTED.
    Poll this after start_lab — cat8000v/nx9000v need 5-8 minutes to boot.
    Non-blocking by design: call repeatedly rather than waiting."""
    lab = cml().join_existing_lab(lab_id)
    lab.sync()
    states = {n.label: n.state for n in lab.nodes()}
    ready = all(s == "BOOTED" for s in states.values())
    return {"ready": ready, "states": states}

@mcp.tool()
def apply_day0_config(lab_id: str, node_label: str, platform: str, hostname: str,
                    mgmt_cidr: str, gateway: str, loopback0_ip: str,
                    username: str = "", password: str = "",
                    domain: str = "hitech007.com", ntp: str = "192.168.89.98",
                    dns: str = "") -> dict:
    """Render a complete day-0 bootstrap config from a proven template and write
    it to a node — covers hostname, local user, SSH, NETCONF, RESTCONF,
    http/https, management IP + default route (mgmt VRF on nxos), Loopback0,
    NTP and timezone. platform: 'ios-xe' or 'nxos'. mgmt_cidr like
    '192.168.89.184/24'. Node must be DEFINED_ON_CORE or STOPPED; config takes
    effect on next boot from wiped state. The rendered config is returned for
    review. Rendering happens server-side — do NOT regenerate this config
    text yourself."""
    
    username = username or os.environ.get("DAY0_USER", "")
    password = password or os.environ.get("DAY0_PASS", "")
    nxos_hash = os.environ.get("DAY0_PASS_HASH_NXOS", "")
    if not username or not password:
        return {"error": "No day-0 credentials: set DAY0_USER/DAY0_PASS in cml-mcp/.env "
                        "or pass username/password explicitly."}

    try:
        config = render_day0(platform, hostname, mgmt_cidr, gateway, loopback0_ip,
                            username, password, domain, ntp, dns)
    except ValueError as e:
        return {"error": str(e)}
    lab = cml().join_existing_lab(lab_id)
    lab.sync()
    matches = [n for n in lab.nodes() if n.label == node_label]
    if not matches:
        return {"error": f"No node labeled '{node_label}'. Available: {[n.label for n in lab.nodes()]}"}
    node = matches[0]
    if node.state not in ("DEFINED_ON_CORE", "STOPPED"):
        return {"error": f"'{node_label}' is {node.state} — day-0 edits need a non-running node."}
    node.configuration = config
    lab.sync()
    log.info("Applied day-0 to '%s' (%s): mgmt %s, lo0 %s", node_label, platform, mgmt_cidr, loopback0_ip)
    return {"label": node_label, "platform": platform, "config_length": len(config),
            "rendered_config": config}

@mcp.tool()
def wipe_node(lab_id: str, node_label: str, confirm: bool = False) -> dict:
    """Wipe a node's disk so it boots fresh and re-applies its day-0 config.
    DESTROYS the node's disk state (running config, certs, files) — the day-0
    text in the lab definition is what it boots with. Node must be stopped.
    Requires confirm=true; ask the human first."""
    if not confirm:
        return {"error": "Refused: confirm=false. Ask the user to explicitly confirm the wipe."}
    lab = cml().join_existing_lab(lab_id)
    lab.sync()
    matches = [n for n in lab.nodes() if n.label == node_label]
    if not matches:
        return {"error": f"No node labeled '{node_label}'. Available: {[n.label for n in lab.nodes()]}"}
    node = matches[0]
    if node.state not in ("STOPPED", "DEFINED_ON_CORE"):
        return {"error": f"'{node_label}' is {node.state} — stop it first."}
    log.warning("Wiping node '%s' in lab %s", node_label, lab_id)
    node.wipe()
    lab.sync()
    return {"label": node_label, "state": [n for n in lab.nodes() if n.label == node_label][0].state}
@mcp.tool()
def stop_node(lab_id: str, node_label: str) -> dict:
    """Stop a single node (others keep running). Non-blocking; poll with
    check_lab_ready or get_lab for state."""
    lab = cml().join_existing_lab(lab_id)
    lab.sync()
    matches = [n for n in lab.nodes() if n.label == node_label]
    if not matches:
        return {"error": f"No node labeled '{node_label}'. Available: {[n.label for n in lab.nodes()]}"}
    matches[0].stop(wait=False)
    log.info("Stopping node '%s' in lab %s", node_label, lab_id)
    return {"label": node_label, "state": matches[0].state}

@mcp.tool()
def start_node(lab_id: str, node_label: str) -> dict:
    """Start a single node (others unaffected). Non-blocking; poll for BOOTED."""
    lab = cml().join_existing_lab(lab_id)
    lab.sync()
    matches = [n for n in lab.nodes() if n.label == node_label]
    if not matches:
        return {"error": f"No node labeled '{node_label}'. Available: {[n.label for n in lab.nodes()]}"}
    matches[0].start(wait=False)
    log.info("Starting node '%s' in lab %s", node_label, lab_id)
    return {"label": node_label, "state": matches[0].state}

if __name__ == "__main__":
    mcp.run()   # stdio transport (default)
