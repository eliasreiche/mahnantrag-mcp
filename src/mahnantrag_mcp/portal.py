"""Ausfüller für online-mahnantrag.de (Playwright, Zustandsmaschine).

Grundlage ist die Portal-Analyse in docs/referenz/implementierung-spec.md. Die wichtigsten Regeln:

- Zustand = Formularname + verstecktes Feld `Command`, nie Titel oder Feldnamen allein.
- Inhaltsframe ist `main` oder dessen Kindframe `form`, je nach Maske.
- Die Maskenfolge ist nicht fest. Deshalb reagiert jede Runde auf die Maske, die gerade da ist.
- Text-Warnungen ("Warnung: …") werden nur quittiert, wenn sie auf der Erlaubt-Liste stehen.
- Session stirbt nach ca. 30 Min. still (Rückfall auf die Bundeslandmaske) -> wird erkannt.

Der Ausfüller hält auf der Datenübersicht an. Herunterladen ist ein eigener, ausdrücklicher Schritt.
Die heruntergeladene EDA-Datei wird nie verändert, nur gespeichert und gehasht.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from playwright.async_api import Browser, Frame, Page, Playwright, async_playwright

from . import format as fmt
from .kataloge import PV_BEZEICHNUNG, VERTRETER_FUNKTION
from .modell import Antrag, Firma, NatuerlichePerson, Rolle, Versandart

START_URL = "https://www.online-mahnantrag.de/"

# Warnungen, die quittiert werden dürfen, und unter welcher Bedingung (siehe _erlaubte_warnungen)
WARNUNG_VORGERICHTLICH = (
    "es wurde ein Streitwert für eine vorgerichtliche Tätigkeit und/oder ein Minderungsbetrag angegeben, "
    "ohne dass hierfür eine Anwaltsvergütung angegeben wurde"
)


class PortalFehler(Exception):
    """Der Ausfüller hat angehalten. Der Browser bleibt offen, damit ein Mensch übernehmen kann."""


class SessionAbgelaufen(PortalFehler):
    pass


@dataclass
class Zustand:
    frame: Frame
    formular: str
    command: str
    text: str

    @property
    def warnungen(self) -> list[str]:
        return [z.strip() for z in self.text.splitlines() if z.strip().startswith("Warnung:")]

    @property
    def fehler(self) -> list[str]:
        """Blockierende Portal-Fehler ('Fehler: …'). Nicht quittierbar, Eingabe muss sich ändern."""
        return [z.strip() for z in self.text.splitlines() if z.strip().startswith("Fehler:")]

    @property
    def schluessel(self) -> str:
        return f"{self.formular}/{self.command}"


@dataclass
class Protokoll:
    schritte: list[str] = field(default_factory=list)
    quittierte_warnungen: list[str] = field(default_factory=list)
    dialoge: list[str] = field(default_factory=list)

    def add(self, s: str) -> None:
        self.schritte.append(f"{datetime.now():%H:%M:%S} {s}")


def _normalisieren(text: str) -> str:
    text = re.sub(r"[ \t ]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


class PortalSitzung:
    """Eine Browser-Sitzung = ein Antrag. Nach dem Download oder bei Abbruch schließen."""

    def __init__(self) -> None:
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self.page: Page | None = None
        self.protokoll = Protokoll()
        self.antrag: Antrag | None = None
        self.uebersicht: str = ""
        self.gestartet: datetime | None = None

    # ------------------------------------------------------------------ Browser
    async def oeffnen(self, sichtbar: bool) -> None:
        self._pw = await async_playwright().start()
        opts: dict = {"headless": not sichtbar}
        pfad = os.environ.get("MAHNANTRAG_BROWSER_PFAD")
        kanal = os.environ.get("MAHNANTRAG_BROWSER_KANAL", "chrome")
        if pfad:
            opts["executable_path"] = pfad
        else:
            opts["channel"] = kanal
        try:
            self._browser = await self._pw.chromium.launch(**opts)
        except Exception:
            opts.pop("channel", None)
            self._browser = await self._pw.chromium.launch(**opts)  # Playwright-Chromium als Rückfall
        ctx = await self._browser.new_context(locale="de-DE", accept_downloads=True)
        self.page = await ctx.new_page()
        self.page.on("dialog", self._dialog)
        self.gestartet = datetime.now()

    async def _dialog(self, d) -> None:
        # Modale alert()s blockieren den Renderer. Immer bestätigen, aber protokollieren.
        self.protokoll.dialoge.append(d.message)
        await d.accept()

    async def schliessen(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self._browser = self._pw = self.page = None

    # ------------------------------------------------------------------ Grundfunktionen
    def _inhaltsframe(self) -> Frame:
        assert self.page
        f = self.page.frame(name="form") or self.page.frame(name="main")
        if f is None:
            raise PortalFehler("Kein Inhaltsframe gefunden. Ist das Portal erreichbar oder im Wartungsfenster?")
        return f

    async def _warten(self) -> None:
        """Warten, bis der Inhaltsframe ein Formular mit Command trägt."""
        assert self.page
        await self.page.wait_for_timeout(400)
        for _ in range(60):
            try:
                f = self._inhaltsframe()
                if await f.evaluate(
                    "()=>document.readyState==='complete'&&!!document.querySelector('form input[name=Command]')"
                ):
                    await self.page.wait_for_timeout(250)
                    return
            except Exception:
                pass
            await self.page.wait_for_timeout(250)
        raise PortalFehler("Die Maske ist nicht fertig geladen (Zeitüberschreitung).")

    async def zustand(self) -> Zustand:
        f = self._inhaltsframe()
        d = await f.evaluate(
            """()=>{const fo=document.querySelector('form');const c=fo&&fo.querySelector('input[name=Command]');
            return {n:fo?fo.getAttribute('name')||'':'',c:c?c.value:'',t:document.body?document.body.innerText:''}}"""
        )
        return Zustand(f, d["n"], d["c"], _normalisieren(d["t"]))

    async def _text(self, f: Frame, name: str, wert: str) -> None:
        loc = f.locator(f'form :is(input,textarea)[name="{name}"]')
        if await loc.count() != 1:
            raise PortalFehler(f"Feld {name} nicht eindeutig gefunden ({await loc.count()}x).")
        await loc.fill(wert)  # überschreibt Vorbelegungen wie '0,00 EUR'

    async def _auswahl(self, f: Frame, name: str, wert: str) -> None:
        loc = f.locator(f'form select[name="{name}"]')
        if await loc.count() != 1:
            raise PortalFehler(f"Auswahlliste {name} nicht gefunden.")
        gesetzt = await loc.select_option(value=wert)
        if gesetzt != [wert]:
            raise PortalFehler(f"Wert '{wert}' in {name} nicht vorhanden.")

    async def _haken(self, f: Frame, name: str, an: bool) -> None:
        loc = f.locator(f'form input[type=checkbox][name="{name}"]')
        if await loc.count() != 1:
            raise PortalFehler(f"Checkbox {name} nicht gefunden.")
        await loc.set_checked(an)

    async def _radio(self, f: Frame, name: str, wert: str) -> None:
        loc = f.locator(f'form input[type=radio][name="{name}"][value="{wert}"]')
        if await loc.count() != 1:
            raise PortalFehler(f"Option {wert} bei {name} ist in dieser Maske nicht vorhanden.")
        await loc.check()

    async def _weiter(self, f: Frame, name: str | None = None) -> None:
        if name:
            sel = f'form input[type=image][name="{name}"]'
        else:
            sel = 'form input[type=image]:not([name="neuer Antrag"])'
        loc = f.locator(sel)
        if await loc.count() < 1:
            raise PortalFehler(f"Kein Weiter-Knopf gefunden ({sel}).")
        await loc.first.click()
        await self._warten()

    async def _link(self, f: Frame, command: str) -> None:
        loc = f.locator(f'a[href*="Command={command}"]')
        if await loc.count() < 1:
            raise PortalFehler(f"Link {command} nicht gefunden.")
        await loc.first.evaluate("e=>e.click()")
        await self._warten()

    # ------------------------------------------------------------------ Ablauf
    def _erlaubte_warnungen(self) -> list[str]:
        a = self.antrag
        erlaubt = []
        if a and a.auslagen and (a.auslagen.vorgerichtlicher_gegenstandswert or a.auslagen.anrechnungsbetrag_3305):
            if not a.auslagen.vorgerichtliche_anwaltsverguetung:
                erlaubt.append(WARNUNG_VORGERICHTLICH)
        return erlaubt

    async def _absenden(self, z: Zustand, knopf: str | None = None) -> None:
        """Absenden und Text-Warnungen behandeln (gleiche Maske kommt mit 'Warnung:' zurück)."""
        await self._weiter(z.frame, knopf)
        for _ in range(3):
            neu = await self.zustand()
            if not neu.command:
                await self._warten()
                neu = await self.zustand()
            if neu.schluessel == z.schluessel and neu.fehler:
                raise PortalFehler("Das Portal meldet einen Fehler: " + " | ".join(neu.fehler))
            if neu.schluessel != z.schluessel or not neu.warnungen:
                return
            for w in neu.warnungen:
                if not any(e in w for e in self._erlaubte_warnungen()):
                    raise PortalFehler(f"Unbekannte oder nicht freigegebene Warnung des Portals: {w}")
                self.protokoll.quittierte_warnungen.append(w)
            self.protokoll.add(f"Warnung quittiert in {z.schluessel}")
            await self._weiter(neu.frame, knopf)  # unverändert erneut absenden = quittieren
        raise PortalFehler("Warnung ließ sich nicht quittieren.")

    async def ausfuellen(self, antrag: Antrag, sichtbar: bool) -> dict:
        self.antrag = antrag
        await self.oeffnen(sichtbar)
        assert self.page
        await self.page.goto(START_URL, wait_until="networkidle")
        await self.page.get_by_text("Ich stimme zu", exact=True).click()
        await self._warten()
        self.protokoll.add("Datenschutzhinweis bestätigt")

        offen = {
            "abtretung": antrag.ansprueche[0].abtretung is not None,
            "zinsen": antrag.ansprueche[0].zinsen is not None,
        }
        gesehen: dict[str, int] = {}
        for _ in range(60):
            z = await self.zustand()
            if not z.command:  # Frame wurde mitten im Neuaufbau gelesen
                await self._warten()
                z = await self.zustand()
            gesehen[z.schluessel] = gesehen.get(z.schluessel, 0) + 1
            if gesehen[z.schluessel] > 4:
                raise PortalFehler(f"Schleife erkannt in Maske {z.schluessel}. Bitte im Browser prüfen.")
            if z.formular == "MBUebersicht":
                return await self._uebersicht_lesen(z)
            await self._schritt(z, antrag, offen)
        raise PortalFehler("Zu viele Schritte, Datenübersicht nicht erreicht.")

    async def _schritt(self, z: Zustand, a: Antrag, offen: dict) -> None:  # noqa: C901 – eine Maske je Zweig
        f, k = z.frame, z.schluessel
        self.protokoll.add(f"Maske {k}")
        pv = a.prozessbevollmaechtigter

        if k == "Bundesland/saveBundesland":
            if self.protokoll.schritte and any("Versandart" in s for s in self.protokoll.schritte):
                raise SessionAbgelaufen("Das Portal ist auf die Bundeslandauswahl zurückgefallen. Die Sitzung ist abgelaufen.")
            await self._auswahl(f, "Bundesland", a.bundesland.value)
            await self._absenden(z)
        elif k == "Antragsart/saveVersandart":
            await self._radio(f, "_bVersandart", a.versandart.value)
            self.protokoll.add(f"Versandart {a.versandart.value}")
            await self._absenden(z)
        elif k == "NeuerMBAntrag/neuerMBAntrag":
            await self._weiter(f, "neuer Antrag")  # frischer Antrag, verwirft alte Eingaben dieser Sitzung
        elif z.formular == "PVJaNein":
            if a.rolle is Rolle.PROZESSBEVOLLMAECHTIGTER:
                loc = f.locator('a[href*="Command=holeProzessVertreter"]:not([href*="raInEigenerSache"]):has(img[src*="butt_weiter"])')
                if await loc.count() != 1:
                    raise PortalFehler("Weg 'Ich bin Prozessbevollmächtigter' nicht eindeutig gefunden.")
                await loc.evaluate("e=>e.click()")
                await self._warten()
            else:
                await self._weiter(f, "Weiter AS")
        elif k == "ProzessVertreter/saveProzessVertreter":
            assert pv
            await self._text(f, "_pvBeauftragungsdatum", fmt.datum(pv.beauftragungsdatum))
            await self._text(f, "_pvBetrag", fmt.betrag(pv.auslagen_statt_pauschale) if pv.auslagen_statt_pauschale else "")
            await self._haken(f, "_pvErklaerungVorsteuer", pv.antragsteller_nicht_vorsteuerabzugsberechtigt)
            await self._haken(f, "_pvUmsatzsteuerBefreit", pv.umsatzsteuerbefreit)
            await self._text(f, "_pvKennziffer", pv.kennziffer)
            await self._auswahl(f, "_pvTitelMM", PV_BEZEICHNUNG[pv.bezeichnung])
            await self._text(f, "_pvName1", pv.name)
            ad = pv.adresse
            await self._text(f, "_pvStr", ad.strasse if ad else "")
            await self._text(f, "_pvPLZ", ad.plz if ad else "")
            await self._text(f, "_pvOrt", ad.ort if ad else "")
            await self._text(f, "_pvNation", ad.auslandskennzeichen if ad else "")
            await self._absenden(z)
        elif k in ("NatuerlichePerson/saveAntragstellerNatPers", "Firma/saveAntragstellerFirma"):
            await self._partei(z, a.antragsteller, "Antragsteller")
        elif k in ("NatuerlichePerson/saveAntragsgegnerNatPers", "Firma/saveAntragsgegnerFirma"):
            await self._partei(z, a.antragsgegner, "Antragsgegner")
        elif k == "AntragstellerGV/saveAntragstellerGV":
            await self._vertreter(z, a.antragsteller)
        elif k == "AntragsgegnerGV/saveAntragsgegnerGV":
            await self._vertreter(z, a.antragsgegner)
        elif z.formular in ("mehrASGV", "mehrAS", "mehrAGGV", "mehrAG"):
            await self._weiter(f, "Nein")  # v0.1: je ein Antragsteller, Antragsgegner, Vertreter
        elif z.formular == "GasamtschuldnerJaNein":  # Schreibfehler stammt aus dem Portal
            await self._absenden(z)
        elif k == "VerfahrensArt/saveVerfahrensArt":
            await self._radio(f, "_bVerfahrensArt", a.verfahrensart)
            await self._absenden(z)
        elif k == "KatAnspruch/saveKatAnspruch":
            await self._anspruch(z, a)
        elif k == "mehrDiverses/anspruchWeiter":
            if offen["abtretung"]:
                wahl = "Abtretung"
            elif offen["zinsen"]:
                wahl = "Zinsen"
            else:
                wahl = "Weiter"
            await self._radio(f, "MehrAbtretungZinsenAnspruch", wahl)
            await self._absenden(z)
        elif z.formular == "Abtretung":
            if not offen["abtretung"]:
                raise PortalFehler("Abtretungsmaske erneut geöffnet, obwohl schon erfasst.")
            ab = a.ansprueche[0].abtretung
            assert ab
            await self._text(f, "_bName1", ab.frueherer_glaeubiger)
            await self._text(f, "_bPLZ", ab.plz)
            await self._text(f, "_bOrt", ab.ort)
            await self._text(f, "_bNation", ab.auslandskennzeichen)
            await self._text(f, "_bAbgetretenAm", fmt.datum(ab.datum))
            await self._absenden(z)
            offen["abtretung"] = False
        elif z.formular == "LaufendeZinsen":
            if not offen["zinsen"]:
                # Erneutes Öffnen legt einen Doppeleintrag an (Falle 9). Nicht absenden.
                raise PortalFehler("Zinsmaske erneut geöffnet, obwohl Zinsen schon erfasst sind. Abbruch gegen Doppeleintrag.")
            zi = a.ansprueche[0].zinsen
            assert zi
            await self._text(f, "_bZinssatz", fmt.zinssatz(zi.zinssatz))
            await self._haken(f, "_bUeberBasisZinssatz", zi.ueber_basiszins)
            await self._auswahl(f, "_bZinssatzJMT", {"jaehrlich": "J", "monatlich": "M", "taeglich": "T"}[zi.turnus])
            await self._text(f, "_bBasisBetrag", fmt.betrag(zi.zu_verzinsender_betrag) if zi.zu_verzinsender_betrag else "")
            await self._text(f, "_bVon", fmt.datum(zi.ab))
            await self._text(f, "_bBis", fmt.datum(zi.bis))
            await self._absenden(z)
            offen["zinsen"] = False
        elif k == "Auslagen/saveAuslagenNebenforderungen":
            await self._auslagen(z, a)
        elif k == "ProzessVertreter/saveProzessVertreterVerguetung":
            e = a.entscheidungen
            if not e.verguetung_mahnverfahren:
                raise PortalFehler("Vergütung im Mahnverfahren nicht entschieden.")
            await self._radio(f, "_bVerguetungMM", e.verguetung_mahnverfahren.upper())
            await self._text(f, "_bVerguetungBetrag", fmt.betrag(e.verguetung_vereinbart_betrag))
            await self._absenden(z)
        elif k == "Allg/showAllgemeineAngaben":
            gericht = z.text
            self.protokoll.add("Prozessgericht (automatisch): " + _ausschnitt(gericht, "Prozessgericht", 300))
            if not a.entscheidungen.gerichtsstand_automatisch_ok:
                raise PortalFehler("Gerichtsstand nicht bestätigt.")
            await self._absenden(z)
        elif z.command == "saveAllgemeineAngaben":
            e = a.entscheidungen
            await self._text(f, "_bAntragstellerGeschaeftszeichen", a.geschaeftszeichen)
            await self._haken(f, "_bErklaerungVorGegenLeistung1", e.gegenleistung == "bereits_erbracht")
            await self._haken(f, "_bErklaerungVorGegenLeistung2", e.gegenleistung == "nicht_abhaengig")
            await self._haken(f, "_bErklaerungStreitVerfahren", e.streitiges_verfahren_bei_widerspruch)
            await self._absenden(z)
        elif k == "BankVerbindung/saveBankVerbindung":
            bv = a.bankverbindung
            await self._text(f, "_bIban", re.sub(r"\s+", "", bv.iban) if bv else "")
            await self._text(f, "_bBic", bv.bic if bv else "")
            if bv:
                await self._auswahl(f, "_bKontoZuordnung", "2" if bv.kontoinhaber == "prozessbevollmaechtigter" else "1")
            await self._absenden(z)
        else:
            raise PortalFehler(
                f"Unbekannte Maske {k}. Der Ausfüller hält an; bitte im Browser prüfen.\n"
                + _ausschnitt(z.text, "Antrag auf Erlass", 600)
            )

    async def _partei(self, z: Zustand, p: NatuerlichePerson | Firma, rolle: str) -> None:
        f = z.frame
        if isinstance(p, Firma) and z.formular != "Firma":
            await self._link(f, f"hole{rolle}Firma")  # Reiter 'Firma'
            return
        if isinstance(p, NatuerlichePerson) and z.formular != "NatuerlichePerson":
            await self._link(f, f"hole{rolle}NatPers")
            return
        if isinstance(p, NatuerlichePerson):
            await self._auswahl(f, "_bAnrede", "1" if p.anrede == "Herr" else "2")
            await self._text(f, "_bName1", p.vorname)
            await self._text(f, "_bName2", p.nachname)
            if rolle == "Antragsgegner":
                assert self.antrag
                await self._haken(f, "_bNatoTruppenstatut", self.antrag.antragsgegner_nato_truppenstatut)
        else:
            zeilen = p.name_zeilen + [""] * (4 - len(p.name_zeilen))
            for i, zeile in enumerate(zeilen, 1):
                await self._text(f, f"_bName{i}", zeile)
            await self._auswahl(f, "_bRechtsform", p.rechtsform_code)
        ad = p.adresse
        await self._text(f, "_bStr", ad.strasse)
        await self._text(f, "_bPLZ", ad.plz)
        await self._text(f, "_bOrt", ad.ort)
        await self._text(f, "_bNation", ad.auslandskennzeichen)
        await self._absenden(z)

    async def _vertreter(self, z: Zustand, p: NatuerlichePerson | Firma) -> None:
        if not isinstance(p, Firma) or not p.gesetzliche_vertreter:
            raise PortalFehler(f"Maske {z.schluessel} erwartet einen gesetzlichen Vertreter, im Antrag ist keiner.")
        gv = p.gesetzliche_vertreter[0]
        f = z.frame
        await self._auswahl(f, "_gvVertreterFunktion", VERTRETER_FUNKTION[gv.funktion])
        await self._text(f, "_gvName1", gv.name)
        ad = gv.adresse
        await self._text(f, "_gvStr", ad.strasse if ad else "")
        await self._text(f, "_gvPLZ", ad.plz if ad else "")
        await self._text(f, "_gvOrt", ad.ort if ad else "")
        await self._text(f, "_gvNation", ad.auslandskennzeichen if ad else "")
        await self._absenden(z)

    async def _anspruch(self, z: Zustand, a: Antrag) -> None:
        f = z.frame
        asp = a.ansprueche[0]
        await self._text(f, "KatNr", asp.katalog_nr)
        await self._auswahl(f, "_bKatalogArt", asp.katalog_nr)
        await self._auswahl(f, "_aspAspGr", asp.belegart)
        await self._text(f, "_aspAspGrZusatz", asp.belegart_zusatz)
        await self._text(f, "_bAspNr", asp.belegnummer)
        await self._text(f, "_bVon", fmt.datum(asp.datum_von))
        await self._text(f, "_bBis", fmt.datum(asp.datum_bis))
        await self._text(f, "_bBetrag", fmt.betrag(asp.betrag))
        await self._haken(f, "MehrVerbrKreditGesetz", asp.verbraucherkredit)
        await self._absenden(z)

    async def _auslagen(self, z: Zustand, a: Antrag) -> None:
        f = z.frame
        au = a.auslagen
        if au:
            await self._text(f, "_bVordruckPorto", fmt.betrag(au.vordruck_porto))
            if au.sonstige_auslage_art:
                await self._auswahl(f, "liste1", au.sonstige_auslage_art)
            await self._text(f, "_bSonstBetrag", fmt.betrag(au.sonstige_auslage_betrag))
            await self._text(f, "_bSonstBezeichnung", au.sonstige_auslage_bezeichnung)
            for praefix, nf in [
                ("_bMahnKosten", au.mahnkosten),
                ("_bAuskunftsKosten", au.auskunftskosten),
                ("_bBankruecklastKosten", au.bankruecklastkosten),
                ("_bInkassoKosten", au.inkassokosten),
                ("_bVorgerAnwaltsverguetung", au.vorgerichtliche_anwaltsverguetung),
            ]:
                if nf:
                    await self._text(f, praefix, fmt.betrag(nf.betrag))
                    if nf.zinssatz is not None:
                        await self._text(f, f"{praefix}Zins", fmt.zinssatz(nf.zinssatz))
                        await self._haken(f, f"{praefix}ZinsUeberBasis", nf.zins_ueber_basiszins)
                        await self._text(f, f"{praefix}ZinsVon", fmt.datum(nf.zins_ab))
                        await self._text(f, f"{praefix}ZinsBis", fmt.datum(nf.zins_bis))
            await self._text(f, "_bVorgerStreitwert", fmt.betrag(au.vorgerichtlicher_gegenstandswert))
            await self._haken(f, "_bVorgerUmfangreich", au.vorgerichtlich_umfangreich)
            await self._text(f, "_bVorgerMinderungsbetrag", fmt.betrag(au.anrechnungsbetrag_3305))
        await self._absenden(z)

    async def _uebersicht_lesen(self, z: Zustand) -> dict:
        fehler_da = await z.frame.evaluate(
            "()=>{const e=document.querySelector('input[name=FehlerDa]');return e?e.value:null}"
        )
        self.uebersicht = z.text
        self.protokoll.add(f"Datenübersicht erreicht (FehlerDa={fehler_da})")
        return {
            "status": "datenuebersicht",
            "fehler_da": fehler_da,
            "offene_warnungen": z.warnungen,
            "uebersicht": _ausschnitt(z.text, "MB-Antrag Übersicht", 6000),
            "hinweis": (
                "Der Ausfüller hat auf der Datenübersicht angehalten. Bitte die Übersicht prüfen. "
                "Checkbox-Zustände (Erklärungen) sind dort nicht ablesbar und stehen im Protokoll. "
                "Danach eda_herunterladen aufrufen oder im Browser selbst weitermachen."
            ),
            "protokoll": self.protokoll.schritte,
            "quittierte_warnungen": self.protokoll.quittierte_warnungen,
            "dialoge": self.protokoll.dialoge,
        }

    # ------------------------------------------------------------------ Download
    async def eda_herunterladen(self, zielordner: Path) -> dict:
        if not self.antrag or self.antrag.versandart is not Versandart.EDA:
            raise PortalFehler("Download gibt es nur für Versandart EDA-Download.")
        z = await self.zustand()
        if z.formular == "MBUebersicht":
            await self._weiter(z.frame)
            z = await self.zustand()
        if z.formular != "AbgabeEDA":
            raise PortalFehler(f"Erwartet: Abgabemaske EDA, gefunden: {z.schluessel}.")
        f = z.frame
        haken = f.locator('form input[type=checkbox][name="hinweisGelesen"]')
        if await haken.count() != 1:
            raise PortalFehler("Bestätigung 'hinweisGelesen' nicht gefunden.")
        await haken.check()  # Pflicht-Gate, sonst blockierender alert()
        assert self.page
        async with self.page.expect_download(timeout=60_000) as dl_info:
            await f.locator('form input[type=image][src*="butt_speichern"]').first.click()
        dl = await dl_info.value
        zielordner.mkdir(parents=True, exist_ok=True)
        gz = re.sub(r"[^A-Za-z0-9_-]+", "_", self.antrag.geschaeftszeichen or "ohne-az").strip("_")
        ziel = zielordner / f"{datetime.now():%Y%m%d-%H%M%S}_{gz}_{dl.suggested_filename}"
        await dl.save_as(ziel)
        sha = hashlib.sha256(ziel.read_bytes()).hexdigest()
        ziel.chmod(0o444)  # schreibgeschützt: die Datei darf nicht verändert werden
        self.protokoll.add(f"EDA-Datei gespeichert: {ziel.name} sha256={sha}")
        return {
            "datei": str(ziel),
            "portal_dateiname": dl.suggested_filename,
            "groesse_bytes": ziel.stat().st_size,
            "sha256": sha,
            "hinweis": (
                "Datei unverändert über einen sicheren Übermittlungsweg (beA) an das zuständige Mahngericht senden. "
                "Nicht öffnen und speichern, nicht umbenennen-und-bearbeiten, nicht zusätzlich als Barcode einreichen."
            ),
        }


def _ausschnitt(text: str, ab: str, laenge: int) -> str:
    i = text.find(ab)
    return text[i if i >= 0 else 0 :][:laenge]
