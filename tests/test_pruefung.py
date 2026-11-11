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


def test_gegenstandswert_ohne_verguetung_verlangt_entscheidung():
    b = bericht(lambda d: d["auslagen"].update(vorgerichtlicher_gegenstandswert="1000"))
    assert any("vorgerichtlich_ohne_verguetung_bestaetigt" in f for f in b.fehler)

    def abgelehnt(d):
        d["auslagen"]["anrechnungsbetrag_3305"] = "50"
        d["entscheidungen"]["vorgerichtlich_ohne_verguetung_bestaetigt"] = False

    assert any("vorgerichtlich_ohne_verguetung_bestaetigt" in f for f in bericht(abgelehnt).fehler)

    def bestaetigt(d):
        d["auslagen"]["vorgerichtlicher_gegenstandswert"] = "1000"
        d["entscheidungen"]["vorgerichtlich_ohne_verguetung_bestaetigt"] = True

    assert bericht(bestaetigt).zulaessig


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
        x["entscheidungen"]["einreichung_durch_berufstraeger"] = False

    assert bericht(d).zulaessig


def test_barcode_anwalt_in_eigener_sache_gesperrt():
    def d(x):
        x["versandart"] = "Barcode"
        x["rolle"] = "antragsteller"
        x["prozessbevollmaechtigter"] = None
        x["entscheidungen"]["verguetung_mahnverfahren"] = None
        x["entscheidungen"]["einreichung_durch_berufstraeger"] = True

    assert any("130d" in f for f in bericht(d).fehler)


def test_pv_erzwingt_berufstraeger():
    b = bericht(lambda d: d["entscheidungen"].update(einreichung_durch_berufstraeger=False))
    assert any("einreichung_durch_berufstraeger" in f for f in b.fehler)


def test_pv_ohne_verguetungsentscheidung():
    b = bericht(lambda d: d["entscheidungen"].update(verguetung_mahnverfahren=None))
    assert any("Vergütung" in f for f in b.fehler)


def test_gericht_unbestaetigt_ist_warnung_kein_fehler():
    b = bericht(lambda d: d["entscheidungen"].update(prozessgericht_bestaetigt=""))
    assert b.zulaessig
    assert any("35 ZPO" in w for w in b.warnungen)


def test_iban_pruefziffer():
    b = bericht(lambda d: d["bankverbindung"].update(iban="DE89370400440532013001"))
    assert any("IBAN" in f for f in b.fehler)


def test_auslage_ohne_begruendung():
    b = bericht(lambda d: d["auslagen"].update(sonstige_auslage_bezeichnung=""))
    assert any("Begründung" in f for f in b.fehler)


def test_neun_punkte_verlangen_verbraucherentscheidung():
    b = bericht(lambda d: d["entscheidungen"].update(verbraucher_beteiligt=None))
    assert any("verbraucher_beteiligt" in f for f in b.fehler)


@pytest.mark.parametrize("zinssatz", ["5.5", "9", "9.5", "12"])
def test_ueber_fuenf_punkte_immer_verbraucherentscheidung(zinssatz):
    def d(x):
        x["ansprueche"][0]["zinsen"]["zinssatz"] = zinssatz
        x["entscheidungen"]["verbraucher_beteiligt"] = None

    assert any("verbraucher_beteiligt" in f for f in bericht(d).fehler)


def test_ueber_neun_punkte_warnt_zusaetzlich():
    b = bericht(lambda d: d["ansprueche"][0]["zinsen"].update(zinssatz="12"))
    assert b.zulaessig  # verbraucher_beteiligt=False ist entschieden
    assert any("9 Punkte" in w for w in b.warnungen)

    def mit_verbraucher(d):
        d["ansprueche"][0]["zinsen"]["zinssatz"] = "12"
        d["entscheidungen"]["verbraucher_beteiligt"] = True

    w = bericht(mit_verbraucher).warnungen
    assert any("9 Punkte" in x for x in w) and any("288 Abs. 1" in x for x in w)


def test_fuenf_punkte_ohne_verbraucherentscheidung_ok():
    def d(x):
        x["ansprueche"][0]["zinsen"]["zinssatz"] = "5"
        x["entscheidungen"]["verbraucher_beteiligt"] = None

    assert bericht(d).zulaessig


