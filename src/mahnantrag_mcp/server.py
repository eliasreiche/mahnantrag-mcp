"""MCP-Server: Mahnbescheidsantrag über online-mahnantrag.de vorbereiten.

Ablauf für Claude:
1. kataloge_suchen       -> Anspruchsart, Rechtsform, Belegart, Auslagenart nachschlagen
2. antrag_pruefen        -> deterministische Vorprüfung, Fehler/Warnungen an den Menschen
3. portal_ausfuellen     -> füllt das Portal; hält am Prozessgericht an, falls nicht bestätigt
4. ausfuellen_fortsetzen -> nachdem der Mensch das angezeigte Gericht bestätigt hat
5. Mensch prüft die Datenübersicht (im sichtbaren Browser oder im Rückgabetext)
6. eda_herunterladen     -> nur mit ausdrücklicher Freigabe; speichert die Datei unverändert
7. portal_schliessen

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
from .portal import GerichtBestaetigen, PortalFehler, PortalSitzung
from .pruefung import pruefen

ANWEISUNG = """\
Dieser Server bereitet einen Antrag auf Erlass eines Mahnbescheids über online-mahnantrag.de vor.

Regeln:
- Immer zuerst antrag_pruefen. Fehler dem Menschen zeigen und nicht selbst "wegentscheiden".
- Die Felder in `entscheidungen` sind rechtliche Weichen (Gegenleistung, streitiges Verfahren,
  Vergütung, Einreichung durch Berufsträger, vorgerichtliche Anwaltsvergütung, Verbraucherbeteiligung,
  Prozessgericht). Nie raten oder vorbelegen, immer den Menschen fragen.
- Prozessgericht: portal_ausfuellen hält an und nennt das vom Portal abgeleitete Gericht. Dem Menschen
  zeigen und erklären, dass Weiterklicken als Wahl nach § 35 ZPO gilt. Erst nach seiner Bestätigung
  ausfuellen_fortsetzen mit genau diesem Gerichtsnamen aufrufen.
- Katalognummern und Rechtsform-Codes nur aus kataloge_suchen nehmen.
- Der Firmenname wird mit Rechtsformzusatz eingetragen; Zeilenumbrüche über 35 Zeichen legt der Mensch fest.
- eda_herunterladen erst, nachdem der Mensch die Datenübersicht gesehen und ausdrücklich freigegeben hat.
  Die Freigabe-Parameter nie ohne diese Freigabe setzen.
- Die heruntergeladene Datei nie öffnen, umschreiben oder neu speichern. Sie geht unverändert per beA ans Mahngericht.
- Rechtsanwälte, Behörden und Inkassodienstleister reichen nur elektronisch ein (§ 130d ZPO);
  Barcode nur ausnahmsweise mit Glaubhaftmachung.
