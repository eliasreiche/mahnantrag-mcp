"""Datenmodell eines Mahnbescheidsantrags (Umfang v0.1).

Das Modell bildet nur ab, was der Portal-Ausfüller sicher bedienen kann. Alles andere
(mehrere Antragsgegner, sonstige Ansprüche, manuelle Gerichtswahl …) lehnt der
Validator ab, statt es halb auszufüllen.

Beträge und Zinssätze sind Decimal, Daten sind date. Die Portal-Formate
("1.234,56 EUR", "9,000 %", "TT.MM.JJJJ") erzeugt erst format.py.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Basis(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Bundesland(str, Enum):
    BW = "BW"
    BAY = "BAY"
    BER = "BER"
    BRB = "BRB"
    HB = "HB"
    HH = "HH"
    HES = "HES"
    MBV = "MBV"
    NDS = "NDS"
    NRW = "NRW"
    RPF = "RPF"
    SLD = "SLD"
    SAC = "SAC"
    SAH = "SAH"
    SH = "SH"
    THU = "THU"


class Versandart(str, Enum):
    EDA = "EDA-Download"
    BARCODE = "Barcode"


class Rolle(str, Enum):
    """Für wen der Antrag erfasst wird (Maske 'Für wen erfassen Sie diesen Antrag?')."""

    PROZESSBEVOLLMAECHTIGTER = "prozessbevollmaechtigter"
    ANTRAGSTELLER = "antragsteller"


class Adresse(_Basis):
    strasse: str = Field(description="Straße und Hausnummer, max. 35 Zeichen")
    plz: str = Field(description="Postleitzahl; bei Inland genau 5 Ziffern")
    ort: str = Field(description="Ort, max. 27 Zeichen")
    auslandskennzeichen: str = Field("", description="Nur bei Auslandsadresse, max. 3 Zeichen, z. B. 'A' oder 'NL'")


class NatuerlichePerson(_Basis):
    art: Literal["person"] = "person"
    anrede: Literal["Herr", "Frau"]
    vorname: str
    nachname: str
    adresse: Adresse


class GesetzlicherVertreter(_Basis):
    funktion: Literal[
        "Geschäftsführer",
        "Geschäftsführerin",
        "Geschäftsführender Gesellschafter",
        "Geschäftsführende Gesellschafterin",
        "Managing Director",
    ]
    name: str = Field(description="Vor- und Nachname, max. 35 Zeichen")
    adresse: Adresse | None = Field(None, description="Nur angeben, wenn abweichend von der Firmenanschrift")


class Firma(_Basis):
    art: Literal["firma"] = "firma"
    name_zeilen: list[str] = Field(
        min_length=1,
        max_length=4,
        description=(
            "Vollständiger Firmenname einschließlich Rechtsformzusatz, je Zeile max. 35 Zeichen. "
            "Den Umbruch legt der Mensch fest, weil er so im Bescheid erscheint."
        ),
    )
    rechtsform_code: str = Field(description="Code aus dem Rechtsform-Katalog, z. B. '3' = GmbH")
    adresse: Adresse
    gesetzliche_vertreter: list[GesetzlicherVertreter] = Field(default_factory=list)


Partei = Annotated[NatuerlichePerson | Firma, Field(discriminator="art")]


class Prozessbevollmaechtigter(_Basis):
    """Reiter 'Rechtsanwalt/-beistand'. Andere Reiter (RA-Gesellschaft, Inkasso …) sind in v0.1 nicht unterstützt."""

    bezeichnung: Literal["Rechtsanwalt", "Rechtsanwälte", "Rechtsbeistand", "Rechtsanwältin", "Rechtsanwältinnen"]
    name: str = Field(description="Vor- und Nachname bzw. Kanzleibezeichnung, max. 105 Zeichen")
    adresse: Adresse | None = Field(None, description="Pflicht, wenn keine Kennziffer angegeben ist")
    kennziffer: str = Field("", description="Prozessvertreter-Kennziffer des Mahngerichts, 8 Ziffern (optional)")
    beauftragungsdatum: date | None = None
    auslagen_statt_pauschale: Decimal | None = Field(
        None, description="Nur wenn statt der Pauschale Nr. 7002 VV RVG konkrete Auslagen verlangt werden"
    )
    antragsteller_nicht_vorsteuerabzugsberechtigt: bool = False
    umsatzsteuerbefreit: bool = False


class Abtretung(_Basis):
    frueherer_glaeubiger: str = Field(description="Name, max. 35 Zeichen, nur eine Zeile")
    plz: str
    ort: str
    auslandskennzeichen: str = ""
    datum: date


class LaufendeZinsen(_Basis):
    zinssatz: Decimal = Field(description="Prozentsatz bzw. Prozentpunkte, z. B. 9 für '9 Punkte über Basiszins'")
    ueber_basiszins: bool = Field(description="True = Prozentpunkte über dem Basiszinssatz (§ 288 BGB)")
    turnus: Literal["jaehrlich", "monatlich", "taeglich"] = "jaehrlich"
    ab: date
    bis: date | None = Field(None, description="Leer = bis Zustellung des Mahnbescheids bzw. laufend")
    zu_verzinsender_betrag: Decimal | None = Field(None, description="Nur wenn abweichend von der Hauptforderung")


class Anspruch(_Basis):
    katalog_nr: str = Field(description="Nummer aus dem Anspruchskatalog, z. B. '11' = Kaufvertrag")
    belegart: str = Field("", description="Wert aus dem Belegarten-Katalog, z. B. 'Rechnung'")
    belegart_zusatz: str = ""
    belegnummer: str = Field("", description="Rechnungs-/Vertragsnummer, max. 35 Zeichen")
    datum_von: date = Field(description="Datum bzw. Beginn des Zeitraums")
    datum_bis: date | None = None
    betrag: Decimal
    verbraucherkredit: bool = False
    abtretung: Abtretung | None = None
    zinsen: LaufendeZinsen | None = None


class Nebenforderung(_Basis):
    betrag: Decimal
    zinssatz: Decimal | None = None
    zins_ueber_basiszins: bool = False
    zins_ab: date | None = None
    zins_bis: date | None = None


class AuslagenNebenforderungen(_Basis):
    vordruck_porto: Decimal | None = None
    sonstige_auslage_art: str = Field("", description="Wert aus der Auslagenliste, z. B. 'Verzugspauschale § 288 Abs. 5 BGB'")
    sonstige_auslage_betrag: Decimal | None = None
    sonstige_auslage_bezeichnung: str = Field("", description="Begründung der Auslage, max. 35 Zeichen; vom Portal für jede Auslagenart verlangt")
    mahnkosten: Nebenforderung | None = None
    auskunftskosten: Nebenforderung | None = None
    bankruecklastkosten: Nebenforderung | None = None
    inkassokosten: Nebenforderung | None = None
    vorgerichtliche_anwaltsverguetung: Nebenforderung | None = None
    vorgerichtlicher_gegenstandswert: Decimal | None = None
    vorgerichtlich_umfangreich: bool = False
    anrechnungsbetrag_3305: Decimal | None = None


class Bankverbindung(_Basis):
    iban: str
    bic: str = ""
    kontoinhaber: Literal["antragsteller", "prozessbevollmaechtigter"] = "antragsteller"


class Entscheidungen(_Basis):
    """Rechtliche Weichen, die der Mensch ausdrücklich treffen muss. Kein Default."""

    gegenleistung: Literal["nicht_abhaengig", "bereits_erbracht"] = Field(
        description="§ 690 Abs. 1 Nr. 4 ZPO: Anspruch hängt nicht von einer Gegenleistung ab / Gegenleistung ist erbracht"
    )
    streitiges_verfahren_bei_widerspruch: bool = Field(
        description="Im Falle eines Widerspruchs automatisch Durchführung des streitigen Verfahrens beantragen"
    )
    verguetung_mahnverfahren: Literal["gesetzlich", "vereinbart", "verzicht"] | None = Field(
        None, description="Nur bei Prozessbevollmächtigtem: Vergütung im Mahnbescheid"
    )
    verguetung_vereinbart_betrag: Decimal | None = None
    einreichung_durch_berufstraeger: bool = Field(
        description=(
            "Stellt eine Rechtsanwältin/ein Rechtsanwalt, eine Behörde oder ein registrierter Inkassodienstleister "
            "den Antrag, auch in eigener Sache? Dann ist nur die elektronische Einreichung zulässig (§ 702 Abs. 2, § 130d ZPO)."
        )
    )
    vorgerichtliche_anwaltsverguetung: Literal["keine", "als_hauptforderung", "als_nebenforderung"] = Field(
        description=(
            "Wie die vorgerichtliche Anwaltsvergütung geltend gemacht wird: gar nicht, als Hauptforderung "
            "(Kat.-Nr. 24 oder 71) oder als Nebenforderung. Nie beides, sonst verdoppelt sich die Forderung."
        )
    )
    vorgerichtlich_ohne_verguetung_bestaetigt: bool | None = Field(
        None,
        description=(
            "Soll ein Gegenstandswert der vorgerichtlichen Tätigkeit oder ein Anrechnungsbetrag (Nr. 3305 VV RVG) "
            "angegeben werden, ohne dass eine vorgerichtliche Anwaltsvergütung geltend gemacht wird? Pflicht, wenn "
            "die Antragsdaten das ergeben. Das Portal warnt dann; der Ausfüller quittiert diese Warnung nur bei true."
        ),
    )
    verbraucher_beteiligt: bool | None = Field(
        None,
        description=(
            "Ist an dem Rechtsgeschäft ein Verbraucher beteiligt (§ 288 Abs. 2 BGB)? Pflicht, wenn mehr als "
            "5 Prozentpunkte über dem Basiszinssatz verlangt werden (auch bei mehr als 9 Punkten)."
        ),
    )
    prozessgericht_bestaetigt: str = Field(
        "",
        description=(
            "Name des Prozessgerichts, das der Mensch bestätigt hat, nachdem der Ausfüller es angezeigt hat "
            "(z. B. 'Amtsgericht München'). Leer = der Ausfüller hält an der Prozessgericht-Maske an und zeigt "
            "das vom Portal abgeleitete Gericht. Weiterklicken gilt als Wahl nach § 35 ZPO."
        ),
    )
    barcode_glaubhaftmachung: str = Field(
        "",
        description="Nur Anwälte mit Barcode-Weg: Begründung, warum elektronische Einreichung vorübergehend unmöglich ist (§ 130d S. 2, 3 ZPO)",
    )


class Antrag(_Basis):
    bundesland: Bundesland = Field(description="Sitz/Wohnsitz des Antragstellers; Ausland -> BER")
    versandart: Versandart
    rolle: Rolle
    prozessbevollmaechtigter: Prozessbevollmaechtigter | None = None
    antragsteller: Partei
    antragsgegner: Partei
    verfahrensart: Literal["NMV", "UMV", "SMV", "WMV"] = "NMV"
    ansprueche: list[Anspruch] = Field(min_length=1)
    auslagen: AuslagenNebenforderungen | None = None
    geschaeftszeichen: str = Field("", description="Eigenes Aktenzeichen, max. 35 Zeichen; einziger Schlüssel für Rückläufer")
    bankverbindung: Bankverbindung | None = None
    antragsgegner_nato_truppenstatut: bool = False
    entscheidungen: Entscheidungen
