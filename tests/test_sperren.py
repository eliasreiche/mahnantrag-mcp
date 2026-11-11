"""Sicherheits- und Freigabesperren, offline getestet (ohne Browser, ohne Portal)."""

import json
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

from mahnantrag_mcp import server
from mahnantrag_mcp.modell import Antrag
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout

from mahnantrag_mcp.portal import (
    JS_BEREITSCHAFT,
    JS_MARKIEREN,
    MASKEN,
    MASKEN_NACH_FORMULAR,
    MAX_QUITTIERUNGEN,
    WARNUNG_VORGERICHTLICH,
    PortalFehler,
    PortalSitzung,
    Zustand,
    ablageordner_anlegen,
    browserfehler_text,
    dialog_erlaubt,
    download_fehlertext,
    download_sperrgrund,
    erlaubte_warnungen,
    gericht_passt,
    neue_maske_bereit,
    prozessgericht_aus_text,
    uebersicht_text,
    unbekannte_warnungen,
    verguetung_betrag_feld,
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


# --- Vorgerichtliche Tätigkeit ohne Vergütung: Warnung nur nach ausdrücklicher Entscheidung --
def _antrag_vorgerichtlich(bestaetigt):
    d = deepcopy(BEISPIEL)
    d["auslagen"]["vorgerichtlicher_gegenstandswert"] = "1000"
    d["entscheidungen"]["vorgerichtlich_ohne_verguetung_bestaetigt"] = bestaetigt
    return Antrag.model_validate(d)


@pytest.mark.parametrize("bestaetigt", [None, False])
def test_vorgerichtliche_warnung_ohne_entscheidung_nicht_quittierbar(bestaetigt):
    erlaubt = erlaubte_warnungen(_antrag_vorgerichtlich(bestaetigt))
    assert erlaubt == []
    w = [f"Warnung: Bitte überprüfen Sie Ihre Eingabe, {WARNUNG_VORGERICHTLICH}."]
    assert "Warnungen" in download_sperrgrund(*UEBERSICHT, "false", w, erlaubt)


def test_vorgerichtliche_warnung_nur_bei_true_quittierbar():
    erlaubt = erlaubte_warnungen(_antrag_vorgerichtlich(True))
    assert erlaubt == [WARNUNG_VORGERICHTLICH]
    w = [f"Warnung: Bitte überprüfen Sie Ihre Eingabe, {WARNUNG_VORGERICHTLICH}."]
    assert download_sperrgrund(*UEBERSICHT, "false", w, erlaubt) is None


def test_bestaetigung_ohne_konstellation_erlaubt_nichts():
    d = deepcopy(BEISPIEL)
    d["entscheidungen"]["vorgerichtlich_ohne_verguetung_bestaetigt"] = True
    assert erlaubte_warnungen(Antrag.model_validate(d)) == []
    assert erlaubte_warnungen(None) == []


# --- Warten auf die neue Maske (Markierung des alten Dokuments) ------------------------
@pytest.mark.parametrize(
    "d,erwartet",
    [
        ({"geladen": True, "alt": False, "command": True}, True),
        ({"geladen": True, "alt": True, "command": True}, False),  # alte Maske steht noch
        ({"geladen": False, "alt": False, "command": True}, False),
        ({"geladen": True, "alt": False, "command": False}, False),
        (None, False),
    ],
)
def test_neue_maske_bereit(d, erwartet):
    assert neue_maske_bereit(d) is erwartet


class _FakeFrame:
    """Simuliert einen Inhaltsframe: markierbares Dokument, das nach einigen Abfragen ersetzt wird."""

    def __init__(self, seite, wechsel_nach):
        self.seite = seite
        self.markiert = False
        self.abfragen = 0
        self.wechsel_nach = wechsel_nach  # None = es kommt nie ein neues Dokument

    async def evaluate(self, js):
        if js == JS_MARKIEREN:
            self.markiert = True
            return None
        if js == JS_BEREITSCHAFT:
            self.abfragen += 1
            if self.wechsel_nach is not None and self.abfragen > self.wechsel_nach:
                self.markiert = False  # neues Dokument trägt keine Markierung
            if self.abfragen == 2:
                raise PlaywrightError("Execution context was destroyed")  # Frame im Neuaufbau
            return {"geladen": True, "alt": self.markiert, "command": True}
        if "innerText" in js:
            if self.seite.zustand_fehler > 0:
                self.seite.zustand_fehler -= 1
                raise PlaywrightError("Frame was detached")
            return {"n": "Allg", "c": "saveAllgemeineAngaben", "t": "Text"}
        raise AssertionError(js)


class _FakePage:
    def __init__(self, wechsel_nach=None, zustand_fehler=0, ohne_frame=False):
        self.zustand_fehler = zustand_fehler
        self.f = None if ohne_frame else _FakeFrame(self, wechsel_nach)
        self.wartezeit = 0

    def frame(self, name):
        return self.f if name == "form" else None

    async def wait_for_timeout(self, ms):
        self.wartezeit += ms


def _sitzung(page):
    s = PortalSitzung()
    s.page = page
    return s


async def test_klick_wartet_auf_neues_dokument_nicht_auf_alte_maske():
    page = _FakePage(wechsel_nach=5)
    s = _sitzung(page)
    geklickt = []

    async def klick():
        geklickt.append(True)

    await s._klicken_und_warten(klick)
    assert geklickt and page.f.markiert is False
    assert page.f.abfragen == 6  # fünfmal die alte, markierte Maske abgelehnt


async def test_alte_maske_allein_fuehrt_zur_zeitueberschreitung():
    s = _sitzung(_FakePage(wechsel_nach=None))

    async def klick():
        pass

    with pytest.raises(PortalFehler, match="Zeitüberschreitung"):
        await s._klicken_und_warten(klick)


async def test_abgewiesener_dialog_ohne_neue_maske_wird_genannt():
    s = _sitzung(_FakePage(wechsel_nach=None))
    s.protokoll.abgewiesene_dialoge.append("Bitte füllen Sie das Feld PLZ aus.")

    async def klick():
        pass

    with pytest.raises(PortalFehler, match="Feld PLZ"):
        await s._klicken_und_warten(klick)


# --- Playwright-Fehler enden als Halt ---------------------------------------------------
async def test_zustand_uebersteht_kurzen_neuaufbau():
    z = await _sitzung(_FakePage(zustand_fehler=2)).zustand()
    assert z.schluessel == "Allg/saveAllgemeineAngaben"


async def test_zustand_dauerhaft_unlesbar_wird_portalfehler():
    with pytest.raises(PortalFehler, match="Lesen der Maske"):
        await _sitzung(_FakePage(zustand_fehler=99)).zustand()


async def test_zustand_ohne_frame_wird_portalfehler():
    with pytest.raises(PortalFehler, match="Kein Inhaltsframe"):
        await _sitzung(_FakePage(ohne_frame=True)).zustand()


async def test_playwright_fehler_im_lauf_wird_portalfehler():
    s = _sitzung(_FakePage())
    s.antrag = Antrag.model_validate(deepcopy(BEISPIEL))

    async def kaputt(self):
        raise PlaywrightTimeout("Timeout 30000ms exceeded.\n=========================== logs ===")

    s._lauf = kaputt.__get__(s)
    with pytest.raises(PortalFehler, match="Fortsetzen: Timeout 30000ms exceeded.") as info:
        await s.fortsetzen("Amtsgericht München")
    assert "logs" not in str(info.value)


async def test_programmierfehler_werden_nicht_verschluckt():
    s = _sitzung(_FakePage())
    s.antrag = Antrag.model_validate(deepcopy(BEISPIEL))

    async def kaputt(self):
        raise KeyError("bug")

    s._lauf = kaputt.__get__(s)
    with pytest.raises(KeyError):
        await s.fortsetzen("Amtsgericht München")


def test_download_fehler_nennt_abgewiesenen_dialog():
    text = download_fehlertext("Timeout 60000ms exceeded", ["Bitte bestätigen Sie zuerst den Hinweis."])
    assert "Bitte bestätigen Sie zuerst den Hinweis." in text
    assert "EDA-Datei kam nicht an" in text
    assert "Timeout" in download_fehlertext("Timeout 60000ms exceeded", [])


def test_browserfehler_text_nur_erste_zeile():
    text = browserfehler_text("Ausfüllen", "net::ERR_NAME_NOT_RESOLVED\nCall log:\n- navigating", [])
    assert "ERR_NAME_NOT_RESOLVED" in text and "Call log" not in text


async def test_portal_status_stirbt_nicht_an_unlesbarer_maske(monkeypatch):
    s = _sitzung(_FakePage(zustand_fehler=99))
    monkeypatch.setattr(server, "_sitzung", s)
    status = await server.portal_status()
    assert status["offen"] is True and status["maske"] is None
    assert "nicht lesbar" in status["grund"]


# --- Datenübersicht wird nie gekürzt -----------------------------------------------------
def test_uebersicht_vollstaendig():
    text = "Navigation\nMB-Antrag Übersicht\n" + "Zeile mit Daten\n" * 2000 + "ENDE-DER-UEBERSICHT"
    u = uebersicht_text(text)
    assert u.startswith("MB-Antrag Übersicht") and u.endswith("ENDE-DER-UEBERSICHT")
    assert len(u) > 6000
    assert uebersicht_text("ohne Überschrift") == "ohne Überschrift"


# --- Vergütungsbetrag nur bei 'vereinbart' -----------------------------------------------
def test_verguetungsbetrag_feld():
    assert verguetung_betrag_feld("vereinbart", Decimal("300")) == "300,00 EUR"
    assert verguetung_betrag_feld("gesetzlich", Decimal("300")) == "0,00 EUR"
    assert verguetung_betrag_feld("verzicht", Decimal("300")) == "0,00 EUR"


class _Aufzeichner(PortalSitzung):
    """Sitzung, deren Feld-Primitive nur aufzeichnen (kein Browser)."""

    def __init__(self, antrag):
        super().__init__()
        self.antrag = antrag
        self.aufrufe = []

    async def _text(self, f, name, wert):
        self.aufrufe.append(("text", name, wert))

    async def _auswahl(self, f, name, wert):
        self.aufrufe.append(("auswahl", name, wert))

    async def _radio(self, f, name, wert):
        self.aufrufe.append(("radio", name, wert))

    async def _haken(self, f, name, an):
        self.aufrufe.append(("haken", name, an))

    async def _absenden(self, z, knopf=None):
        self.aufrufe.append(("absenden",))


def _zustand(formular="X", command="y", text=""):
    return Zustand(frame=None, formular=formular, command=command, text=text)


async def test_m_verguetung_schreibt_betrag_nur_bei_vereinbart():
    d = deepcopy(BEISPIEL)
    d["entscheidungen"]["verguetung_vereinbart_betrag"] = "300"  # gesetzlich: Betrag darf nicht ins Portal
    s = _Aufzeichner(Antrag.model_validate(d))
    await s._m_verguetung(_zustand())
    assert ("text", "_bVerguetungBetrag", "0,00 EUR") in s.aufrufe
    d["entscheidungen"]["verguetung_mahnverfahren"] = "vereinbart"
    s = _Aufzeichner(Antrag.model_validate(d))
    await s._m_verguetung(_zustand())
    assert ("text", "_bVerguetungBetrag", "300,00 EUR") in s.aufrufe


async def test_m_anspruch_laesst_leere_belegart_unberuehrt():
    d = deepcopy(BEISPIEL)
    d["ansprueche"][0]["belegart"] = ""
    s = _Aufzeichner(Antrag.model_validate(d))
    await s._m_anspruch(_zustand())
    assert not any(a[:2] == ("auswahl", "_aspAspGr") for a in s.aufrufe)
    s = _Aufzeichner(Antrag.model_validate(deepcopy(BEISPIEL)))
    await s._m_anspruch(_zustand())
    assert ("auswahl", "_aspAspGr", "Rechnung") in s.aufrufe


# --- Ablageordner vor dem Download -------------------------------------------------------
def test_ablageordner_wird_angelegt(tmp_path):
    ordner = ablageordner_anlegen(tmp_path / "ausgabe", "AZ 12/26", datetime(2026, 11, 11, 9, 30, 5))
    assert ordner.is_dir() and ordner.name == "20261111-093005_AZ_12_26"
    assert list(ordner.iterdir()) == []  # Schreibprobe hinterlässt nichts


def test_ablageordner_nicht_beschreibbar(tmp_path):
    gesperrt = tmp_path / "gesperrt"
    gesperrt.mkdir()
    gesperrt.chmod(0o500)
    try:
        with pytest.raises(PortalFehler, match="MAHNANTRAG_AUSGABE"):
            ablageordner_anlegen(gesperrt, "AZ", datetime(2026, 11, 11))
    finally:
        gesperrt.chmod(0o700)


async def test_download_klickt_nicht_bei_unbeschreibbarem_ordner(tmp_path, monkeypatch):
    s = PortalSitzung()
    s.antrag = Antrag.model_validate(deepcopy(BEISPIEL))
    s.page = object()
    geklickt = []

    async def zustand_uebersicht():
        return _zustand(*UEBERSICHT)

    async def fehler_da(z):
        return "false"

    async def knopf(f, name=None):
        geklickt.append(True)

    monkeypatch.setattr(s, "_stabiler_zustand", zustand_uebersicht)
    monkeypatch.setattr(s, "_fehler_da", fehler_da)
    monkeypatch.setattr(s, "_knopf", knopf)
    datei = tmp_path / "keinordner"
    datei.write_text("x")  # Datei statt Ordner -> mkdir scheitert
    with pytest.raises(PortalFehler, match="Ablageordner"):
        await s.eda_herunterladen(datei)
    assert geklickt == []


async def test_leerer_ordner_wird_bei_fehler_nach_dem_klick_entfernt(tmp_path, monkeypatch):
    s = PortalSitzung()
    s.antrag = Antrag.model_validate(deepcopy(BEISPIEL))
    s.page = object()
    zustaende = iter([_zustand(*UEBERSICHT), _zustand("Bundesland", "saveBundesland")])

    async def naechster():
        return next(zustaende)

    async def fehler_da(z):
        return "false"

    async def knopf(f, name=None):
        pass

    monkeypatch.setattr(s, "_stabiler_zustand", naechster)
    monkeypatch.setattr(s, "_fehler_da", fehler_da)
    monkeypatch.setattr(s, "_knopf", knopf)
    with pytest.raises(PortalFehler, match="abgelaufen"):
        await s.eda_herunterladen(tmp_path)
    assert list(tmp_path.iterdir()) == []


# --- Quittieren: jedes Klick-Ergebnis wird gelesen ----------------------------------------
WARNUNG_TEXT = f"Warnung: Bitte überprüfen Sie Ihre Eingabe, {WARNUNG_VORGERICHTLICH}."


def _quittier_sitzung(monkeypatch, folge):
    s = PortalSitzung()
    s.antrag = _antrag_vorgerichtlich(True)
    folge = iter(folge)
    klicks = []

    async def knopf(f, name=None):
        klicks.append(True)

    async def naechster():
        return next(folge)

    monkeypatch.setattr(s, "_knopf", knopf)
    monkeypatch.setattr(s, "_stabiler_zustand", naechster)
    return s, klicks


async def test_letzter_quittierklick_wird_ausgewertet(monkeypatch):
    warn = _zustand("Auslagen", "saveAuslagenNebenforderungen", WARNUNG_TEXT)
    weiter = _zustand("ProzessVertreter", "saveProzessVertreterVerguetung")
    s, klicks = _quittier_sitzung(monkeypatch, [warn] * MAX_QUITTIERUNGEN + [weiter])
    await s._absenden(_zustand("Auslagen", "saveAuslagenNebenforderungen"))
    assert len(klicks) == 1 + MAX_QUITTIERUNGEN


async def test_quittieren_gibt_nach_letztem_gelesenen_ergebnis_auf(monkeypatch):
    warn = _zustand("Auslagen", "saveAuslagenNebenforderungen", WARNUNG_TEXT)
    s, klicks = _quittier_sitzung(monkeypatch, [warn] * (MAX_QUITTIERUNGEN + 1))
    with pytest.raises(PortalFehler, match="nicht quittieren"):
        await s._absenden(_zustand("Auslagen", "saveAuslagenNebenforderungen"))
    assert len(klicks) == 1 + MAX_QUITTIERUNGEN


async def test_fehler_nach_quittierklick_wird_gemeldet(monkeypatch):
    warn = _zustand("Auslagen", "saveAuslagenNebenforderungen", WARNUNG_TEXT)
    fehler = _zustand("Auslagen", "saveAuslagenNebenforderungen", "Fehler: Betrag fehlt.")
    s, _ = _quittier_sitzung(monkeypatch, [warn, fehler])
    with pytest.raises(PortalFehler, match="Betrag fehlt"):
        await s._absenden(_zustand("Auslagen", "saveAuslagenNebenforderungen"))
