"""Ausfüller für online-mahnantrag.de (Playwright, Zustandsmaschine).

Grundlage ist die Portal-Analyse in docs/referenz/implementierung-spec.md. Die wichtigsten Regeln:

- Zustand = Formularname + verstecktes Feld `Command`, nie Titel oder Feldnamen allein.
  Ausnahme: Abtretung, Zinsen und "weiterer Antragsgegner" tragen alle `Command=display`;
  dort unterscheidet nur der Formularname.
- Inhaltsframe ist `main` oder dessen Kindframe `form`, je nach Maske.
- Die Maskenfolge ist nicht fest. Deshalb reagiert jede Runde auf die Maske, die gerade da ist.
- Text-Warnungen ("Warnung: …") werden nur quittiert, wenn sie auf der Erlaubt-Liste stehen.
- Session stirbt nach ca. 30 Min. still (Rückfall auf die Bundeslandmaske) -> wird erkannt.

Haltepunkte, an denen der Mensch entscheidet:
1. Prozessgericht: das Portal leitet es aus der Gegneranschrift ab; Weiterklicken gilt als Wahl
   nach § 35 ZPO. Ohne passende Bestätigung hält der Ausfüller an und zeigt das Gericht.
2. Datenübersicht: Herunterladen ist ein eigener, ausdrücklicher Schritt.

Die heruntergeladene EDA-Datei wird nie verändert, nur gespeichert und gehasht.
"""

from __future__ import annotations

import functools
import hashlib
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Awaitable, Callable

from playwright.async_api import Browser, Frame, Page, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError

from . import format as fmt
from .kataloge import PV_BEZEICHNUNG, VERTRETER_FUNKTION
from .modell import Adresse, Antrag, Firma, NatuerlichePerson, Rolle, Versandart
from .pruefung import vorgerichtlich_ohne_verguetung

START_URL = "https://www.online-mahnantrag.de/"
SESSION_GRENZE = timedelta(minutes=28)  # Portal beendet nach ~30 Min. Untätigkeit, mit Puffer

# Wortlaute, die der Ausfüller quittieren bzw. bestätigen darf
WARNUNG_VORGERICHTLICH = (
    "es wurde ein Streitwert für eine vorgerichtliche Tätigkeit und/oder ein Minderungsbetrag angegeben, "
    "ohne dass hierfür eine Anwaltsvergütung angegeben wurde"
)
BEKANNTE_DIALOGE = ("Bitte lesen Sie die Hinweise zum EDA-Download",)
MAX_QUITTIERUNGEN = 3  # so oft wird eine erlaubte Warnung höchstens durch erneutes Absenden quittiert

# Vor jedem Klick bekommt das alte Dokument jedes Inhaltsframes eine Markierung. Ein frisch geladenes
# Dokument hat sie nicht. So erkennt _warten() die neue Maske auch dann, wenn das Portal langsam antwortet
# oder dieselbe Maske (Formular/Command) mit Warnung oder Fehler zurückkommt.
INHALTSFRAMES = ("form", "main")
JS_MARKIEREN = "()=>{document.__mahnantragAlt=true}"
JS_BEREITSCHAFT = (
    "()=>({geladen:document.readyState==='complete',alt:!!document.__mahnantragAlt,"
    "command:!!document.querySelector('form input[name=Command]')})"
)

# Knopf-Namen der Portalmasken (input[type=image]); je Maske live belegt
KNOPF_NEUER_ANTRAG = "neuer Antrag"
KNOPF_ICH_BIN_ANTRAGSTELLER = "Weiter AS"
KNOPF_NEIN = "Nein"

# Reiter-Links zwischen "Herr, Frau" und "Firma"
REITER = {
    ("Antragsteller", Firma): "holeAntragstellerFirma",
    ("Antragsteller", NatuerlichePerson): "holeAntragstellerNatPers",
    ("Antragsgegner", Firma): "holeAntragsgegnerFirma",
    ("Antragsgegner", NatuerlichePerson): "holeAntragsgegnerNatPers",
}
ZINS_TURNUS = {"jaehrlich": "J", "monatlich": "M", "taeglich": "T"}


class PortalFehler(Exception):
    """Der Ausfüller hat angehalten. Der Browser bleibt offen, damit ein Mensch übernehmen kann."""


class SessionAbgelaufen(PortalFehler):
    pass


class GerichtBestaetigen(PortalFehler):
    """Haltepunkt: das abgeleitete Prozessgericht muss vom Menschen bestätigt werden."""

    def __init__(self, gefunden: str, bestaetigt: str) -> None:
        self.gefunden = gefunden
        self.bestaetigt = bestaetigt
        grund = "noch nicht bestätigt" if not bestaetigt else f"bestätigt war '{bestaetigt}'"
        super().__init__(f"Prozessgericht laut Portal: '{gefunden}' ({grund}).")


# ---------------------------------------------------------------------- reine Prüffunktionen
def unbekannte_warnungen(warnungen: list[str], erlaubt: list[str]) -> list[str]:
    """Warnungen, die nicht auf der Erlaubt-Liste stehen und deshalb nie quittiert werden."""
    return [w for w in warnungen if not any(e in w for e in erlaubt)]


def dialog_erlaubt(meldung: str) -> bool:
    return any(b in meldung for b in BEKANNTE_DIALOGE)


def prozessgericht_aus_text(text: str) -> str | None:
    """Erste Gerichtsbezeichnung nach dem Stichwort 'Prozessgericht' (z. B. 'Amtsgericht München')."""
    i = text.find("Prozessgericht")
    rest = text[i:] if i >= 0 else text
    m = re.search(r"((?:Amts|Land)gericht[^\n]*)", rest)
    return m.group(1).strip() if m else None


def gericht_passt(bestaetigt: str, gefunden: str | None) -> bool:
    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip().casefold()

    return bool(bestaetigt and gefunden and norm(bestaetigt) == norm(gefunden))


def neue_maske_bereit(d: dict | None) -> bool:
    """Ergebnis von JS_BEREITSCHAFT: fertig geladen, nicht das markierte alte Dokument, Formular mit Command."""
    return bool(d and d.get("geladen") and not d.get("alt") and d.get("command"))


