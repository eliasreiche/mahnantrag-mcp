"""Erzeugt die Katalog-JSONs aus docs/referenz (mahnantrag-portal-reference, CC BY 4.0)."""
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "docs" / "referenz"
OUT = ROOT / "src" / "mahnantrag_mcp" / "daten"


def tabelle(text: str, abschnitt_start: str | None = None, abschnitt_ende: str | None = None):
    if abschnitt_start:
        text = text.split(abschnitt_start, 1)[1]
    if abschnitt_ende and abschnitt_ende in text:
        text = text.split(abschnitt_ende, 1)[0]
    zeilen = []
    for z in text.splitlines():
        m = re.match(r"^\|\s*`?([^|`]+?)`?\s*\|\s*(.+?)\s*\|$", z)
        if not m or m.group(1) in ("Code", "Wert") or set(m.group(1)) <= set("-"):
            continue
        zeilen.append((m.group(1).strip(), m.group(2).strip()))
    return zeilen


a = (REF / "anspruchskatalog.md").read_text()
ansprueche = {k: v for k, v in tabelle(a, None, "## Katalog `_aspAspGr`") if k.isdigit()}
belegarten = {k: re.sub(r"\s*&nbsp;.*$", "", v) for k, v in tabelle(a, "## Katalog `_aspAspGr`") if k != "(leer)"}
r = (REF / "rechtsform-katalog.md").read_text()
rechtsformen = {k: v for k, v in tabelle(r) if k.isdigit() and k != "0"}

OUT.mkdir(parents=True, exist_ok=True)
for name, d in [("anspruchsarten", ansprueche), ("belegarten", belegarten), ("rechtsformen", rechtsformen)]:
    (OUT / f"{name}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n")
    print(name, len(d))
