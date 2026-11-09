"""Portal-Formate: Beträge '1.234,56 EUR', Zinssätze '9,000 %', Daten 'TT.MM.JJJJ'."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal


def betrag(wert: Decimal | None) -> str:
    """Decimal -> '1.234,56 EUR'. None -> '0,00 EUR' (Vorbelegung des Portals)."""
    if wert is None:
        wert = Decimal("0")
    q = Decimal(wert).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    vorzeichen = "-" if q < 0 else ""
    ganz, nach = f"{abs(q):.2f}".split(".")
    gruppen = []
    while len(ganz) > 3:
        gruppen.insert(0, ganz[-3:])
        ganz = ganz[:-3]
    gruppen.insert(0, ganz)
    return f"{vorzeichen}{'.'.join(gruppen)},{nach} EUR"


def zinssatz(wert: Decimal | None) -> str:
    """Decimal -> '9,000 %'."""
    if wert is None:
        wert = Decimal("0")
    q = Decimal(wert).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return f"{q:.3f}".replace(".", ",") + " %"


def datum(wert: date | None) -> str:
    return wert.strftime("%d.%m.%Y") if wert else ""
