"""Startet den Server per stdio, listet Tools, ruft antrag_pruefen und kataloge_suchen."""
import asyncio, json
from pathlib import Path
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

async def main():
    p = StdioServerParameters(command="uv", args=["run", "--directory", str(Path(__file__).parent.parent), "mahnantrag-mcp"])
    async with stdio_client(p) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        tools = await s.list_tools()
        print("TOOLS", [t.name for t in tools.tools])
        antrag = json.loads((Path(__file__).parent.parent / "tests/beispiel_antrag.json").read_text())
        res = await s.call_tool("antrag_pruefen", {"antrag": antrag})
        print("PRUEFEN", res.content[0].text[:300])
        res = await s.call_tool("kataloge_suchen", {"katalog": "rechtsform", "suchbegriff": "UG (haft"})
        print("KATALOG", res.content[0].text[:300])
asyncio.run(main())