def erlaubte_warnungen(antrag: Antrag | None) -> list[str]:
    """Portal-Warnungen, die der Ausfüller quittieren darf. Die Warnung zur vorgerichtlichen Tätigkeit
    ohne Anwaltsvergütung nur, wenn der Mensch diese Konstellation ausdrücklich bestätigt hat."""
    if (
        antrag
        and vorgerichtlich_ohne_verguetung(antrag)
        and antrag.entscheidungen.vorgerichtlich_ohne_verguetung_bestaetigt is True
    ):
        return [WARNUNG_VORGERICHTLICH]
    return []


def browserfehler_text(was: str, meldung: str, abgewiesene_dialoge: list[str]) -> str:
    """Playwright-Fehler als Halt-Meldung. Nur die erste Zeile, das Call-Log bleibt draußen."""
    zeile = (meldung.strip().splitlines() or ["ohne Meldung"])[0]
    text = f"Browser- oder Portalfehler beim {was}: {zeile}"
    if abgewiesene_dialoge:
        text += f" Das Portal hat einen unbekannten Dialog gezeigt, der abgewiesen wurde: '{abgewiesene_dialoge[-1]}'."
    return text + " Bitte im Browser prüfen."


def download_fehlertext(meldung: str, neue_abgewiesene_dialoge: list[str]) -> str:
    """Halt-Meldung, wenn die EDA-Datei nicht ankommt. Ein abgewiesener Dialog ist dann meist die Ursache."""
    if neue_abgewiesene_dialoge:
        return (
            "Die EDA-Datei kam nicht an. Das Portal hat nach dem Klick auf Speichern einen unbekannten Dialog gezeigt, "
            f"der abgewiesen wurde: '{neue_abgewiesene_dialoge[-1]}'. Bitte im Browser prüfen."
        )
    return browserfehler_text("EDA-Download (Datei kam nicht an)", meldung, [])


def uebersicht_text(text: str) -> str:
    """Datenübersicht ab ihrer Überschrift, vollständig. Ohne Überschrift der ganze Maskentext."""
    i = text.find("MB-Antrag Übersicht")
    return text[i:] if i >= 0 else text


def verguetung_betrag_feld(verguetung: str | None, betrag: Decimal | None) -> str:
    """Inhalt von _bVerguetungBetrag: der Betrag nur bei 'vereinbart', sonst die Vorbelegung '0,00 EUR'."""
    return fmt.betrag(betrag if verguetung == "vereinbart" else None)


def ablageordner_anlegen(zielordner: Path, geschaeftszeichen: str, jetzt: datetime) -> Path:
    """Unterordner je Fall anlegen und Schreibrecht prüfen, bevor der Download angestoßen wird."""
    gz = re.sub(r"[^A-Za-z0-9_-]+", "_", geschaeftszeichen or "ohne-az").strip("_") or "ohne-az"
    ordner = Path(zielordner).expanduser() / f"{jetzt:%Y%m%d-%H%M%S}_{gz}"
    try:
        ordner.mkdir(parents=True, exist_ok=False)
        with tempfile.TemporaryFile(dir=ordner):
            pass  # Schreibprobe; die Probedatei verschwindet sofort wieder
    except OSError as e:
        _leeren_ordner_entfernen(ordner)
        raise PortalFehler(
            f"Ablageordner {ordner} lässt sich nicht anlegen oder nicht beschreiben ({e.strerror or e}). "
            "Bitte MAHNANTRAG_AUSGABE prüfen. Es wurde noch nichts heruntergeladen, die Datenübersicht steht noch."
        ) from e
    return ordner


def _leeren_ordner_entfernen(ordner: Path) -> None:
    try:
        ordner.rmdir()  # nur wenn leer; eine gespeicherte Datei bleibt immer liegen
    except OSError:
        pass


def _browserfehler_als_halt(was: str):
    """Playwright-Fehler (Frame neu aufgebaut, Zeitüberschreitung, Portal nicht erreichbar) enden als PortalFehler,
    damit der Server sie wie jeden anderen Halt behandelt. Programmierfehler bleiben unberührt."""

    def deko(fn):
        @functools.wraps(fn)
        async def huelle(self: "PortalSitzung", *args, **kwargs):
            try:
                return await fn(self, *args, **kwargs)
            except PlaywrightError as e:
                raise PortalFehler(browserfehler_text(was, str(e), self.protokoll.abgewiesene_dialoge)) from e

        return huelle

    return deko


def download_sperrgrund(formular: str, command: str, fehler_da: str | None, warnungen: list[str], erlaubt: list[str]) -> str | None:
    """Warum der Download nicht starten darf, oder None. Die Übersicht ist die Sammelprüfung (Spec 2.2)."""
    if (formular, command) != ("MBUebersicht", "saveMBAntragUebersicht"):
        return f"Download nur von der Datenübersicht aus (aktuell: {formular}/{command})."
    if fehler_da != "false":
        return f"Das Portal meldet Fehler in der Übersicht (FehlerDa={fehler_da})."
    offen = unbekannte_warnungen(warnungen, erlaubt)
    if offen:
        return "Offene, nicht freigegebene Warnungen in der Übersicht: " + " | ".join(offen)
    return None


# ---------------------------------------------------------------------- Zustand
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
        """Blockierende Portal-Fehler ('Fehler: …'). Nicht quittierbar, die Eingabe muss sich ändern."""
        return [z.strip() for z in self.text.splitlines() if z.strip().startswith("Fehler:")]

    @property
    def schluessel(self) -> str:
        return f"{self.formular}/{self.command}"


@dataclass
class Protokoll:
    schritte: list[str] = field(default_factory=list)
    quittierte_warnungen: list[str] = field(default_factory=list)
    dialoge: list[str] = field(default_factory=list)
    abgewiesene_dialoge: list[str] = field(default_factory=list)

    def add(self, s: str) -> None:
        self.schritte.append(f"{datetime.now():%H:%M:%S} {s}")


