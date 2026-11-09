"""Probelauf gegen das echte Portal bis zur Datenübersicht. Lädt NICHTS herunter.
uv run python scripts/live_probelauf.py tests/beispiel_antrag.json [--sichtbar]"""
import asyncio, json, sys
from mahnantrag_mcp.modell import Antrag
from mahnantrag_mcp.portal import PortalFehler, PortalSitzung
from mahnantrag_mcp.pruefung import pruefen

async def main():
    a = Antrag.model_validate(json.load(open(sys.argv[1])))
    b = pruefen(a); print("PRUEFUNG", json.dumps(b.als_dict(), ensure_ascii=False, indent=1))
    if not b.zulaessig: return
    s = PortalSitzung()
    try:
        r = await s.ausfuellen(a, sichtbar="--sichtbar" in sys.argv)
        print(json.dumps({k: v for k, v in r.items() if k != "uebersicht"}, ensure_ascii=False, indent=1))
        print("----- UEBERSICHT\n" + r["uebersicht"])
    except PortalFehler as e:
        print("ANGEHALTEN:", e)
        print("\n".join(s.protokoll.schritte))
        try:
            z = await s.zustand(); print("MASKE", z.schluessel); print(z.text[:1500])
        except Exception as x: print("kein Zustand", x)
    finally:
        await s.schliessen()
asyncio.run(main())
