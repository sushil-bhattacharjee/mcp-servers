"""network-device-mcp — v0.4: + routing, verification and ACL tools (Netmiko)."""
import os
import sys
import logging
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import FastMCP
from netmiko import ConnectHandler
from platforms import PLATFORMS

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s device-mcp %(levelname)s %(message)s",
)
log = logging.getLogger("device-mcp")
load_dotenv(Path(__file__).parent / ".env")

mcp = FastMCP("netdev")

def _connect(host: str, platform: str):
    """Open a Netmiko session. Returns (conn, None) or (None, error_dict)."""
    drv = PLATFORMS.get(platform)
    if drv is None:
        return None, {"error": f"Unknown platform '{platform}'. Supported: {list(PLATFORMS)}"}
    user = os.environ.get("DEVICE_USER")
    pw = os.environ.get("DEVICE_PASS")
    if not user or not pw:
        return None, {"error": "DEVICE_USER/DEVICE_PASS not set — check network-device-mcp/.env"}
    try:
        conn = ConnectHandler(
            device_type=drv.NETMIKO_DEVICE_TYPE,
            host=host,
            username=user,
            password=pw,
            timeout=15,
            fast_cli=False,
        )
        return conn, None
    except Exception as e:
        return None, {"error": f"SSH connection to {host} failed: {e}"}

def _send_config_impl(host: str, platform: str, commands: list[str]) -> dict:
    conn, err = _connect(host, platform)
    if err:
        return err
    try:
        output = conn.send_config_set(commands)
        log.warning("send_config %s@%s: %d commands", platform, host, len(commands))
        _err_markers = ("% ", "error", "invalid", "overlap", "cannot", "failed", "denied")
        rejected = [l for l in output.splitlines()
                    if any(m in l.lower() for m in _err_markers) or l.strip().startswith("%")]
        return {"host": host, "commands_sent": len(commands), "echo": output,
                "rejected_lines": rejected}
    finally:
        conn.disconnect()

def _run_show_impl(host: str, platform: str, command: str) -> dict:
    conn, err = _connect(host, platform)
    if err:
        return err
    try:
        output = conn.send_command(command)
        log.info("run_show %s@%s: %s", platform, host, command)
        return {"host": host, "command": command, "output": output}
    finally:
        conn.disconnect()

@mcp.tool()
def check_reachability(host: str) -> dict:
    """Test whether a device answers on SSH (TCP 22). Use after booting a lab
    (CML nodes can be BOOTED but still initializing SSH for another minute)."""
    import socket
    try:
        with socket.create_connection((host, 22), timeout=5):
            return {"host": host, "ssh_reachable": True}
    except OSError as e:
        return {"host": host, "ssh_reachable": False, "detail": str(e)}

@mcp.tool()
def run_show(host: str, platform: str, command: str) -> dict:
    """Run a single read-only 'show' command on a device and return raw output.
    platform: 'ios-xe' or 'nxos'. Refuses non-show commands — use the config
    tools for changes."""
    if not command.strip().lower().startswith("show"):
        return {"error": "Only 'show' commands allowed here. Use config tools for changes."}
    return _run_show_impl(host, platform, command)

@mcp.tool()
def get_running_config(host: str, platform: str, section: str = "") -> dict:
    """Get a device's running configuration. Optional section filter, e.g.
    section='router bgp' returns only that block. Empty section = full config
    (can be large — prefer a section when you know what you need)."""
    conn, err = _connect(host, platform)
    if err:
        return err
    try:
        drv = PLATFORMS[platform]
        cmd = drv.config_section_command(section) if section else "show running-config"
        output = conn.send_command(cmd, read_timeout=60)
        log.info("get_running_config %s@%s section='%s' (%d chars)", platform, host, section, len(output))
        return {"host": host, "section": section or "(full)", "config": output}
    finally:
        conn.disconnect()
@mcp.tool()
def send_config(host: str, platform: str, commands: list[str]) -> dict:
    """Push configuration commands to a device (enters config mode, applies in
    order, exits). Returns the device's echo — READ IT: lines containing
    '% Invalid' or 'ERROR' mean a command was rejected. For interfaces, OSPF
    and BGP prefer the structured configure_* tools; use this for everything
    else (ACLs, static routes, features). Does NOT save to startup-config —
    use save_config when the change is verified."""
    return _send_config_impl(host, platform, commands)

