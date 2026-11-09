"""Sicherheits- und Freigabesperren, offline getestet (ohne Browser, ohne Portal)."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

from mahnantrag_mcp import server
from mahnantrag_mcp.modell import Antrag
from mahnantrag_mcp.portal import (
    MASKEN,
    MASKEN_NACH_FORMULAR,
    WARNUNG_VORGERICHTLICH,
    dialog_erlaubt,
    download_sperrgrund,
    gericht_passt,
    prozessgericht_aus_text,
    unbekannte_warnungen,
)

BEISPIEL = json.loads((Path(__file__).parent / "beispiel_antrag.json").read_text())
UEBERSICHT = ("MBUebersicht", "saveMBAntragUebersicht")


# --- Server-Sperren ------------------------------------------------------------------
async def test_ausfuellen_ohne_datenschutz_zustimmung_gesperrt():
    with pytest.raises(ToolError, match="Datenschutzhinweis"):
        await server.portal_ausfuellen(BEISPIEL, datenschutzhinweis_akzeptiert=False)


async def test_ausfuellen_mit_pruefungsfehler_oeffnet_keinen_browser():
    d = deepcopy(BEISPIEL)
    d["antragsgegner"]["adresse"]["plz"] = "1043"
    ergebnis = await server.portal_ausfuellen(d, datenschutzhinweis_akzeptiert=True)
    assert ergebnis["status"] == "abgelehnt"
    assert server._sitzung is None


async def test_download_ohne_freigabe_gesperrt():
    with pytest.raises(ToolError, match="freigeben"):
        await server.eda_herunterladen(uebersicht_vom_menschen_freigegeben=False)


async def test_download_ohne_sitzung_gesperrt():
    with pytest.raises(ToolError, match="Keine offene Portal-Sitzung"):
        await server.eda_herunterladen(uebersicht_vom_menschen_freigegeben=True)


async def test_fortsetzen_ohne_sitzung_gesperrt():
    with pytest.raises(ToolError, match="Keine offene Portal-Sitzung"):
        await server.ausfuellen_fortsetzen("Amtsgericht München")


def test_validierungsfehler_ohne_mandatsdaten():
    d = deepcopy(BEISPIEL)
    d["antragsgegner"]["name_zeilen"] = "Geheime Mandantin GmbH"  # falscher Typ: str statt Liste
    with pytest.raises(ValidationError) as info:
        Antrag.model_validate(d)
    text = server.validierungsfehler_text(info.value)
    assert "Geheime Mandantin" not in text
    assert "antragsgegner" in text


def test_kataloge_suchen_unbekannter_katalog():
    with pytest.raises(ToolError):
        server.kataloge_suchen("gibtsnicht")


# --- Warnungen und Dialoge -----------------------------------------------------------
def test_unbekannte_warnung_wird_nicht_quittiert():
    w = ["Warnung: Bitte prüfen Sie etwas völlig Neues."]
    assert unbekannte_warnungen(w, [WARNUNG_VORGERICHTLICH]) == w


def test_bekannte_warnung_nur_wenn_freigegeben():
    w = [f"Warnung: Bitte überprüfen Sie Ihre Eingabe, {WARNUNG_VORGERICHTLICH}."]
    assert unbekannte_warnungen(w, [WARNUNG_VORGERICHTLICH]) == []
    assert unbekannte_warnungen(w, []) == w  # ohne Freigabe aus der Vorprüfung: nicht quittieren


def test_nur_bekannte_dialoge_werden_bestaetigt():
    assert dialog_erlaubt("Bitte lesen Sie die Hinweise zum EDA-Download und bestätigen Sie die Kenntnisnahme")
    assert not dialog_erlaubt("Wollen Sie wirklich wechseln? Alle Daten gehen verloren.")


# --- Download-Sperre (Datenübersicht als Sammelprüfung) ------------------------------
def test_download_frei_bei_sauberer_uebersicht():
    assert download_sperrgrund(*UEBERSICHT, "false", [], []) is None


@pytest.mark.parametrize("fehler_da", ["true", None, ""])
def test_download_gesperrt_bei_fehler_da(fehler_da):
    assert "FehlerDa" in download_sperrgrund(*UEBERSICHT, fehler_da, [], [])


def test_download_gesperrt_bei_offener_warnung():
    assert "Warnungen" in download_sperrgrund(*UEBERSICHT, "false", ["Warnung: neu"], [])


def test_download_nur_von_der_uebersicht():
    assert "Datenübersicht" in download_sperrgrund("Bundesland", "saveBundesland", "false", [], [])


# --- Prozessgericht (§ 35 ZPO) --------------------------------------------------------
def test_prozessgericht_erkennen():
    text = "Prozessgericht\nDas Prozessgericht ist:\nAmtsgericht München\n80333 München\nSofern ein Wahlrecht …"
    assert prozessgericht_aus_text(text) == "Amtsgericht München"
    assert prozessgericht_aus_text("ohne Gericht") is None


def test_gericht_muss_genau_passen():
    assert gericht_passt("amtsgericht  münchen", "Amtsgericht München")
    assert not gericht_passt("", "Amtsgericht München")
    assert not gericht_passt("Amtsgericht Berlin", "Amtsgericht München")
    assert not gericht_passt("Amtsgericht München", None)


# --- Maskentabelle deckt die belegte Kette ab -----------------------------------------
@pytest.mark.parametrize(
    "schluessel",
    [
        "Bundesland/saveBundesland",
        "Antragsart/saveVersandart",
        "NeuerMBAntrag/neuerMBAntrag",
        "PVJaNein/leereViewDocumentASundShowAS",
        "ProzessVertreter/saveProzessVertreter",
        "Firma/saveAntragstellerFirma",
        "AntragstellerGV/saveAntragstellerGV",
        "GasamtschuldnerJaNein/saveErklaerungAuslaendischeRechtsformAS",
        "Firma/saveAntragsgegnerFirma",
        "AntragsgegnerGV/saveAntragsgegnerGV",
        "VerfahrensArt/saveVerfahrensArt",
        "KatAnspruch/saveKatAnspruch",
        "mehrDiverses/anspruchWeiter",
        "Auslagen/saveAuslagenNebenforderungen",
        "ProzessVertreter/saveProzessVertreterVerguetung",
        "Allg/showAllgemeineAngaben",
        "Allg/saveAllgemeineAngaben",
        "BankVerbindung/saveBankVerbindung",
    ],
)
def test_maske_hat_handler(schluessel):
    assert schluessel in MASKEN


def test_display_masken_nach_formular():
    for formular in ("Abtretung", "LaufendeZinsen", "mehrAG", "mehrAGGV", "mehrAS", "mehrASGV"):
        assert formular in MASKEN_NACH_FORMULAR
    # die beiden ProzessVertreter-Masken unterscheiden sich nur im Command (Falle 3)
    assert MASKEN["ProzessVertreter/saveProzessVertreter"] is not MASKEN["ProzessVertreter/saveProzessVertreterVerguetung"]
