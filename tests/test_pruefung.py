import json
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from mahnantrag_mcp import format as fmt
from mahnantrag_mcp import kataloge
from mahnantrag_mcp.modell import Antrag
from mahnantrag_mcp.pruefung import pruefen

HEUTE = date(2026, 11, 9)
BEISPIEL = json.loads((Path(__file__).parent / "beispiel_antrag.json").read_text())


def bericht(aenderung=None):
    d = deepcopy(BEISPIEL)
    if aenderung:
        aenderung(d)
    return pruefen(Antrag.model_validate(d), heute=HEUTE)


def test_beispiel_ist_zulaessig():
    b = bericht()
    assert b.zulaessig, b.fehler


# --- Format -------------------------------------------------------------------------
@pytest.mark.parametrize(
    "wert,erwartet",
    [("0", "0,00 EUR"), ("3000", "3.000,00 EUR"), ("1234.565", "1.234,57 EUR"), ("1234567.8", "1.234.567,80 EUR")],
)
def test_betrag(wert, erwartet):
    assert fmt.betrag(Decimal(wert)) == erwartet


def test_zinssatz_und_datum():
    assert fmt.zinssatz(Decimal("9")) == "9,000 %"
    assert fmt.zinssatz(Decimal("5.12")) == "5,120 %"
    assert fmt.datum(date(2026, 2, 1)) == "01.02.2026"
    assert fmt.datum(None) == ""


# --- Kataloge -----------------------------------------------------------------------
def test_kataloge_vollstaendig():
    assert len(kataloge.anspruchsarten()) == 75
    assert len(kataloge.rechtsformen()) == 177  # + Leeroption = 178 im Portal
    assert kataloge.rechtsformen()["131"] == "UG (haftungsbeschränkt)"
    assert kataloge.belegarten()["Sonstiger"] == "andere"


def test_katalog_suche():
    assert "11" in kataloge.suchen("anspruchsart", "Kaufvertrag")
    assert kataloge.suchen("rechtsform", "3") == {"3": kataloge.rechtsformen()["3"]}


# --- Prüfregeln ---------------------------------------------------------------------
def test_firmenname_zu_lang():
    b = bericht(lambda d: d["antragsteller"].update(name_zeilen=["Beispiel Handel UG (haftungsbeschränkt)"]))
    assert any("höchstens 35" in f for f in b.fehler)


def test_vierstellige_plz():
    b = bericht(lambda d: d["antragsgegner"]["adresse"].update(plz="1043"))
    assert any("PLZ" in f for f in b.fehler)


def test_auslandsanschrift_nicht_unterstuetzt():
    b = bericht(lambda d: d["antragsgegner"]["adresse"].update(plz="1010", auslandskennzeichen="A"))
    assert any("Auslandsanschrift" in f for f in b.fehler)


def test_unbekannter_katalogcode():
    b = bericht(lambda d: d["ansprueche"][0].update(katalog_nr="99"))
    assert any("Anspruchskatalog" in f for f in b.fehler)
    b = bericht(lambda d: d["antragsgegner"].update(rechtsform_code="4711"))
    assert any("Rechtsform-Code" in f for f in b.fehler)


def test_firma_ohne_vertreter():
    b = bericht(lambda d: d["antragsgegner"].update(gesetzliche_vertreter=[]))
    assert any("gesetzlicher Vertreter" in f for f in b.fehler)


def test_rvg_doppelt():
    def d(x):
        x["ansprueche"][0]["katalog_nr"] = "24"
        x["auslagen"]["vorgerichtliche_anwaltsverguetung"] = {"betrag": "200"}

    assert any("doppelt" in f for f in bericht(d).fehler)


def test_gegenstandswert_ohne_verguetung_ist_warnung():
    b = bericht(lambda d: d["auslagen"].update(vorgerichtlicher_gegenstandswert="1000"))
    assert b.zulaessig
    assert any("Gegenstandswert" in w for w in b.warnungen)


def test_barcode_fuer_anwalt_nur_mit_glaubhaftmachung():
    b = bericht(lambda d: d.update(versandart="Barcode"))
    assert any("130d" in f for f in b.fehler)

    def mit(d):
        d["versandart"] = "Barcode"
        d["entscheidungen"]["barcode_glaubhaftmachung"] = "beA-Störung seit 08:00, Störungsmeldung liegt vor"

    assert bericht(mit).zulaessig


def test_barcode_ohne_anwalt_ok():
    def d(x):
        x["versandart"] = "Barcode"
        x["rolle"] = "antragsteller"
        x["prozessbevollmaechtigter"] = None
        x["entscheidungen"]["verguetung_mahnverfahren"] = None

    assert bericht(d).zulaessig


def test_pv_ohne_verguetungsentscheidung():
    b = bericht(lambda d: d["entscheidungen"].update(verguetung_mahnverfahren=None))
    assert any("Vergütung" in f for f in b.fehler)


def test_gerichtsstand_muss_bestaetigt_sein():
    b = bericht(lambda d: d["entscheidungen"].update(gerichtsstand_automatisch_ok=False))
    assert any("35 ZPO" in f for f in b.fehler)


def test_iban_pruefziffer():
    b = bericht(lambda d: d["bankverbindung"].update(iban="DE89370400440532013001"))
    assert any("IBAN" in f for f in b.fehler)


def test_auslage_ohne_begruendung():
    b = bericht(lambda d: d["auslagen"].update(sonstige_auslage_bezeichnung=""))
    assert any("Begründung" in f for f in b.fehler)


def test_neun_punkte_gegen_verbraucher_warnt():
    def d(x):
        x["antragsgegner"] = {
            "art": "person",
            "anrede": "Frau",
            "vorname": "Petra",
            "nachname": "Probe",
            "adresse": {"strasse": "Probestraße 3", "plz": "80331", "ort": "München"},
        }

    b = bericht(d)
    assert b.zulaessig
    assert any("288" in w for w in b.warnungen)


def test_mehrere_ansprueche_v01_abgelehnt():
    b = bericht(lambda d: d["ansprueche"].append(deepcopy(d["ansprueche"][0])))
    assert any("Mehrere Ansprüche" in f for f in b.fehler)


def test_zukunftsdatum():
    b = bericht(lambda d: d["ansprueche"][0].update(datum_von="2027-01-01"))
    assert any("Zukunft" in f for f in b.fehler)


def test_unbekannte_felder_werden_abgelehnt():
    d = deepcopy(BEISPIEL)
    d["erfundenes_feld"] = 1
    with pytest.raises(Exception):
        Antrag.model_validate(d)
