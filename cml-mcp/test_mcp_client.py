import asyncio, json
from fastmcp import Client

async def main():
    async with Client("cml_mcp_server.py") as c:
        tools = await c.list_tools()
        print("TOOLS:", [t.name for t in tools])
        res = await c.call_tool("list_labs", {})
        print("RESULT:", json.dumps(res.data, indent=2, default=str))

asyncio.run(main())
