"""Probelauf gegen das echte Portal. NUR MIT FANTASIEDATEN.

uv run python scripts/live_probelauf.py ANTRAG.json [--sichtbar] [--gericht-bestaetigen] [--download ZIELORDNER]

--gericht-bestaetigen  am Haltepunkt Prozessgericht das angezeigte Gericht übernehmen (nur für Tests!)
--download             EDA-Datei herunterladen; ohne den Schalter wird nichts heruntergeladen
"""
import asyncio
import json
import sys
from pathlib import Path

from mahnantrag_mcp.modell import Antrag
from mahnantrag_mcp.portal import GerichtBestaetigen, PortalFehler, PortalSitzung
from mahnantrag_mcp.pruefung import pruefen


async def main():
    antrag = Antrag.model_validate(json.load(open(sys.argv[1])))
    bericht = pruefen(antrag)
    print("PRUEFUNG", json.dumps(bericht.als_dict(), ensure_ascii=False, indent=1))
    if not bericht.zulaessig:
        return
    sitzung = PortalSitzung()
    try:
        try:
            ergebnis = await sitzung.ausfuellen(antrag, sichtbar="--sichtbar" in sys.argv)
        except GerichtBestaetigen as e:
            print("HALTEPUNKT GERICHT:", e)
            if "--gericht-bestaetigen" not in sys.argv:
                return
            ergebnis = await sitzung.fortsetzen(e.gefunden)
        print(json.dumps({k: v for k, v in ergebnis.items() if k not in ("uebersicht", "protokoll")}, ensure_ascii=False, indent=1))
        print("----- UEBERSICHT\n" + ergebnis["uebersicht"][:1500])
        if "--download" in sys.argv:
            ziel = Path(sys.argv[sys.argv.index("--download") + 1])
            print("----- DOWNLOAD\n" + json.dumps(await sitzung.eda_herunterladen(ziel), ensure_ascii=False, indent=1))
    except PortalFehler as e:
        print("ANGEHALTEN:", e)
        print("\n".join(sitzung.protokoll.schritte[-8:]))
    finally:
        print("PROTOKOLL-ENDE:", *sitzung.protokoll.schritte[-4:], sep="\n  ")
        await sitzung.schliessen()


asyncio.run(main())
