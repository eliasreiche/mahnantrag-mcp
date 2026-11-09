"""Kataloge des Online-Mahnantrags.

Quelle: nbindewald-legal/mahnantrag-portal-reference (CC BY 4.0), siehe NOTICE.
Neu erzeugen mit scripts/kataloge_erzeugen.py.
"""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files

AUSLAGEN_ARTEN = [
    "Akteneinsichtsgebühr",
    "Auskunft Vollstreckungsportal",
    "Einstellung der Versorgung",
    "EMA-Anfrage",
    "Fahrtkosten",
    "Gangkosten/Sperrkosten",
    "Gebühren für Gütestelle",
    "Gerichtsvollzieherkosten",
    "Gewerbeamtsanfrage",
    "HR-Auskunft",
    "Kontoführungskosten",
    "Kopien",
    "Kosten Vollstreckungsportal",
    "Pauschale § 288 Abs. 5 BGB",
    "Postanfrage",
    "Schreibkosten",
    "Schufakosten",
    "Servicepauschale gem. Vereinbarung",
    "Telefax",
    "Telefon",
    "Versandkosten",
    "Verzugspauschale § 288 Abs. 5 BGB",
    "Sonstiger",
]

VERTRETER_FUNKTION = {
    "Geschäftsführende Gesellschafterin": "47",
    "Geschäftsführender Gesellschafter": "49",
    "Geschäftsführer": "52",
    "Geschäftsführerin": "53",
    "Managing Director": "219",
}

PV_BEZEICHNUNG = {
    "Rechtsanwalt": "1",
    "Rechtsanwälte": "2",
    "Rechtsbeistand": "3",
    "Rechtsanwältin": "5",
    "Rechtsanwältinnen": "6",
}


@cache
def _laden(name: str) -> dict[str, str]:
    return json.loads(files("mahnantrag_mcp.daten").joinpath(f"{name}.json").read_text(encoding="utf-8"))


def anspruchsarten() -> dict[str, str]:
    return _laden("anspruchsarten")


def rechtsformen() -> dict[str, str]:
    return _laden("rechtsformen")


def belegarten() -> dict[str, str]:
    return _laden("belegarten")


def suchen(katalog: str, begriff: str = "") -> dict[str, str]:
    quelle = {
        "anspruchsart": anspruchsarten,
        "rechtsform": rechtsformen,
        "belegart": belegarten,
        "auslage": lambda: {a: a for a in AUSLAGEN_ARTEN},
    }[katalog]()
    b = begriff.casefold().strip()
    return {k: v for k, v in quelle.items() if not b or b in v.casefold() or b == k.casefold()}