def test_neun_punkte_mit_verbraucher_warnt():
    b = bericht(lambda d: d["entscheidungen"].update(verbraucher_beteiligt=True))
    assert b.zulaessig
    assert any("288 Abs. 1" in w for w in b.warnungen)


def test_verbraucher_wird_nicht_aus_parteiform_geraten():
    def d(x):
        x["antragsgegner"] = {
            "art": "person",
            "anrede": "Frau",
            "vorname": "Petra",
            "nachname": "Probe",
            "adresse": {"strasse": "Probestraße 3", "plz": "80331", "ort": "München"},
        }

    # natürliche Person, aber vom Menschen als Unternehmerin eingestuft -> keine Verbraucher-Warnung
    b = bericht(d)
    assert b.zulaessig
    assert not any("288" in w for w in b.warnungen)


def test_sonderverfahren_abgelehnt():
    b = bericht(lambda d: d.update(verfahrensart="UMV"))
    assert any("Urkunden" in f for f in b.fehler)


def test_zedent_im_ausland_abgelehnt():
    def d(x):
        x["ansprueche"][0]["abtretung"] = {
            "frueherer_glaeubiger": "Alt AG", "plz": "1010", "ort": "Wien", "auslandskennzeichen": "A", "datum": "2026-09-01"
        }

    assert any("Ausland" in f for f in bericht(d).fehler)


def test_rvg_entscheidung_muss_zu_daten_passen():
    b = bericht(lambda d: d["entscheidungen"].update(vorgerichtliche_anwaltsverguetung="als_nebenforderung"))
    assert any("ergeben aber 'keine'" in f for f in b.fehler)

    def neben(x):
        x["auslagen"]["vorgerichtliche_anwaltsverguetung"] = {"betrag": "200"}
        x["entscheidungen"]["vorgerichtliche_anwaltsverguetung"] = "als_nebenforderung"

    assert bericht(neben).zulaessig


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


# --- Vergütungsbetrag nur bei 'vereinbart' ----------------------------------------------
@pytest.mark.parametrize("verguetung", ["gesetzlich", "verzicht", None])
def test_verguetungsbetrag_ohne_vereinbart_ist_fehler(verguetung):
    def d(x):
        x["entscheidungen"]["verguetung_mahnverfahren"] = verguetung
        x["entscheidungen"]["verguetung_vereinbart_betrag"] = "300"

    assert any("vereinbarte Vergütung angegeben" in f for f in bericht(d).fehler)


def test_vereinbarte_verguetung_mit_betrag_ok_und_null_abgelehnt():
    def mit(betrag):
        def d(x):
            x["entscheidungen"]["verguetung_mahnverfahren"] = "vereinbart"
            x["entscheidungen"]["verguetung_vereinbart_betrag"] = betrag

        return d

    assert bericht(mit("300")).zulaessig
    assert any("größer als 0" in f for f in bericht(mit("0")).fehler)


# --- Leere Pflichtangaben ----------------------------------------------------------------
def _person(d):
    d["antragsgegner"] = {
        "art": "person", "anrede": "Frau", "vorname": "Petra", "nachname": "Probe",
        "adresse": {"strasse": "Probestraße 3", "plz": "80331", "ort": "München"},
    }


@pytest.mark.parametrize("feld", ["vorname", "nachname"])
def test_leerer_personenname(feld):
    def d(x):
        _person(x)
        x["antragsgegner"][feld] = "  "

    assert any(f"Antragsgegner {feld.capitalize()} ist leer" in f for f in bericht(d).fehler)


@pytest.mark.parametrize(
    "zeilen,meldung",
    [(["", "Testkunde Bau GmbH"], "erste Zeile"), (["Testkunde", "", "Bau GmbH"], "leere Zeile zwischen")],
)
def test_leere_firmennamenzeilen(zeilen, meldung):
    b = bericht(lambda d: d["antragsgegner"].update(name_zeilen=zeilen))
    assert any(meldung in f for f in b.fehler)


def test_leere_zeile_am_ende_ist_ok():
    assert bericht(lambda d: d["antragsgegner"].update(name_zeilen=["Testkunde Bau GmbH", ""])).zulaessig