@dataclass
class Ablauf:
    """Was im laufenden Antrag noch zu erfassen ist und welche Weichen schon gestellt sind."""

    abtretung_offen: bool
    zinsen_offen: bool
    bundesland_gesendet: bool = False


def _normalisieren(text: str) -> str:
    text = re.sub(r"[ \t ]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def _ausschnitt(text: str, ab: str, laenge: int) -> str:
    i = text.find(ab)
    return text[i if i >= 0 else 0 :][:laenge]


Handler = Callable[["PortalSitzung", Zustand], Awaitable[None]]


class PortalSitzung:
    """Eine Browser-Sitzung = ein Antrag. Nach dem Download oder bei Abbruch schließen."""

    def __init__(self) -> None:
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self.page: Page | None = None
        self.protokoll = Protokoll()
        self.antrag: Antrag | None = None
        self.ablauf: Ablauf | None = None
        self.gestartet: datetime | None = None
        self.letzte_aktivitaet: datetime | None = None

    # ------------------------------------------------------------------ Browser
    async def oeffnen(self, sichtbar: bool) -> None:
        self._pw = await async_playwright().start()
        opts: dict = {"headless": not sichtbar}
        pfad = os.environ.get("MAHNANTRAG_BROWSER_PFAD")
        if pfad:
            opts["executable_path"] = pfad
            self._browser = await self._pw.chromium.launch(**opts)
            self.protokoll.add(f"Browser: {pfad}")
        else:
            kanal = os.environ.get("MAHNANTRAG_BROWSER_KANAL", "chrome")
            try:
                self._browser = await self._pw.chromium.launch(channel=kanal, **opts)
                self.protokoll.add(f"Browser: Kanal {kanal}")
            except PlaywrightError as e:
                # Nur wenn der Kanal fehlt, auf das Playwright-Chromium ausweichen; alles andere ist ein echter Fehler.
                if "is not found" not in str(e) and "not found at" not in str(e):
                    raise
                self._browser = await self._pw.chromium.launch(**opts)
                self.protokoll.add(f"Browser: Kanal {kanal} nicht installiert, Playwright-Chromium verwendet")
        ctx = await self._browser.new_context(locale="de-DE", accept_downloads=True)
        self.page = await ctx.new_page()
        self.page.on("dialog", self._dialog)
        self.gestartet = self.letzte_aktivitaet = datetime.now()

    async def _dialog(self, d) -> None:
        # Modale Dialoge blockieren den Renderer und müssen sofort beantwortet werden.
        # Bekannte bestätigen; unbekannte abweisen und den Lauf danach anhalten.
        if dialog_erlaubt(d.message):
            self.protokoll.dialoge.append(d.message)
            await d.accept()
        else:
            self.protokoll.abgewiesene_dialoge.append(d.message)
            await d.dismiss()

    async def schliessen(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self._browser = self._pw = self.page = None

    def minuten_seit_aktivitaet(self) -> float | None:
        if not self.letzte_aktivitaet:
            return None
        return (datetime.now() - self.letzte_aktivitaet).total_seconds() / 60

    # ------------------------------------------------------------------ Grundfunktionen
    def _inhaltsframe(self) -> Frame:
        assert self.page
        f = self.page.frame(name="form") or self.page.frame(name="main")
        if f is None:
            raise PortalFehler("Kein Inhaltsframe gefunden. Ist das Portal erreichbar oder im Wartungsfenster?")
        return f

    async def _markieren(self) -> None:
        """Vor einem Klick: die aktuell geladenen Dokumente der Inhaltsframes als 'alt' markieren."""
        assert self.page
        for name in INHALTSFRAMES:
            f = self.page.frame(name=name)
            if f is None:
                continue
            try:
                await f.evaluate(JS_MARKIEREN)
            except PlaywrightError:
                pass  # Frame wird gerade neu aufgebaut; sein nächstes Dokument ist ohnehin neu

    async def _klicken_und_warten(self, klick: Callable[[], Awaitable[object]]) -> None:
        """Jeder Klick, der eine neue Maske lädt, läuft hierüber: markieren, klicken, auf neues Dokument warten."""
        await self._markieren()
        await klick()
        await self._warten()

    async def _warten(self) -> None:
        """Warten, bis der Inhaltsframe ein neu geladenes Dokument (ohne Markierung) mit Formular und Command trägt.

        Kriterium ist ein neues Dokument, nicht eine andere Maske: Warnungen und Fehler kommen in derselben
        Maske zurück. Solange das alte, markierte Dokument noch steht, wird weiter gewartet.
        """
        assert self.page
        for _ in range(60):
            f = self.page.frame(name="form") or self.page.frame(name="main")  # kann kurz fehlen
            bereit = False
            if f is not None:
                try:
                    bereit = neue_maske_bereit(await f.evaluate(JS_BEREITSCHAFT))
                except PlaywrightError:
                    pass  # Frame wird gerade neu aufgebaut
            if bereit:
                await self.page.wait_for_timeout(250)
                self.letzte_aktivitaet = datetime.now()
                if self.protokoll.abgewiesene_dialoge:
                    raise PortalFehler("Unbekannter Dialog des Portals: " + self.protokoll.abgewiesene_dialoge[-1])
                return
            await self.page.wait_for_timeout(250)
        if self.protokoll.abgewiesene_dialoge:
            # z. B. ein Prüf-alert() des Portals, der das Absenden verhindert hat
            raise PortalFehler(
                "Die neue Maske kam nicht. Das Portal hat einen unbekannten Dialog gezeigt, der abgewiesen wurde: "
                + self.protokoll.abgewiesene_dialoge[-1]
            )
        raise PortalFehler("Die Maske ist nicht fertig geladen (Zeitüberschreitung).")

    async def zustand(self) -> Zustand:
        """Aktuelle Maske lesen. Wird der Frame gerade neu aufgebaut, kurz erneut versuchen."""
        assert self.page
        letzter: PlaywrightError | None = None
        for versuch in range(8):
            f = self.page.frame(name="form") or self.page.frame(name="main")  # kann kurz fehlen
            if f is None:
                if versuch == 7:
                    self._inhaltsframe()  # wirft PortalFehler mit Hinweis auf Erreichbarkeit
                await self.page.wait_for_timeout(250)
                continue
            try:
                d = await f.evaluate(
                    """()=>{const fo=document.querySelector('form');const c=fo&&fo.querySelector('input[name=Command]');
                    return {n:fo?fo.getAttribute('name')||'':'',c:c?c.value:'',t:document.body?document.body.innerText:''}}"""
                )
                return Zustand(f, d["n"], d["c"], _normalisieren(d["t"]))
            except PlaywrightError as e:
                letzter = e
                await self.page.wait_for_timeout(250)
        assert letzter is not None
        raise PortalFehler(browserfehler_text("Lesen der Maske", str(letzter), self.protokoll.abgewiesene_dialoge)) from letzter

    async def _stabiler_zustand(self) -> Zustand:
        z = await self.zustand()
        if not z.command:  # Frame wurde mitten im Neuaufbau gelesen
            await self._warten()
            z = await self.zustand()
        return z

    async def _text(self, f: Frame, name: str, wert: str) -> None:
        loc = f.locator(f'form :is(input,textarea)[name="{name}"]')
        if await loc.count() != 1:
            raise PortalFehler(f"Feld {name} nicht eindeutig gefunden ({await loc.count()}x).")
        await loc.fill(wert)  # überschreibt Vorbelegungen wie '0,00 EUR'

    async def _auswahl(self, f: Frame, name: str, wert: str) -> None:
        loc = f.locator(f'form select[name="{name}"]')
        if await loc.count() != 1:
            raise PortalFehler(f"Auswahlliste {name} nicht gefunden.")
        if await loc.select_option(value=wert) != [wert]:
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

    async def _adresse(self, f: Frame, praefix: str, ad: Adresse | None, mit_strasse: bool = True) -> None:
        """Adressblock füllen. Felder heißen <praefix>Str/PLZ/Ort/Nation (z. B. _pv, _b, _gv)."""
        if mit_strasse:
            await self._text(f, f"{praefix}Str", ad.strasse if ad else "")
        await self._text(f, f"{praefix}PLZ", ad.plz if ad else "")
        await self._text(f, f"{praefix}Ort", ad.ort if ad else "")
        await self._text(f, f"{praefix}Nation", ad.auslandskennzeichen if ad else "")

    async def _knopf(self, f: Frame, name: str | None = None) -> None:
        """Absende-Knopf klicken: benannter Knopf der Maske oder der erste Weiter-Knopf."""
        sel = f'form input[type=image][name="{name}"]' if name else f'form input[type=image]:not([name="{KNOPF_NEUER_ANTRAG}"])'
        loc = f.locator(sel)
        if await loc.count() < 1:
            raise PortalFehler(f"Kein Knopf gefunden ({sel}).")
        await self._klicken_und_warten(loc.first.click)

    async def _link(self, f: Frame, command: str) -> None:
        loc = f.locator(f'a[href*="Command={command}"]')
        if await loc.count() < 1:
            raise PortalFehler(f"Link {command} nicht gefunden.")
        await self._klicken_und_warten(lambda: loc.first.evaluate("e=>e.click()"))

    # ------------------------------------------------------------------ Ablauf
    def _erlaubte_warnungen(self) -> list[str]:
        return erlaubte_warnungen(self.antrag)

    async def _absenden(self, z: Zustand, knopf: str | None = None) -> None:
        """Absenden und Text-Warnungen behandeln (gleiche Maske kommt mit 'Warnung:' zurück).

        Das Ergebnis jedes Klicks, auch des letzten Quittier-Klicks, wird gelesen, bevor aufgegeben wird.
        """
        await self._knopf(z.frame, knopf)
        quittiert = 0
        while True:
            neu = await self._stabiler_zustand()
            if neu.schluessel == z.schluessel and neu.fehler:
                raise PortalFehler("Das Portal meldet einen Fehler: " + " | ".join(neu.fehler))
            if neu.schluessel != z.schluessel or not neu.warnungen:
                return
            if quittiert >= MAX_QUITTIERUNGEN:
                raise PortalFehler(
                    f"Warnung ließ sich nicht quittieren ({quittiert}x unverändert erneut abgesendet): " + " | ".join(neu.warnungen)
                )
            unbekannt = unbekannte_warnungen(neu.warnungen, self._erlaubte_warnungen())
            if unbekannt:
                raise PortalFehler("Unbekannte oder nicht freigegebene Warnung des Portals: " + " | ".join(unbekannt))
            self.protokoll.quittierte_warnungen.extend(neu.warnungen)
            self.protokoll.add(f"Warnung quittiert in {z.schluessel}")
            quittiert += 1
            await self._knopf(neu.frame, knopf)  # unverändert erneut absenden = quittieren

    @_browserfehler_als_halt("Ausfüllen")
    async def ausfuellen(self, antrag: Antrag, sichtbar: bool) -> dict:
        self.antrag = antrag
        self.ablauf = Ablauf(
            abtretung_offen=antrag.ansprueche[0].abtretung is not None,
            zinsen_offen=antrag.ansprueche[0].zinsen is not None,
        )
        await self.oeffnen(sichtbar)
        assert self.page
        try:
            await self.page.goto(START_URL, wait_until="networkidle")
        except PlaywrightError as e:
            raise PortalFehler(browserfehler_text("Aufrufen von online-mahnantrag.de (Portal nicht erreichbar?)", str(e), [])) from e
        zustimmen = self.page.get_by_text("Ich stimme zu", exact=True)
        try:
            await self._klicken_und_warten(lambda: zustimmen.click(timeout=15_000))
        except PlaywrightError as e:
            raise PortalFehler(
                browserfehler_text("Bestätigen des Datenschutzhinweises ('Ich stimme zu')", str(e), self.protokoll.abgewiesene_dialoge)
            ) from e
        self.protokoll.add("Datenschutzhinweis bestätigt")
        return await self._lauf()

    @_browserfehler_als_halt("Fortsetzen")
    async def fortsetzen(self, prozessgericht_bestaetigt: str) -> dict:
        """Nach dem Haltepunkt Prozessgericht: Bestätigung übernehmen und weiterlaufen."""
        if not self.antrag or not self.page:
            raise PortalFehler("Keine offene Portal-Sitzung.")
        self._session_pruefen()
        self.antrag.entscheidungen.prozessgericht_bestaetigt = prozessgericht_bestaetigt
        return await self._lauf()

    async def _lauf(self) -> dict:
        gesehen: dict[str, int] = {}
        for _ in range(60):
            z = await self._stabiler_zustand()
            gesehen[z.schluessel] = gesehen.get(z.schluessel, 0) + 1
            if gesehen[z.schluessel] > 4:
                raise PortalFehler(f"Schleife erkannt in Maske {z.schluessel}. Bitte im Browser prüfen.")
            if z.schluessel == "MBUebersicht/saveMBAntragUebersicht":
                return await self._uebersicht_lesen(z)
            handler = self._handler_fuer(z)
            if handler is None:
                raise PortalFehler(
                    f"Unbekannte Maske {z.schluessel}. Der Ausfüller hält an; bitte im Browser prüfen.\n"
                    + _ausschnitt(z.text, "Antrag auf Erlass", 600)
                )
            self.protokoll.add(f"Maske {z.schluessel}")
            await handler(self, z)
        raise PortalFehler("Zu viele Schritte, Datenübersicht nicht erreicht.")

    def _handler_fuer(self, z: Zustand) -> Handler | None:
        return MASKEN.get(z.schluessel) or MASKEN_NACH_FORMULAR.get(z.formular)

    def _session_pruefen(self) -> None:
        minuten = self.minuten_seit_aktivitaet()
        if minuten is not None and minuten > SESSION_GRENZE.total_seconds() / 60:
            raise SessionAbgelaufen(
                f"Seit {minuten:.0f} Minuten keine Aktivität. Das Portal hat die Sitzung vermutlich beendet; "
                "bitte neu ausfüllen."
            )

    # ------------------------------------------------------------------ Masken-Handler
    async def _m_bundesland(self, z: Zustand) -> None:
        assert self.antrag and self.ablauf
        if self.ablauf.bundesland_gesendet:
            raise SessionAbgelaufen("Das Portal ist auf die Bundeslandauswahl zurückgefallen. Die Sitzung ist abgelaufen.")
        await self._auswahl(z.frame, "Bundesland", self.antrag.bundesland.value)
        self.ablauf.bundesland_gesendet = True
        await self._absenden(z)

    async def _m_versandart(self, z: Zustand) -> None:
        assert self.antrag
        await self._radio(z.frame, "_bVersandart", self.antrag.versandart.value)
        self.protokoll.add(f"Versandart {self.antrag.versandart.value}")
        await self._absenden(z)

    async def _m_neuer_antrag(self, z: Zustand) -> None:
        await self._knopf(z.frame, KNOPF_NEUER_ANTRAG)  # frischer Antrag in dieser Sitzung

    async def _m_fuer_wen(self, z: Zustand) -> None:
        assert self.antrag
        if self.antrag.rolle is Rolle.PROZESSBEVOLLMAECHTIGTER:
            loc = z.frame.locator(
                'a[href*="Command=holeProzessVertreter"]:not([href*="raInEigenerSache"]):has(img[src*="butt_weiter"])'
            )
            if await loc.count() != 1:
                raise PortalFehler("Weg 'Ich bin Prozessbevollmächtigter' nicht eindeutig gefunden.")
            await self._klicken_und_warten(lambda: loc.evaluate("e=>e.click()"))
        else:
            await self._knopf(z.frame, KNOPF_ICH_BIN_ANTRAGSTELLER)

    async def _m_prozessvertreter(self, z: Zustand) -> None:
        assert self.antrag
        pv = self.antrag.prozessbevollmaechtigter
        if pv is None:
            raise PortalFehler("Maske Prozessbevollmächtigter, aber im Antrag ist keiner angegeben.")
        f = z.frame
        await self._text(f, "_pvBeauftragungsdatum", fmt.datum(pv.beauftragungsdatum))
        await self._text(f, "_pvBetrag", fmt.betrag(pv.auslagen_statt_pauschale) if pv.auslagen_statt_pauschale else "")
        await self._haken(f, "_pvErklaerungVorsteuer", pv.antragsteller_nicht_vorsteuerabzugsberechtigt)
        await self._haken(f, "_pvUmsatzsteuerBefreit", pv.umsatzsteuerbefreit)
        await self._text(f, "_pvKennziffer", pv.kennziffer)
        await self._auswahl(f, "_pvTitelMM", PV_BEZEICHNUNG[pv.bezeichnung])
        await self._text(f, "_pvName1", pv.name)
        await self._adresse(f, "_pv", pv.adresse)
        await self._absenden(z)

    async def _m_antragsteller(self, z: Zustand) -> None:
        assert self.antrag
        await self._partei(z, self.antrag.antragsteller, "Antragsteller")

    async def _m_antragsgegner(self, z: Zustand) -> None:
        assert self.antrag
        await self._partei(z, self.antrag.antragsgegner, "Antragsgegner")

    async def _m_vertreter_as(self, z: Zustand) -> None:
        assert self.antrag
        await self._vertreter(z, self.antrag.antragsteller)

    async def _m_vertreter_ag(self, z: Zustand) -> None:
        assert self.antrag
        await self._vertreter(z, self.antrag.antragsgegner)

    async def _m_nein(self, z: Zustand) -> None:
        await self._knopf(z.frame, KNOPF_NEIN)  # v0.1: je ein Antragsteller, Antragsgegner, Vertreter

    async def _m_weiter(self, z: Zustand) -> None:
        await self._absenden(z)

    async def _m_verfahrensart(self, z: Zustand) -> None:
        assert self.antrag
        await self._radio(z.frame, "_bVerfahrensArt", self.antrag.verfahrensart)
        await self._absenden(z)

    async def _m_anspruch(self, z: Zustand) -> None:
        assert self.antrag
        f, anspruch = z.frame, self.antrag.ansprueche[0]
        await self._text(f, "KatNr", anspruch.katalog_nr)
        await self._auswahl(f, "_bKatalogArt", anspruch.katalog_nr)
        if anspruch.belegart:
            # Leere Belegart: Liste nicht anfassen, die Vorbelegung der frischen Maske ist leer (Spec 3.15).
            # Der Wert der Leeroption ist nicht belegt, deshalb wird er nicht ausgewählt (live ungeprüft).
            await self._auswahl(f, "_aspAspGr", anspruch.belegart)
        await self._text(f, "_aspAspGrZusatz", anspruch.belegart_zusatz)
        await self._text(f, "_bAspNr", anspruch.belegnummer)
        await self._text(f, "_bVon", fmt.datum(anspruch.datum_von))
        await self._text(f, "_bBis", fmt.datum(anspruch.datum_bis))
        await self._text(f, "_bBetrag", fmt.betrag(anspruch.betrag))
        await self._haken(f, "MehrVerbrKreditGesetz", anspruch.verbraucherkredit)
        await self._absenden(z)

    async def _m_anspruch_weiter(self, z: Zustand) -> None:
        assert self.ablauf
        wahl = "Abtretung" if self.ablauf.abtretung_offen else "Zinsen" if self.ablauf.zinsen_offen else "Weiter"
        await self._radio(z.frame, "MehrAbtretungZinsenAnspruch", wahl)
        await self._absenden(z)

    async def _m_abtretung(self, z: Zustand) -> None:
        assert self.antrag and self.ablauf
        if not self.ablauf.abtretung_offen:
            raise PortalFehler("Abtretungsmaske erneut geöffnet, obwohl schon erfasst.")
        abtretung = self.antrag.ansprueche[0].abtretung
        assert abtretung
        f = z.frame
        await self._text(f, "_bName1", abtretung.frueherer_glaeubiger)
        await self._adresse(
            f, "_b", Adresse(strasse="-", plz=abtretung.plz, ort=abtretung.ort, auslandskennzeichen=abtretung.auslandskennzeichen),
            mit_strasse=False,
        )
        await self._text(f, "_bAbgetretenAm", fmt.datum(abtretung.datum))
        await self._absenden(z)
        self.ablauf.abtretung_offen = False

    async def _m_zinsen(self, z: Zustand) -> None:
        assert self.antrag and self.ablauf
        if not self.ablauf.zinsen_offen:
            # Erneutes Öffnen legt einen Doppeleintrag an (Falle 9). Nicht absenden.
            raise PortalFehler("Zinsmaske erneut geöffnet, obwohl Zinsen schon erfasst sind. Abbruch gegen Doppeleintrag.")
        zinsen = self.antrag.ansprueche[0].zinsen
        assert zinsen
        f = z.frame
        await self._text(f, "_bZinssatz", fmt.zinssatz(zinsen.zinssatz))
        await self._haken(f, "_bUeberBasisZinssatz", zinsen.ueber_basiszins)
        await self._auswahl(f, "_bZinssatzJMT", ZINS_TURNUS[zinsen.turnus])
        await self._text(f, "_bBasisBetrag", fmt.betrag(zinsen.zu_verzinsender_betrag) if zinsen.zu_verzinsender_betrag else "")
        await self._text(f, "_bVon", fmt.datum(zinsen.ab))
        await self._text(f, "_bBis", fmt.datum(zinsen.bis))
        await self._absenden(z)
        self.ablauf.zinsen_offen = False

    async def _m_auslagen(self, z: Zustand) -> None:
        assert self.antrag
        f, auslagen = z.frame, self.antrag.auslagen
        if auslagen:
            await self._text(f, "_bVordruckPorto", fmt.betrag(auslagen.vordruck_porto))
            if auslagen.sonstige_auslage_art:
                await self._auswahl(f, "liste1", auslagen.sonstige_auslage_art)
            await self._text(f, "_bSonstBetrag", fmt.betrag(auslagen.sonstige_auslage_betrag))
            await self._text(f, "_bSonstBezeichnung", auslagen.sonstige_auslage_bezeichnung)
            for praefix, nebenforderung in [
                ("_bMahnKosten", auslagen.mahnkosten),
                ("_bAuskunftsKosten", auslagen.auskunftskosten),
                ("_bBankruecklastKosten", auslagen.bankruecklastkosten),
                ("_bInkassoKosten", auslagen.inkassokosten),
                ("_bVorgerAnwaltsverguetung", auslagen.vorgerichtliche_anwaltsverguetung),
            ]:
                if nebenforderung:
                    await self._text(f, praefix, fmt.betrag(nebenforderung.betrag))
                    if nebenforderung.zinssatz is not None:
                        await self._text(f, f"{praefix}Zins", fmt.zinssatz(nebenforderung.zinssatz))
                        await self._haken(f, f"{praefix}ZinsUeberBasis", nebenforderung.zins_ueber_basiszins)
                        await self._text(f, f"{praefix}ZinsVon", fmt.datum(nebenforderung.zins_ab))
                        await self._text(f, f"{praefix}ZinsBis", fmt.datum(nebenforderung.zins_bis))
            await self._text(f, "_bVorgerStreitwert", fmt.betrag(auslagen.vorgerichtlicher_gegenstandswert))
            await self._haken(f, "_bVorgerUmfangreich", auslagen.vorgerichtlich_umfangreich)
            await self._text(f, "_bVorgerMinderungsbetrag", fmt.betrag(auslagen.anrechnungsbetrag_3305))
        await self._absenden(z)

    async def _m_verguetung(self, z: Zustand) -> None:
        assert self.antrag
        e = self.antrag.entscheidungen
        if not e.verguetung_mahnverfahren:
            raise PortalFehler("Vergütung im Mahnverfahren nicht entschieden.")
        await self._radio(z.frame, "_bVerguetungMM", e.verguetung_mahnverfahren.upper())
        await self._text(z.frame, "_bVerguetungBetrag", verguetung_betrag_feld(e.verguetung_mahnverfahren, e.verguetung_vereinbart_betrag))
        await self._absenden(z)

    async def _m_prozessgericht(self, z: Zustand) -> None:
        """Haltepunkt § 35 ZPO: nur weiter, wenn der Mensch genau dieses Gericht bestätigt hat."""
        assert self.antrag
        gefunden = prozessgericht_aus_text(z.text)
        bestaetigt = self.antrag.entscheidungen.prozessgericht_bestaetigt
        if not gefunden:
            raise PortalFehler("Prozessgericht in der Maske nicht erkannt. Bitte im Browser prüfen.")
        if not gericht_passt(bestaetigt, gefunden):
            raise GerichtBestaetigen(gefunden, bestaetigt)
        self.protokoll.add(f"Prozessgericht bestätigt: {gefunden}")
        await self._absenden(z)

    async def _m_allgemeine_angaben(self, z: Zustand) -> None:
        assert self.antrag
        f, e = z.frame, self.antrag.entscheidungen
        await self._text(f, "_bAntragstellerGeschaeftszeichen", self.antrag.geschaeftszeichen)
        await self._haken(f, "_bErklaerungVorGegenLeistung1", e.gegenleistung == "bereits_erbracht")
        await self._haken(f, "_bErklaerungVorGegenLeistung2", e.gegenleistung == "nicht_abhaengig")
        await self._haken(f, "_bErklaerungStreitVerfahren", e.streitiges_verfahren_bei_widerspruch)
        await self._absenden(z)

    async def _m_bank(self, z: Zustand) -> None:
        assert self.antrag
        f, bank = z.frame, self.antrag.bankverbindung
        await self._text(f, "_bIban", re.sub(r"\s+", "", bank.iban) if bank else "")
        await self._text(f, "_bBic", bank.bic if bank else "")
        if bank:
            await self._auswahl(f, "_bKontoZuordnung", "2" if bank.kontoinhaber == "prozessbevollmaechtigter" else "1")
        await self._absenden(z)

    # ------------------------------------------------------------------ Parteien
    async def _partei(self, z: Zustand, partei: NatuerlichePerson | Firma, rolle: str) -> None:
        f = z.frame
        soll_formular = "Firma" if isinstance(partei, Firma) else "NatuerlichePerson"
        if z.formular != soll_formular:
            await self._link(f, REITER[(rolle, type(partei))])  # Reiter wechseln, nächste Runde füllt
            return
        if isinstance(partei, NatuerlichePerson):
            await self._auswahl(f, "_bAnrede", "1" if partei.anrede == "Herr" else "2")
            await self._text(f, "_bName1", partei.vorname)
            await self._text(f, "_bName2", partei.nachname)
            if rolle == "Antragsgegner":
                assert self.antrag
                await self._haken(f, "_bNatoTruppenstatut", self.antrag.antragsgegner_nato_truppenstatut)
        else:
            zeilen = partei.name_zeilen + [""] * (4 - len(partei.name_zeilen))
            for i, zeile in enumerate(zeilen, 1):
                await self._text(f, f"_bName{i}", zeile)
            await self._auswahl(f, "_bRechtsform", partei.rechtsform_code)
        await self._adresse(f, "_b", partei.adresse)
        await self._absenden(z)

    async def _vertreter(self, z: Zustand, partei: NatuerlichePerson | Firma) -> None:
        if not isinstance(partei, Firma) or not partei.gesetzliche_vertreter:
            raise PortalFehler(f"Maske {z.schluessel} erwartet einen gesetzlichen Vertreter, im Antrag ist keiner.")
        vertreter = partei.gesetzliche_vertreter[0]
        await self._auswahl(z.frame, "_gvVertreterFunktion", VERTRETER_FUNKTION[vertreter.funktion])
        await self._text(z.frame, "_gvName1", vertreter.name)
        await self._adresse(z.frame, "_gv", vertreter.adresse)
        await self._absenden(z)

    # ------------------------------------------------------------------ Übersicht und Download
    async def _fehler_da(self, z: Zustand) -> str | None:
        return await z.frame.evaluate("()=>{const e=document.querySelector('input[name=FehlerDa]');return e?e.value:null}")

    async def _uebersicht_lesen(self, z: Zustand) -> dict:
        fehler_da = await self._fehler_da(z)
        self.protokoll.add(f"Datenübersicht erreicht (FehlerDa={fehler_da})")
        sperrgrund = download_sperrgrund(z.formular, z.command, fehler_da, z.warnungen, self._erlaubte_warnungen())
        return {
            "status": "datenuebersicht",
            "fehler_da": fehler_da,
            "offene_warnungen": z.warnungen,
            "download_moeglich": sperrgrund is None,
            "download_sperrgrund": sperrgrund,
            "uebersicht": uebersicht_text(z.text),  # vollständig, nie gekürzt: der Mensch gibt genau das frei
            "hinweis": (
                "Der Ausfüller hat auf der Datenübersicht angehalten. Bitte die Übersicht prüfen. "
                "Checkbox-Zustände (Erklärungen) sind dort nicht ablesbar; sie stehen im eigenen Antrag. "
                f"Das Portal beendet die Sitzung nach rund 30 Minuten ohne Aktivität."
            ),
            "protokoll": self.protokoll.schritte,
            "quittierte_warnungen": self.protokoll.quittierte_warnungen,
            "dialoge": self.protokoll.dialoge,
        }

    @_browserfehler_als_halt("EDA-Download")
    async def eda_herunterladen(self, zielordner: Path) -> dict:
        if not self.antrag or self.antrag.versandart is not Versandart.EDA:
            raise PortalFehler("Download gibt es nur für Versandart EDA-Download.")
        self._session_pruefen()
        z = await self._stabiler_zustand()
        if z.formular == "Bundesland":
            raise SessionAbgelaufen("Das Portal ist auf die Bundeslandauswahl zurückgefallen. Die Sitzung ist abgelaufen.")
        sperrgrund = download_sperrgrund(z.formular, z.command, await self._fehler_da(z), z.warnungen, self._erlaubte_warnungen())
        if sperrgrund:
            raise PortalFehler(sperrgrund)
        # Ablageordner vor dem ersten Klick anlegen und prüfen: nach dem Speichern-Klick ist der Download verbraucht.
        ordner = ablageordner_anlegen(zielordner, self.antrag.geschaeftszeichen, datetime.now())
        try:
            return await self._eda_abholen(z, ordner)
        except BaseException:
            _leeren_ordner_entfernen(ordner)
            raise

    async def _eda_abholen(self, z: Zustand, ordner: Path) -> dict:
        assert self.antrag
        await self._knopf(z.frame)  # wartet auf ein neues Dokument, nicht auf die stehende Übersicht
        z = await self._stabiler_zustand()
        if z.formular == "Bundesland":
            raise SessionAbgelaufen("Das Portal ist auf die Bundeslandauswahl zurückgefallen. Die Sitzung ist abgelaufen.")
        if z.formular != "AbgabeEDA":
            raise PortalFehler(f"Erwartet: Abgabemaske EDA, gefunden: {z.schluessel}.")
        haken = z.frame.locator('form input[type=checkbox][name="hinweisGelesen"]')
        if await haken.count() != 1:
            raise PortalFehler("Bestätigung 'hinweisGelesen' nicht gefunden.")
        await haken.check()  # Pflicht-Gate, sonst blockierender alert()
        assert self.page
        dialoge_vorher = len(self.protokoll.abgewiesene_dialoge)
        try:
            async with self.page.expect_download(timeout=60_000) as dl_info:
                await z.frame.locator('form input[type=image][src*="butt_speichern"]').first.click()
            download = await dl_info.value
        except PlaywrightError as e:
            raise PortalFehler(
                download_fehlertext(str(e), self.protokoll.abgewiesene_dialoge[dialoge_vorher:])
            ) from e
        # Portal-Dateinamen nie ändern (z. B. EDA_MBA_09_11_2026_930208_<32 Hex>.eda, live belegt 09.11.2026).
        # Zuordnung zum Fall über den Unterordner je Geschäftszeichen und Zeitpunkt.
        ziel = ordner / Path(download.suggested_filename).name
        try:
            await download.save_as(ziel)
            sha = hashlib.sha256(ziel.read_bytes()).hexdigest()
            ziel.chmod(0o444)  # schreibgeschützt: die Datei darf nicht verändert werden
        except (OSError, PlaywrightError) as e:
            raise PortalFehler(
                f"Die EDA-Datei kam an, ließ sich aber nicht unter {ziel} speichern ({e.__class__.__name__}: "
                f"{str(e).strip().splitlines()[0] if str(e).strip() else 'ohne Meldung'}). Browser bleibt offen; "
                "die Datei im Browser-Downloadbereich prüfen, bevor portal_schliessen aufgerufen wird."
            ) from e
        self.letzte_aktivitaet = datetime.now()
        self.protokoll.add(f"EDA-Datei gespeichert: {ziel.name} sha256={sha}")
        return {
            "datei": str(ziel),
            "portal_dateiname": download.suggested_filename,
            "groesse_bytes": ziel.stat().st_size,
            "sha256": sha,
            "hinweis": (
                "Datei unverändert über einen sicheren Übermittlungsweg (beA) an das zuständige Mahngericht senden. "
                "Nicht bearbeiten und nicht umbenennen; nicht zusätzlich als Barcode einreichen."
            ),
        }


# Maske -> Handler. Schlüssel ist "Formularname/Command"; wo der Command nichtssagend ist
# (display, wechselnde Commands), entscheidet der Formularname.
MASKEN: dict[str, Handler] = {
    "Bundesland/saveBundesland": PortalSitzung._m_bundesland,
    "Antragsart/saveVersandart": PortalSitzung._m_versandart,
    "NeuerMBAntrag/neuerMBAntrag": PortalSitzung._m_neuer_antrag,
    "PVJaNein/leereViewDocumentASundShowAS": PortalSitzung._m_fuer_wen,
    "ProzessVertreter/saveProzessVertreter": PortalSitzung._m_prozessvertreter,
    "NatuerlichePerson/saveAntragstellerNatPers": PortalSitzung._m_antragsteller,
    "Firma/saveAntragstellerFirma": PortalSitzung._m_antragsteller,
    "NatuerlichePerson/saveAntragsgegnerNatPers": PortalSitzung._m_antragsgegner,
    "Firma/saveAntragsgegnerFirma": PortalSitzung._m_antragsgegner,
    "AntragstellerGV/saveAntragstellerGV": PortalSitzung._m_vertreter_as,
    "AntragsgegnerGV/saveAntragsgegnerGV": PortalSitzung._m_vertreter_ag,
    "GasamtschuldnerJaNein/saveErklaerungAuslaendischeRechtsformAS": PortalSitzung._m_weiter,  # Schreibfehler stammt aus dem Portal
    "VerfahrensArt/saveVerfahrensArt": PortalSitzung._m_verfahrensart,
    "KatAnspruch/saveKatAnspruch": PortalSitzung._m_anspruch,
    "mehrDiverses/anspruchWeiter": PortalSitzung._m_anspruch_weiter,
    "Auslagen/saveAuslagenNebenforderungen": PortalSitzung._m_auslagen,
    "ProzessVertreter/saveProzessVertreterVerguetung": PortalSitzung._m_verguetung,
    "Allg/showAllgemeineAngaben": PortalSitzung._m_prozessgericht,  # live belegt 09.11.2026
    "Allg/saveAllgemeineAngaben": PortalSitzung._m_allgemeine_angaben,  # live belegt 09.11.2026
    "BankVerbindung/saveBankVerbindung": PortalSitzung._m_bank,
}
MASKEN_NACH_FORMULAR: dict[str, Handler] = {
    "mehrASGV": PortalSitzung._m_nein,
    "mehrAS": PortalSitzung._m_nein,
    "mehrAGGV": PortalSitzung._m_nein,
    "mehrAG": PortalSitzung._m_nein,
    "Abtretung": PortalSitzung._m_abtretung,
    "LaufendeZinsen": PortalSitzung._m_zinsen,
}
