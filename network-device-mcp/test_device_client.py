import asyncio, json
from fastmcp import Client

async def main():
    async with Client("device_mcp_server.py") as c:
        tools = await c.list_tools()
        print("TOOLS:", [t.name for t in tools])
        res = await c.call_tool("check_reachability", {"host": "192.168.89.71"})
        print("REACH:", json.dumps(res.data, indent=2))
        res = await c.call_tool("run_show",
            {"host": "192.168.89.71", "platform": "ios-xe", "command": "show version"})
        print("SHOW:", json.dumps(res.data, indent=2)[:600])

asyncio.run(main())