def test_leerer_vertreter_und_pv_name():
    b = bericht(lambda d: d["antragsgegner"]["gesetzliche_vertreter"][0].update(name=""))
    assert any("Vertreter-Name ist leer" in f for f in b.fehler)
    b = bericht(lambda d: d["prozessbevollmaechtigter"].update(name=""))
    assert any("Prozessbevollmächtigter Name ist leer" in f for f in b.fehler)


def test_abtretung_ohne_glaeubiger_und_ort():
    def d(x):
        x["ansprueche"][0]["abtretung"] = {"frueherer_glaeubiger": "", "plz": "10115", "ort": "", "datum": "2026-09-01"}

    fehler = bericht(d).fehler
    assert any("früherer Gläubiger ist leer" in f for f in fehler)
    assert any("Ort des früheren Gläubigers ist leer" in f for f in fehler)


# --- Beträge und Zinsen ------------------------------------------------------------------
@pytest.mark.parametrize(
    "aenderung",
    [
        lambda d: d["auslagen"].update(vordruck_porto="0"),
        lambda d: d["auslagen"].update(sonstige_auslage_betrag="-40"),
        lambda d: d["auslagen"].update(mahnkosten={"betrag": "0"}),
        lambda d: d["prozessbevollmaechtigter"].update(auslagen_statt_pauschale="-1"),
        lambda d: d["ansprueche"][0]["zinsen"].update(zu_verzinsender_betrag="0"),
        lambda d: d["auslagen"].update(
            anrechnungsbetrag_3305="-5", vorgerichtlicher_gegenstandswert="1000"
        ),
    ],
)
def test_nicht_positive_betraege(aenderung):
    def d(x):
        x["entscheidungen"]["vorgerichtlich_ohne_verguetung_bestaetigt"] = True
        aenderung(x)

    assert any("größer als 0" in f for f in bericht(d).fehler)


def test_gegenstandswert_null_abgelehnt():
    def d(x):
        x["auslagen"]["vorgerichtlicher_gegenstandswert"] = "0"

    assert any("Gegenstandswert der vorgerichtlichen Tätigkeit" in f for f in bericht(d).fehler)


def test_negativer_zinssatz():
    b = bericht(lambda d: d["ansprueche"][0]["zinsen"].update(zinssatz="-1"))
    assert any("negativ" in f for f in b.fehler)
    b = bericht(lambda d: d["auslagen"].update(mahnkosten={"betrag": "5", "zinssatz": "-2", "zins_ab": "2026-10-01"}))
    assert any("Mahnkosten Zinsen: Zinssatz -2 ist negativ" in f for f in b.fehler)


def test_null_punkte_ueber_basiszins_ok_fester_nullsatz_warnt():
    assert bericht(lambda d: d["ansprueche"][0]["zinsen"].update(zinssatz="0")).zulaessig
    b = bericht(lambda d: d["ansprueche"][0]["zinsen"].update(zinssatz="0", ueber_basiszins=False))
    assert b.zulaessig and any("0 %" in w for w in b.warnungen)


def test_zinsende_vor_beginn():
    b = bericht(lambda d: d["ansprueche"][0]["zinsen"].update(bis="2026-09-01"))
    assert any("Zins-Ende" in f for f in b.fehler)
    b = bericht(lambda d: d["auslagen"].update(
        mahnkosten={"betrag": "5", "zinssatz": "5", "zins_ueber_basiszins": True, "zins_ab": "2026-10-01", "zins_bis": "2026-09-01"}
    ))
    assert any("Mahnkosten: Zins-Ende" in f for f in b.fehler)


def test_nebenforderung_zinssatz_ohne_beginn():
    b = bericht(lambda d: d["auslagen"].update(mahnkosten={"betrag": "5", "zinssatz": "5", "zins_ueber_basiszins": True}))
    assert any("ohne Zinsbeginn" in f for f in b.fehler)
    b = bericht(lambda d: d["auslagen"].update(mahnkosten={"betrag": "5", "zins_ab": "2026-10-01"}))
    assert any("ohne Zinssatz" in f for f in b.fehler)
    ok = bericht(lambda d: d["auslagen"].update(
        mahnkosten={"betrag": "5", "zinssatz": "5", "zins_ueber_basiszins": True, "zins_ab": "2026-10-01"}
    ))
    assert ok.zulaessig, ok.fehler