@mcp.tool()
def configure_interface(host: str, platform: str, interface: str, ip: str,
                        mask: str, description: str = "") -> dict:
    """Configure an interface with an IPv4 address and enable it. Works for
    physical interfaces and loopbacks (creates the loopback if absent).
    interface must be a full name, e.g. 'Loopback0', 'GigabitEthernet2',
    'Ethernet1/1'. mask in dotted form, e.g. '255.255.255.0'."""
    drv = PLATFORMS.get(platform)
    if drv is None:
        return {"error": f"Unknown platform '{platform}'. Supported: {list(PLATFORMS)}"}
    commands = drv.render_interface(interface, ip, mask, description)
    result = _send_config_impl(host, platform, commands)
    if "error" in result:
        return result
    verify = _run_show_impl(host, platform, f"show ip interface brief | include {interface}")
    result["verification"] = verify.get("output", verify.get("error"))
    return result

@mcp.tool()
def save_config(host: str, platform: str) -> dict:
    """Save running-config to startup-config (copy run start). Call after
    changes are verified working — not before."""
    conn, err = _connect(host, platform)
    if err:
        return err
    try:
        output = conn.save_config()
        log.warning("save_config %s@%s", platform, host)
        return {"host": host, "saved": True, "echo": output[-300:]}
    finally:
        conn.disconnect()

@mcp.tool()
def configure_ospf(host: str, platform: str, process_id: int, router_id: str,
                   area: str, interfaces: list[str]) -> dict:
    """Enable OSPF (interface mode) on a device: creates the process with the
    given router-id and puts each listed interface into the given area. Use
    FULL interface names. On nxos, 'feature ospf' is enabled automatically.
    Adjacencies take up to ~40s to reach FULL — verify with
    check_ospf_neighbors afterwards, don't assume."""
    drv = PLATFORMS.get(platform)
    if drv is None:
        return {"error": f"Unknown platform '{platform}'. Supported: {list(PLATFORMS)}"}
    commands = drv.render_ospf(process_id, router_id, area, interfaces)
    result = _send_config_impl(host, platform, commands)
    log.warning("configure_ospf %s@%s pid=%s area=%s ifaces=%s", platform, host,
                process_id, area, interfaces)
    return result

@mcp.tool()
def configure_bgp(host: str, platform: str, asn: int, router_id: str,
                  neighbors: list[dict], networks: list[str] = []) -> dict:
    """Configure BGP: local ASN, router-id, neighbors and optional networks to
    advertise (CIDR strings). Each neighbor dict: {"ip": "...", "remote_as": N}
    plus optional "update_source" (e.g. "Loopback0") and "ebgp_multihop" (int).
    On nxos, 'feature bgp' is enabled automatically. Sessions take seconds to
    establish — verify with check_bgp_neighbors afterwards, don't assume."""
    drv = PLATFORMS.get(platform)
    if drv is None:
        return {"error": f"Unknown platform '{platform}'. Supported: {list(PLATFORMS)}"}
    for n in neighbors:
        if "ip" not in n or "remote_as" not in n:
            return {"error": f"Neighbor missing ip/remote_as: {n}"}
    commands = drv.render_bgp(asn, router_id, neighbors, networks)
    result = _send_config_impl(host, platform, commands)
    log.warning("configure_bgp %s@%s asn=%s neighbors=%s", platform, host, asn,
                [n["ip"] for n in neighbors])
    return result

@mcp.tool()
def check_ospf_neighbors(host: str, platform: str) -> dict:
    """Show parsed OSPF neighbors: neighbor_id, state, address, interface.
    Healthy adjacency = state contains FULL. Empty list = no adjacencies."""
    drv = PLATFORMS.get(platform)
    if drv is None:
        return {"error": f"Unknown platform '{platform}'. Supported: {list(PLATFORMS)}"}
    res = _run_show_impl(host, platform, drv.SHOW_OSPF_NEIGHBORS)
    if "error" in res:
        return res
    neighbors = drv.parse_ospf_neighbors(res["output"])
    full = [n for n in neighbors if "FULL" in n["state"].upper()]
    return {"host": host, "neighbors": neighbors, "full_count": len(full),
            "raw": res["output"]}

@mcp.tool()
def check_bgp_neighbors(host: str, platform: str) -> dict:
    """Show parsed BGP summary: neighbor, remote_as, established (bool), state.
    established=true means the session is up and exchanging prefixes."""
    drv = PLATFORMS.get(platform)
    if drv is None:
        return {"error": f"Unknown platform '{platform}'. Supported: {list(PLATFORMS)}"}
    res = _run_show_impl(host, platform, drv.SHOW_BGP_SUMMARY)
    if "error" in res:
        return res
    neighbors = drv.parse_bgp_summary(res["output"])
    return {"host": host, "neighbors": neighbors,
            "established_count": len([n for n in neighbors if n["established"]]),
            "raw": res["output"]}

