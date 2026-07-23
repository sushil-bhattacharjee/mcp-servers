"""IOS-XE platform driver: Netmiko device_type + command semantics."""

import ipaddress
import re


NETMIKO_DEVICE_TYPE = "cisco_xe"

SHOW_VERSION = "show version"
SHOW_OSPF_NEIGHBORS = "show ip ospf neighbor"
SHOW_BGP_SUMMARY = "show ip bgp summary"

def config_section_command(section: str) -> str:
    return f"show running-config | section {section}"

def render_interface(interface: str, ip: str, mask: str, description: str = "") -> list[str]:
    cmds = [f"interface {interface}"]
    if description:
        cmds.append(f" description {description}")
    cmds.append(f" ip address {ip} {mask}")
    cmds.append(" no shutdown")
    return cmds

def render_ospf(process_id: int, router_id: str, area: str, interfaces: list[str]) -> list[str]:
    cmds = [f"router ospf {process_id}", f" router-id {router_id}"]
    for i in interfaces:
        cmds += [f"interface {i}", f" ip ospf {process_id} area {area}"]
    return cmds

def render_bgp(asn: int, router_id: str, neighbors: list[dict], networks: list[str]) -> list[str]:
    cmds = [f"router bgp {asn}", f" bgp router-id {router_id}", " bgp log-neighbor-changes"]
    for n in neighbors:
        cmds.append(f" neighbor {n['ip']} remote-as {n['remote_as']}")
        if n.get("update_source"):
            cmds.append(f" neighbor {n['ip']} update-source {n['update_source']}")
        if n.get("ebgp_multihop"):
            cmds.append(f" neighbor {n['ip']} ebgp-multihop {n['ebgp_multihop']}")
    cmds.append(" address-family ipv4")
    for net in networks:
        i = ipaddress.ip_network(net, strict=False)
        cmds.append(f"  network {i.network_address} mask {i.netmask}")
    for n in neighbors:
        cmds.append(f"  neighbor {n['ip']} activate")
    cmds.append(" exit-address-family")
    return cmds

def parse_ospf_neighbors(output: str) -> list[dict]:
    """Parse 'show ip ospf neighbor'. Handles both broadcast (FULL/DR) and
    point-to-point (FULL/  -) state formats — the p2p state contains a space,
    so the state field is matched non-greedily rather than as a single token."""
    out = []
    for line in output.splitlines():
        m = re.match(r"^\s*(\d+\.\d+\.\d+\.\d+)\s+(\d+)\s+(.+?)\s+(\S+)\s+(\d+\.\d+\.\d+\.\d+)\s+(\S+)\s*$", line)
        if m:
            out.append({"neighbor_id": m.group(1), "state": m.group(3).strip(),
                        "address": m.group(5), "interface": m.group(6)})
    return out

def parse_bgp_summary(output: str) -> list[dict]:
    out = []
    for line in output.splitlines():
        m = re.match(r"^(\d+\.\d+\.\d+\.\d+)\s+\d+\s+(\d+)\s+.*\s(\S+)\s*$", line)
        if m:
            last = m.group(3)
            established = last.isdigit()
            out.append({"neighbor": m.group(1), "remote_as": int(m.group(2)),
                        "established": established,
                        "state": f"Established ({last} pfx)" if established else last})
    return out