"""

mcp = MCPServer("mahnantrag", instructions=ANWEISUNG)
_sitzung: PortalSitzung | None = None


def validierungsfehler_text(e: ValidationError) -> str:
    """Strukturfehler ohne die eingegebenen Werte: die enthalten Mandatsdaten."""
    zeilen = [f"- {'.'.join(str(teil) for teil in fehler['loc'])}: {fehler['msg']}" for fehler in e.errors(include_input=False, include_url=False)]
    return "Antrag unvollständig oder falsch strukturiert:\n" + "\n".join(zeilen)


def _antrag(daten: dict) -> Antrag:
    try:
        return Antrag.model_validate(daten)
    except ValidationError as e:
        raise ToolError(validierungsfehler_text(e)) from None


def _ausgabeordner() -> Path:
    return Path(os.environ.get("MAHNANTRAG_AUSGABE", Path.home() / "Documents" / "Mahnantraege")).expanduser()


async def _angehalten(e: PortalFehler) -> dict:
    """Antwort, wenn der Ausfüller anhält. Der Browser bleibt offen."""
    assert _sitzung
    if isinstance(e, GerichtBestaetigen):
        return {
            "status": "gericht_bestaetigen",
            "prozessgericht_laut_portal": e.gefunden,
            "hinweis": (
                "Das Portal hat dieses Prozessgericht aus der Anschrift des Antragsgegners abgeleitet. "
                "Weiterklicken gilt als Wahl nach § 35 ZPO. Dem Menschen zeigen; nur nach seiner Bestätigung "
                "ausfuellen_fortsetzen(prozessgericht_bestaetigt=<genau dieser Name>) aufrufen. "
                "Eine abweichende Gerichtswahl ist in v0.1 nicht abgebildet."
            ),
            "protokoll": _sitzung.protokoll.schritte,
        }
    maske = None
    try:
        maske = (await _sitzung.zustand()).schluessel
    except Exception:  # noqa: BLE001 – die Maske ist hier nur Zusatzinfo
        pass
    return {
        "status": "angehalten",
        "grund": str(e),
        "maske": maske,
        "protokoll": _sitzung.protokoll.schritte,
        "hinweis": "Browser bleibt offen. Mensch kann übernehmen oder portal_schliessen aufrufen.",
    }


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def kataloge_suchen(katalog: str, suchbegriff: str = "") -> dict:
    """Katalogwerte des Portals nachschlagen.

    katalog: 'anspruchsart' | 'rechtsform' | 'belegart' | 'auslage'
    suchbegriff: Teil des Namens (z. B. 'Kauf', 'GmbH') oder exakter Code; leer = alles.
    """
    if katalog not in kataloge.KATALOGE:
        raise ToolError(f"katalog muss einer von {', '.join(kataloge.KATALOGE)} sein.")
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
    """Füllt online-mahnantrag.de aus und hält an der Datenübersicht an. Es wird nichts eingereicht.

    Haltepunkt Prozessgericht: Ist `entscheidungen.prozessgericht_bestaetigt` leer oder passt es nicht zum
    vom Portal abgeleiteten Gericht, endet der Aufruf mit status 'gericht_bestaetigen'.

    datenschutzhinweis_akzeptiert: Der Mensch hat den Datenschutzhinweis des Portals gelesen und stimmt zu
        (der Ausfüller klickt dort 'Ich stimme zu'). Muss True sein.
    sichtbar: Browserfenster zeigen (empfohlen), damit der Mensch mitlesen und übernehmen kann.
    Die Portal-Sitzung läuft nach ca. 30 Minuten ohne Aktivität ab.
    """
    global _sitzung
    if not datenschutzhinweis_akzeptiert:
        raise ToolError("Ohne Zustimmung zum Datenschutzhinweis des Portals kann nicht ausgefüllt werden.")
    antrag_obj = _antrag(antrag)
    bericht = pruefen(antrag_obj)
    if not bericht.zulaessig:
        return {"status": "abgelehnt", "pruefung": bericht.als_dict()}
    if _sitzung:
        await _sitzung.schliessen()
    _sitzung = PortalSitzung()
    try:
        ergebnis = await _sitzung.ausfuellen(antrag_obj, sichtbar=sichtbar)
    except PortalFehler as e:
        return await _angehalten(e)
    ergebnis["pruefung"] = bericht.als_dict()
    return ergebnis


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
async def ausfuellen_fortsetzen(prozessgericht_bestaetigt: str) -> dict:
    """Nach status 'gericht_bestaetigen': das vom Menschen bestätigte Prozessgericht übernehmen und
    bis zur Datenübersicht weiterfüllen. Der Name muss genau dem angezeigten Gericht entsprechen."""
    if not _sitzung or not _sitzung.page:
        raise ToolError("Keine offene Portal-Sitzung. Zuerst portal_ausfuellen.")
    if not prozessgericht_bestaetigt.strip():
        raise ToolError("Bitte das vom Menschen bestätigte Prozessgericht angeben.")
    try:
        return await _sitzung.fortsetzen(prozessgericht_bestaetigt)
    except PortalFehler as e:
        return await _angehalten(e)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True))
async def eda_herunterladen(uebersicht_vom_menschen_freigegeben: bool) -> dict:
    """EDA-Datei aus der offenen Portal-Sitzung herunterladen (nur Versandart EDA-Download).

    Nur aufrufen, wenn der Mensch die Datenübersicht gesehen und ausdrücklich freigegeben hat.
    Gesperrt, wenn das Portal Fehler meldet (FehlerDa) oder nicht freigegebene Warnungen offen sind.
    Die Datei wird schreibgeschützt unter ihrem Portal-Namen gespeichert und gehasht, aber nie verändert.
    Zielordner: Umgebungsvariable MAHNANTRAG_AUSGABE, sonst ~/Documents/Mahnantraege.
    (destructiveHint, damit Clients vor dem Aufruf beim Menschen nachfragen.)
    """
    if not uebersicht_vom_menschen_freigegeben:
        raise ToolError("Erst die Datenübersicht vom Menschen freigeben lassen.")
    if not _sitzung or not _sitzung.page:
        raise ToolError("Keine offene Portal-Sitzung. Zuerst portal_ausfuellen.")
    try:
        return await _sitzung.eda_herunterladen(_ausgabeordner())
    except PortalFehler as e:
        raise ToolError(str(e)) from None


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def portal_status() -> dict:
    """Aktuelle Maske der offenen Portal-Sitzung, Minuten seit der letzten Aktivität und Protokoll."""
    if not _sitzung or not _sitzung.page:
        return {"offen": False}
    z = await _sitzung.zustand()
    minuten = _sitzung.minuten_seit_aktivitaet()
    return {
        "offen": True,
        "maske": z.schluessel,
        "minuten_seit_aktivitaet": round(minuten, 1) if minuten is not None else None,
        "sitzung_vermutlich_abgelaufen": bool(minuten and minuten > 28) or z.formular == "Bundesland",
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
