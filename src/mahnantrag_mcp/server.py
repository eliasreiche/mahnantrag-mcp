"""MCP-Server: Mahnbescheidsantrag über online-mahnantrag.de vorbereiten.

Ablauf für Claude:
1. kataloge_suchen    -> Anspruchsart, Rechtsform, Belegart, Auslagenart nachschlagen
2. antrag_pruefen     -> deterministische Vorprüfung, Fehler/Warnungen an den Menschen
3. portal_ausfuellen  -> füllt das Portal bis zur Datenübersicht und hält dort an
4. Mensch prüft die Übersicht (im sichtbaren Browser oder im Rückgabetext)
5. eda_herunterladen  -> nur mit ausdrücklicher Bestätigung; speichert die Datei unverändert
6. portal_schliessen

Eingereicht wird nie durch diesen Server. Die EDA-Datei schickt der Mensch über beA.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import ValidationError

from . import kataloge
from .modell import Antrag
from .portal import PortalFehler, PortalSitzung
from .pruefung import pruefen

ANWEISUNG = """\
Dieser Server bereitet einen Antrag auf Erlass eines Mahnbescheids über online-mahnantrag.de vor.

Regeln:
- Immer zuerst antrag_pruefen. Fehler dem Menschen zeigen und nicht selbst "wegentscheiden".
- Die Felder in `entscheidungen` sind rechtliche Weichen (Gegenleistung, streitiges Verfahren,
  Vergütung, Gerichtsstand). Nie raten oder vorbelegen, immer den Menschen fragen.
- Katalognummern und Rechtsform-Codes nur aus kataloge_suchen nehmen.
- Der Firmenname wird mit Rechtsformzusatz eingetragen; Zeilenumbrüche über 35 Zeichen legt der Mensch fest.
- eda_herunterladen erst, nachdem der Mensch die Datenübersicht gesehen und freigegeben hat.
- Die heruntergeladene Datei nie öffnen, umschreiben oder neu speichern. Sie geht unverändert per beA ans Mahngericht.
- Rechtsanwälte reichen nur elektronisch ein (§ 130d ZPO); Barcode nur ausnahmsweise mit Glaubhaftmachung.
"""

mcp = MCPServer("mahnantrag", instructions=ANWEISUNG)
_sitzung: PortalSitzung | None = None


def _antrag(daten: dict) -> Antrag:
    try:
        return Antrag.model_validate(daten)
    except ValidationError as e:
        raise ToolError("Antrag unvollständig oder falsch strukturiert:\n" + str(e)) from e


def _ausgabeordner() -> Path:
    return Path(os.environ.get("MAHNANTRAG_AUSGABE", Path.home() / "Documents" / "Mahnantraege")).expanduser()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def kataloge_suchen(katalog: str, suchbegriff: str = "") -> dict:
    """Katalogwerte des Portals nachschlagen.

    katalog: 'anspruchsart' | 'rechtsform' | 'belegart' | 'auslage'
    suchbegriff: Teil des Namens (z. B. 'Kauf', 'GmbH') oder exakter Code; leer = alles.
    """
    if katalog not in ("anspruchsart", "rechtsform", "belegart", "auslage"):
        raise ToolError("katalog muss 'anspruchsart', 'rechtsform', 'belegart' oder 'auslage' sein.")
    treffer = kataloge.suchen(katalog, suchbegriff)
    return {"anzahl": len(treffer), "treffer": treffer}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def antrag_schema() -> dict:
    """JSON-Schema des Antrags (Felder, Pflichtangaben, Beschreibungen)."""
    return Antrag.model_json_schema()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def antrag_pruefen(antrag: dict) -> dict:
    """Antrag deterministisch vorprüfen (Feldlängen, Kataloge, PLZ, IBAN, doppelte Anwaltsvergütung,
    § 130d ZPO, § 288 BGB, Pflicht-Entscheidungen). Schreibt nichts, öffnet keinen Browser."""
    return pruefen(_antrag(antrag)).als_dict()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
async def portal_ausfuellen(antrag: dict, datenschutzhinweis_akzeptiert: bool, sichtbar: bool = True) -> dict:
    """Füllt online-mahnantrag.de bis zur Datenübersicht aus und hält dort an. Es wird nichts eingereicht.

    datenschutzhinweis_akzeptiert: Der Mensch hat den Datenschutzhinweis des Portals gelesen und stimmt zu
        (der Ausfüller klickt dort 'Ich stimme zu'). Muss True sein.
    sichtbar: Browserfenster zeigen (empfohlen), damit der Mensch mitlesen und übernehmen kann.
    Die Portal-Sitzung läuft nach ca. 30 Minuten ohne Aktivität ab.
    """
    global _sitzung
    if not datenschutzhinweis_akzeptiert:
        raise ToolError("Ohne Zustimmung zum Datenschutzhinweis des Portals kann nicht ausgefüllt werden.")
    a = _antrag(antrag)
    bericht = pruefen(a)
    if not bericht.zulaessig:
        return {"status": "abgelehnt", "pruefung": bericht.als_dict()}
    if _sitzung:
        await _sitzung.schliessen()
    _sitzung = PortalSitzung()
    try:
        ergebnis = await _sitzung.ausfuellen(a, sichtbar=sichtbar)
    except PortalFehler as e:
        z = None
        try:
            z = await _sitzung.zustand()
        except Exception:
            pass
        return {
            "status": "angehalten",
            "grund": str(e),
            "maske": z.schluessel if z else None,
            "protokoll": _sitzung.protokoll.schritte,
            "hinweis": "Browser bleibt offen. Mensch kann übernehmen oder portal_schliessen aufrufen.",
        }
    ergebnis["pruefung"] = bericht.als_dict()
    return ergebnis


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
async def eda_herunterladen(uebersicht_vom_menschen_freigegeben: bool) -> dict:
    """EDA-Datei aus der offenen Portal-Sitzung herunterladen (nur Versandart EDA-Download).

    Nur aufrufen, wenn der Mensch die Datenübersicht ausdrücklich freigegeben hat.
    Die Datei wird schreibgeschützt gespeichert und gehasht, aber nie verändert.
    Zielordner: Umgebungsvariable MAHNANTRAG_AUSGABE, sonst ~/Documents/Mahnantraege.
    """
    if not uebersicht_vom_menschen_freigegeben:
        raise ToolError("Erst die Datenübersicht vom Menschen freigeben lassen.")
    if not _sitzung or not _sitzung.page:
        raise ToolError("Keine offene Portal-Sitzung. Zuerst portal_ausfuellen.")
    try:
        return await _sitzung.eda_herunterladen(_ausgabeordner())
    except PortalFehler as e:
        raise ToolError(str(e)) from e


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def portal_status() -> dict:
    """Aktuelle Maske der offenen Portal-Sitzung und Protokoll."""
    if not _sitzung or not _sitzung.page:
        return {"offen": False}
    z = await _sitzung.zustand()
    return {
        "offen": True,
        "maske": z.schluessel,
        "seit": _sitzung.gestartet.isoformat() if _sitzung.gestartet else None,
        "warnungen": z.warnungen,
        "protokoll": _sitzung.protokoll.schritte[-15:],
    }


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False))
async def portal_schliessen() -> dict:
    """Browser schließen. Nicht heruntergeladene Eingaben im Portal gehen verloren."""
    global _sitzung
    if _sitzung:
        await _sitzung.schliessen()
        _sitzung = None
    return {"geschlossen": True}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
