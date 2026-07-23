"""Day-0 bootstrap templates — sourced from proven cat8Kv71/nx9K73 configs."""
import ipaddress
from jinja2 import Template

IOSXE_DAY0 = Template("""hostname {{ hostname }}
!
aaa new-model
aaa authentication login default local
aaa authorization exec default local
aaa session-id common
login on-success log
!
username {{ username }} privilege 15 secret 0 {{ password }}
!
ip domain name {{ domain }}
{% if dns %}ip name-server {{ dns }}
{% endif %}clock timezone AEDT 11 0
service timestamps debug datetime msec
service timestamps log datetime msec
no logging console
!
ip ssh version 2
ip scp server enable
!
ip http server
ip http authentication local
ip http secure-server
restconf
netconf-yang
netconf ssh
!
interface Loopback0
 ip address {{ loopback0_ip }} 255.255.255.255
!
interface GigabitEthernet1
 description MGMT
 ip address {{ mgmt_ip }} {{ mgmt_mask }}
 no shutdown
!
ip route 0.0.0.0 0.0.0.0 {{ gateway }}
{% if ntp %}ntp server {{ ntp }}
{% endif %}!
line con 0
 exec-timeout 0 0
 stopbits 1
line vty 0 15
 exec-timeout 0 0
 transport input ssh
!
end
""")

NXOS_DAY0 = Template("""hostname {{ hostname }}
feature nxapi
feature scp-server
feature sftp-server
feature netconf
feature restconf
no password strength-check
username {{ username }} password 5 {{ nxos_hash }} role network-admin
ip domain-name {{ domain }}
clock timezone AEDT 11 0
no logging console
copp profile strict
vrf context management
  ip route 0.0.0.0/0 {{ gateway }}
interface mgmt0
  vrf member management
  ip address {{ mgmt_ip }}/{{ mgmt_prefixlen }}
  no shutdown
interface loopback0
  ip address {{ loopback0_ip }}/32
{% if ntp %}ntp server {{ ntp }} use-vrf management
ntp source-interface mgmt0
{% endif %}nxapi http port 80
netconf idle-timeout 1440
netconf sessions 10
line console
  exec-timeout 0
line vty
  exec-timeout 0
""")

def render_day0(platform: str, hostname: str, mgmt_cidr: str, gateway: str,
                loopback0_ip: str, username: str, password: str,
                domain: str, ntp: str, dns: str) -> str:
    iface = ipaddress.ip_interface(mgmt_cidr)   # accepts '192.168.89.184/24'
    ctx = dict(hostname=hostname, gateway=gateway, loopback0_ip=loopback0_ip,
               username=username, password=password, domain=domain, ntp=ntp, dns=dns,
               mgmt_ip=str(iface.ip), mgmt_mask=str(iface.network.netmask),
               mgmt_prefixlen=iface.network.prefixlen)
    if platform == "ios-xe":
        return IOSXE_DAY0.render(**ctx)
    if platform == "nxos":
        if not ctx["nxos_hash"]:
            raise ValueError("nxos day-0 needs a type-5 password hash (DAY0_PASS_HASH_NXOS)")
        return NXOS_DAY0.render(**ctx)
    raise ValueError(f"Unknown platform '{platform}' (use 'ios-xe' or 'nxos')")