@mcp.tool()
def verify_day0(host: str, platform: str) -> dict:
    """One-call day-0 audit on a live device: SSH login (implicit), hostname,
    Loopback0 present, and programmability stack (restconf/netconf; nxapi on
    nxos). Returns pass/fail per item — the post-boot acceptance gate."""
    drv = PLATFORMS.get(platform)
    if drv is None:
        return {"error": f"Unknown platform '{platform}'. Supported: {list(PLATFORMS)}"}
    checks = {}
    r = _run_show_impl(host, platform, "show hostname" if platform == "nxos"
                    else "show running-config | include ^hostname")
    if "error" in r:
        return {"host": host, "ssh_login": False, "detail": r["error"]}
    checks["ssh_login"] = True
    checks["hostname"] = r["output"].strip()
    if platform == "ios-xe":
        r = _run_show_impl(host, platform, "show running-config | include restconf|netconf")
        out = r.get("output", "")
        checks["restconf"] = "restconf" in out
        checks["netconf_yang"] = "netconf-yang" in out
    else:
        r = _run_show_impl(host, platform, "show feature | include netconf|restconf|nxapi")
        out = r.get("output", "").lower()
        checks["restconf"] = "restconf" in out and "enabled" in out
        checks["netconf"] = "netconf" in out
        checks["nxapi"] = "nxapi" in out
    r = _run_show_impl(host, platform, "show ip interface brief | include Loopback0"
                    if platform == "ios-xe" else "show interface loopback0 brief")
    checks["loopback0"] = bool(r.get("output", "").strip()) and "error" not in r
    checks["all_pass"] = all(v for k, v in checks.items() if isinstance(v, bool))
    return {"host": host, "platform": platform, **checks}

@mcp.tool()
def configure_acl(host: str, platform: str, acl_type: str, name: str,
                rules: list[str], replace: bool = False) -> dict:
    """Create or extend an IPv4 ACL. acl_type: 'standard' or 'extended'
    (ios-xe only distinction; nxos ACLs are all extended-style — pass
    'extended'). Each rule is one native ACE line WITHOUT the acl header,
    e.g. '10 permit 10.10.10.0' (standard) or
    '10 permit tcp any gt 100 203.36.36.32 0.0.0.15 eq 636' (extended).
    Include sequence numbers. replace=true deletes the ACL first (atomic
    redefine); replace=false appends to an existing ACL.
    Verification (the resulting ACL) is included in the response.
    NOTE: this defines the ACL only — applying it to interfaces/vty/RESTCONF
    is a separate step via send_config or apply_acl."""
    drv = PLATFORMS.get(platform)
    if drv is None:
        return {"error": f"Unknown platform '{platform}'. Supported: {list(PLATFORMS)}"}
    if platform == "ios-xe" and acl_type not in ("standard", "extended"):
        return {"error": "acl_type must be 'standard' or 'extended'"}
    commands = []
    if platform == "ios-xe":
        header = f"ip access-list {acl_type} {name}"
    else:
        header = f"ip access-list {name}"
    commands = ([f"no {header}"] if replace else []) + [header] + [f" {r.strip()}" for r in rules]
    result = _send_config_impl(host, platform, commands)
    if "error" in result:
        return result
    log.warning("configure_acl %s@%s %s '%s' (%d rules, replace=%s)",
                platform, host, acl_type, name, len(rules), replace)
    verify_cmd = (f"show ip access-lists {name}" if platform == "ios-xe"
                else f"show ip access-lists {name}")
    verify = _run_show_impl(host, platform, verify_cmd)
    result["verification"] = verify.get("output", verify.get("error"))
    return result

@mcp.tool()
def apply_acl(host: str, platform: str, name: str, interface: str,
            direction: str) -> dict:
    """Apply an existing ACL to an interface. direction: 'in' or 'out'.
    For vty/line or restconf/netconf ACL application use send_config instead
    (platform syntax varies). Verification included."""
    drv = PLATFORMS.get(platform)
    if drv is None:
        return {"error": f"Unknown platform '{platform}'. Supported: {list(PLATFORMS)}"}
    if direction not in ("in", "out"):
        return {"error": "direction must be 'in' or 'out'"}
    if platform == "ios-xe":
        commands = [f"interface {interface}", f" ip access-group {name} {direction}"]
    else:
        commands = [f"interface {interface}", f" ip access-group {name} {direction}"]
    result = _send_config_impl(host, platform, commands)
    if "error" in result:
        return result
    log.warning("apply_acl %s@%s '%s' -> %s %s", platform, host, name, interface, direction)
    verify = _run_show_impl(host, platform, f"show running-config interface {interface}")
    result["verification"] = verify.get("output", verify.get("error"))
    return result

if __name__ == "__main__":
    mcp.run()
