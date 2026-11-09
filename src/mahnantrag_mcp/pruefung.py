"""Deterministische Vorprüfung eines Antrags, bevor das Portal ihn sieht.

Das Portal prüft selbst kaum etwas (vierstellige PLZ, falsche Vertreterfunktion und
doppelte Anwaltsvergütung gehen durch). Deshalb prüfen wir hier.

- fehler:    blockiert das Ausfüllen
- warnungen: Ausfüllen möglich, Mensch soll hinsehen
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from . import kataloge
from .modell import Adresse, Antrag, Firma, NatuerlichePerson, Rolle, Versandart

# Rechtsformzusätze, die im Firmennamen auftauchen sollten (grobe Plausibilität)
_RECHTSFORM_KURZ = re.compile(
    r"\b(GmbH|UG|AG|KG|OHG|GbR|e\.\s?K\.|e\.\s?V\.|eG|SE|mbH|Ltd|Limited|PartG|KGaA|S\.?A\.?R\.?L|B\.?V\.)",
    re.IGNORECASE,
)


@dataclass
class Pruefbericht:
    fehler: list[str] = field(default_factory=list)
    warnungen: list[str] = field(default_factory=list)

    @property
    def zulaessig(self) -> bool:
        return not self.fehler

    def als_dict(self) -> dict:
        return {"zulaessig": self.zulaessig, "fehler": self.fehler, "warnungen": self.warnungen}


def _laenge(b: Pruefbericht, wo: str, wert: str, maximal: int) -> None:
    if len(wert) > maximal:
        b.fehler.append(f"{wo}: {len(wert)} Zeichen, das Portal erlaubt höchstens {maximal}.")


def _adresse(b: Pruefbericht, wo: str, a: Adresse) -> None:
    _laenge(b, f"{wo} Straße", a.strasse, 35)
    _laenge(b, f"{wo} Ort", a.ort, 27)
    _laenge(b, f"{wo} Auslandskennzeichen", a.auslandskennzeichen, 3)
    if a.auslandskennzeichen and a.auslandskennzeichen.upper() not in ("D", "DE"):
        b.fehler.append(
            f"{wo}: Auslandsanschrift. Die Zusatzmasken für Auslandsfälle sind in v0.1 nicht abgebildet; bitte im Portal von Hand erfassen."
        )
    elif not re.fullmatch(r"\d{5}", a.plz):
        b.fehler.append(f"{wo}: PLZ '{a.plz}' ist keine fünfstellige deutsche PLZ (das Portal würde sie trotzdem annehmen).")
    if not a.strasse or not a.ort:
        b.fehler.append(f"{wo}: Straße und Ort sind Pflicht.")


def _iban_ok(iban: str) -> bool:
    s = re.sub(r"\s+", "", iban).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s):
        return False
    n = "".join(str(int(c, 36)) for c in s[4:] + s[:4])
    return int(n) % 97 == 1


def _partei(b: Pruefbericht, wo: str, p: NatuerlichePerson | Firma) -> None:
    if isinstance(p, NatuerlichePerson):
        _laenge(b, f"{wo} Vorname", p.vorname, 35)
        _laenge(b, f"{wo} Nachname", p.nachname, 35)
        _adresse(b, wo, p.adresse)
        return
    for i, z in enumerate(p.name_zeilen, 1):
        _laenge(b, f"{wo} Firmenname Zeile {i}", z, 35)
    if p.rechtsform_code not in kataloge.rechtsformen():
        b.fehler.append(f"{wo}: Rechtsform-Code '{p.rechtsform_code}' steht nicht im Katalog.")
    else:
        rf = kataloge.rechtsformen()[p.rechtsform_code]
        if not _RECHTSFORM_KURZ.search(" ".join(p.name_zeilen)):
            b.warnungen.append(
                f"{wo}: Der Firmenname enthält keinen erkennbaren Rechtsformzusatz. Das Portal verlangt den "
                f"vollständigen Namen einschließlich Rechtsform (gewählt: {rf})."
            )
    _adresse(b, wo, p.adresse)
    if not p.gesetzliche_vertreter:
        b.fehler.append(
            f"{wo}: Kein gesetzlicher Vertreter angegeben (§ 690 Abs. 1 Nr. 1 ZPO). "
            "Firmen ohne Vertreter (z. B. e.K.) sind in v0.1 nicht abgebildet."
        )
    if len(p.gesetzliche_vertreter) > 1:
        b.fehler.append(f"{wo}: Mehr als ein gesetzlicher Vertreter ist in v0.1 nicht abgebildet.")
    for gv in p.gesetzliche_vertreter:
        _laenge(b, f"{wo} Vertreter-Name", gv.name, 35)
        if gv.adresse:
            _adresse(b, f"{wo} Vertreter", gv.adresse)


RVG_KATALOG_NR = ("24", "71")  # Rechtsanwaltshonorar / Verzugsschaden aus vorgerichtlicher RA-Tätigkeit


def vorgerichtlich_ohne_verguetung(a: Antrag) -> bool:
    """Gegenstandswert oder Anrechnungsbetrag ohne vorgerichtliche Vergütung. Das Portal warnt dann;
    die Warnung darf der Ausfüller quittieren, weil die Vorprüfung sie schon gemeldet hat."""
    au = a.auslagen
    return bool(
        au
        and (au.vorgerichtlicher_gegenstandswert or au.anrechnungsbetrag_3305)
        and not au.vorgerichtliche_anwaltsverguetung
    )


def pruefen(a: Antrag, heute: date | None = None) -> Pruefbericht:
    heute = heute or date.today()
    b = Pruefbericht()
    e = a.entscheidungen

    # --- Rolle, Prozessbevollmächtigter, Versandart -------------------------------------
    pv = a.prozessbevollmaechtigter
    if a.rolle is Rolle.PROZESSBEVOLLMAECHTIGTER:
        if pv is None:
            b.fehler.append("Rolle 'prozessbevollmaechtigter', aber keine Angaben zum Prozessbevollmächtigten.")
        if e.verguetung_mahnverfahren is None:
            b.fehler.append("Vergütung im Mahnverfahren nicht entschieden (gesetzlich / vereinbart / verzicht).")
    elif pv is not None:
        b.fehler.append("Rolle 'antragsteller', aber Prozessbevollmächtigter angegeben. Rolle prüfen.")

    if pv:
        _laenge(b, "Prozessbevollmächtigter Name", pv.name, 105)
        if pv.kennziffer and not re.fullmatch(r"\d{8}", pv.kennziffer):
            b.fehler.append("Prozessvertreter-Kennziffer muss genau 8 Ziffern haben (ggf. führende 0).")
        if not pv.kennziffer and pv.adresse is None:
            b.fehler.append("Prozessbevollmächtigter: ohne Kennziffer ist die Anschrift Pflicht.")
        if pv.adresse:
            _adresse(b, "Prozessbevollmächtigter", pv.adresse)
        if pv.beauftragungsdatum and pv.beauftragungsdatum > heute:
            b.fehler.append("Beauftragungsdatum liegt in der Zukunft.")

    if e.verguetung_mahnverfahren == "vereinbart" and not e.verguetung_vereinbart_betrag:
        b.fehler.append("Vereinbarte Vergütung gewählt, aber kein Betrag angegeben.")

    if pv is not None and not e.einreichung_durch_berufstraeger:
        b.fehler.append(
            "Prozessbevollmächtigter (Rechtsanwalt/-beistand) angegeben, aber 'einreichung_durch_berufstraeger' ist false."
        )
    if a.versandart is Versandart.BARCODE and e.einreichung_durch_berufstraeger:
        if not e.barcode_glaubhaftmachung:
            b.fehler.append(
                "Barcode-Weg bei Einreichung durch Rechtsanwalt, Behörde oder Inkassodienstleister (auch in eigener "
                "Sache): nach § 130d S. 2, 3 ZPO nur zulässig, wenn die elektronische Einreichung vorübergehend "
                "unmöglich ist und das glaubhaft gemacht wird. EDA-Download wählen oder die Glaubhaftmachung angeben."
            )
        else:
            b.warnungen.append("Barcode-Weg durch Berufsträger: die Glaubhaftmachung muss dem Antrag gesondert beigefügt werden.")

    # --- Parteien -------------------------------------------------------------------------
    _partei(b, "Antragsteller", a.antragsteller)
    _partei(b, "Antragsgegner", a.antragsgegner)
    if a.antragsgegner_nato_truppenstatut and not isinstance(a.antragsgegner, NatuerlichePerson):
        b.fehler.append("NATO-Truppenstatut gibt es nur bei natürlichen Personen als Antragsgegner.")

    # --- Verfahren und Ansprüche ----------------------------------------------------------
    if a.verfahrensart != "NMV":
        b.fehler.append(
            f"Verfahrensart {a.verfahrensart}: Urkunden-, Scheck- und Wechselmahnverfahren sind in v0.1 nicht erprobt. "
            "Bitte im Portal von Hand erfassen."
        )
    if len(a.ansprueche) > 1:
        b.fehler.append("Mehrere Ansprüche sind in v0.1 nicht abgebildet (Reihenfolge und Index-Bindung im Portal unsicher).")

    for i, asp in enumerate(a.ansprueche, 1):
        wo = f"Anspruch {i}"
        if asp.katalog_nr not in kataloge.anspruchsarten():
            b.fehler.append(f"{wo}: Katalognummer '{asp.katalog_nr}' steht nicht im Anspruchskatalog.")
        if asp.belegart and asp.belegart not in kataloge.belegarten():
            b.fehler.append(f"{wo}: Belegart '{asp.belegart}' unbekannt. Erlaubt: {', '.join(kataloge.belegarten())}.")
        _laenge(b, f"{wo} Belegnummer", asp.belegnummer, 35)
        _laenge(b, f"{wo} Zusatz", asp.belegart_zusatz, 35)
        if asp.betrag <= 0:
            b.fehler.append(f"{wo}: Betrag muss größer als 0 sein.")
        if asp.datum_von > heute:
            b.fehler.append(f"{wo}: Datum liegt in der Zukunft.")
        if asp.datum_bis and asp.datum_bis < asp.datum_von:
            b.fehler.append(f"{wo}: Zeitraum-Ende liegt vor dem Beginn.")
        if asp.abtretung:
            ab = asp.abtretung
            _laenge(b, f"{wo} früherer Gläubiger", ab.frueherer_glaeubiger, 35)
            _laenge(b, f"{wo} Abtretung Ort", ab.ort, 27)
            if ab.auslandskennzeichen and ab.auslandskennzeichen.upper() not in ("D", "DE"):
                b.fehler.append(f"{wo}: früherer Gläubiger im Ausland. Auslandsfälle sind in v0.1 nicht abgebildet.")
            elif not re.fullmatch(r"\d{5}", ab.plz):
                b.fehler.append(f"{wo}: PLZ des früheren Gläubigers ist keine fünfstellige deutsche PLZ.")
            if ab.datum > heute:
                b.fehler.append(f"{wo}: Abtretungsdatum liegt in der Zukunft.")
        if asp.zinsen:
            z = asp.zinsen
            if z.ab > heute:
                b.warnungen.append(f"{wo}: Zinsbeginn liegt in der Zukunft.")
            if z.ab < asp.datum_von:
                b.warnungen.append(f"{wo}: Zinsbeginn liegt vor dem Anspruchsdatum.")
            if z.ueber_basiszins:
                # Ob ein Verbraucher beteiligt ist, ist eine Rechtsfrage (§ 13 BGB) und wird nicht aus der
                # Parteiform geraten: der Mensch entscheidet es in `entscheidungen.verbraucher_beteiligt`.
                if z.zinssatz > 9:
                    b.warnungen.append(f"{wo}: {z.zinssatz} Punkte über Basiszins übersteigt § 288 Abs. 2 BGB (9 Punkte).")
                elif z.zinssatz > 5 and e.verbraucher_beteiligt is None:
                    b.fehler.append(
                        f"{wo}: {z.zinssatz} Punkte über Basiszins setzen voraus, dass kein Verbraucher beteiligt ist "
                        "(§ 288 Abs. 2 BGB). Bitte 'verbraucher_beteiligt' entscheiden."
                    )
                elif z.zinssatz > 5 and e.verbraucher_beteiligt:
                    b.warnungen.append(
                        f"{wo}: {z.zinssatz} Punkte über Basiszins, obwohl ein Verbraucher beteiligt ist. Gesetzlich sind "
                        "dann 5 Punkte vorgesehen (§ 288 Abs. 1 BGB); höhere Zinsen brauchen eine eigene Grundlage."
                    )
            elif z.zinssatz > 10:
                b.warnungen.append(f"{wo}: fester Zinssatz von {z.zinssatz} % ist ungewöhnlich hoch. War 'über Basiszins' gemeint?")

    # --- Auslagen und Nebenforderungen ----------------------------------------------------
    au = a.auslagen
    rvg_haupt = any(x.katalog_nr in RVG_KATALOG_NR for x in a.ansprueche)
    rvg_neben = bool(au and au.vorgerichtliche_anwaltsverguetung)
    if rvg_haupt and rvg_neben:
        b.fehler.append(
            "Vorgerichtliche Anwaltsvergütung steht doppelt drin: als Hauptforderung (Kat.-Nr. 24/71) und als "
            "Nebenforderung. Das verdoppelt die Forderung, und das Portal merkt es nicht. Eine Variante wählen."
        )
    else:
        tatsaechlich = "als_hauptforderung" if rvg_haupt else "als_nebenforderung" if rvg_neben else "keine"
        if tatsaechlich != e.vorgerichtliche_anwaltsverguetung:
            b.fehler.append(
                f"Entscheidung vorgerichtliche Anwaltsvergütung = '{e.vorgerichtliche_anwaltsverguetung}', "
                f"die Antragsdaten ergeben aber '{tatsaechlich}'. Daten oder Entscheidung anpassen."
            )
    if au:
        if vorgerichtlich_ohne_verguetung(a):
            b.warnungen.append(
                "Gegenstandswert oder Anrechnungsbetrag ohne vorgerichtliche Anwaltsvergütung. Das Portal warnt hier; "
                "der Ausfüller quittiert die Warnung nur, wenn das so gewollt ist."
            )
        if au.sonstige_auslage_art and au.sonstige_auslage_art not in kataloge.AUSLAGEN_ARTEN:
            b.fehler.append(f"Auslagenart '{au.sonstige_auslage_art}' steht nicht in der Portal-Liste.")
        if au.sonstige_auslage_art and not au.sonstige_auslage_bezeichnung:
            # live belegt 2026-11-09: "Fehler: Bitte geben Sie eine Begründung für die sonstigen Auslagen an."
            b.fehler.append("Sonstige Auslage ohne Begründung. Das Portal verlangt sie für jede Auslagenart.")
        if au.sonstige_auslage_betrag and not au.sonstige_auslage_art:
            b.fehler.append("Betrag für sonstige Auslage ohne Auslagenart.")
        _laenge(b, "Auslagen-Bezeichnung", au.sonstige_auslage_bezeichnung, 35)
        if re.search(r"gericht|mahnverfahren|mahnbescheid", au.sonstige_auslage_bezeichnung, re.IGNORECASE):
            b.warnungen.append(
                "Auslage klingt nach Kosten des Mahnverfahrens. Die werden nach § 699 Abs. 3 ZPO von Amts wegen "
                "aufgenommen und dürfen nicht als Auslage eingetragen werden."
            )

    # --- Allgemeine Angaben -----------------------------------------------------------------
    _laenge(b, "Geschäftszeichen", a.geschaeftszeichen, 35)
    if not a.geschaeftszeichen:
        b.warnungen.append("Kein Geschäftszeichen. Es ist der einzige Schlüssel, über den sich Post vom Mahngericht der Akte zuordnen lässt.")
    if not e.prozessgericht_bestaetigt:
        b.warnungen.append(
            "Prozessgericht noch nicht bestätigt. Der Ausfüller hält an der Prozessgericht-Maske an und zeigt das vom "
            "Portal abgeleitete Gericht; Weiterklicken gilt als Wahl nach § 35 ZPO. Eine abweichende Gerichtswahl ist "
            "in v0.1 nicht abgebildet."
        )

    if a.bankverbindung:
        if not _iban_ok(a.bankverbindung.iban):
            b.fehler.append("IBAN ist ungültig (Prüfziffer).")
        if a.bankverbindung.kontoinhaber == "prozessbevollmaechtigter" and pv is None:
            b.fehler.append("Kontoinhaber Prozessbevollmächtigter, aber kein Prozessbevollmächtigter angegeben.")
    elif not (pv and pv.kennziffer):
        b.warnungen.append("Keine Bankverbindung. Ohne Kennziffer mit hinterlegtem Konto kann der Gegner nicht direkt zahlen.")

    gesamt = sum((x.betrag for x in a.ansprueche), Decimal(0))
    if gesamt > Decimal("100000"):
        b.warnungen.append(f"Hauptforderung {gesamt} EUR. Bei hohen Beträgen Zuständigkeit und Gebühren besonders prüfen.")

    return b
