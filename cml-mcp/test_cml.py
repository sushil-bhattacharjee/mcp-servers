import os, urllib3
urllib3.disable_warnings()
from virl2_client import ClientLibrary

client = ClientLibrary(
    os.environ["CML_URL"],
    os.environ["CML_USER"],
    os.environ["CML_PASS"],
    ssl_verify=False,
)

print("CML version:", client.system_info()["version"])
for lab in client.all_labs():
    print(f"- {lab.id}  {lab.title:30s}  state={lab.state()}  nodes={len(lab.nodes())}")
