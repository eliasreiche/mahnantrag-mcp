# mahnantrag-mcp

MCP-Server (und Claude-Plugin), mit dem Claude einen **Antrag auf Erlass eines Mahnbescheids** über
[online-mahnantrag.de](https://www.online-mahnantrag.de) vorbereitet:

1. **Vorprüfung** – deterministisch, bevor das Portal den Antrag sieht
2. **Ausfüllen** des Portals bis zur Datenübersicht – im sichtbaren Browser, Mensch kann jederzeit übernehmen.
   Haltepunkt am **Prozessgericht**: das Portal leitet es aus der Gegneranschrift ab, Weiterklicken gilt als
   Wahl nach § 35 ZPO. Der Ausfüller zeigt das Gericht und macht erst nach Bestätigung weiter.
3. **EDA-Download** – erst nach ausdrücklicher Freigabe und nur, wenn die Datenübersicht keine Fehler
   (`FehlerDa`) und keine offenen Warnungen zeigt; Datei wird schreibgeschützt gespeichert und gehasht

**Eingereicht wird nie durch diesen Server.** Die EDA-Datei geht unverändert über einen sicheren
Übermittlungsweg (beA, § 130a Abs. 4 ZPO) an das Mahngericht. Das macht der Mensch.

> Status: **v0.1, Work-in-Progress.** Ende-zu-Ende gegen das Live-Portal getestet (09.11.2026, Fantasiedaten),
> einschließlich EDA-Download. Eine echte Einreichung beim Mahngericht ist noch nicht erprobt.

## Warum eine Vorprüfung?

Das Portal prüft fast nichts. Vierstellige PLZ, eine weibliche Vertreterfunktion zu einem männlichen
Namen oder eine doppelt eingetragene vorgerichtliche Anwaltsvergütung gehen ohne Meldung durch.
`antrag_pruefen` fängt unter anderem ab:

- Feldlängen des Portals (Firmenname 35 Zeichen je Zeile, Ort 27, Kennziffer 8 Ziffern …)
- Einzelunternehmen: Das Portal bildet sie nicht eigens ab. Auf Wunsch wird der Inhaber als natürliche Person
  erfasst und die Geschäftsbezeichnung hinter den Nachnamen gesetzt (`geschaeftsbezeichnung`, zusammen höchstens
  35 Zeichen). Das ist ein Praxishinweis, keine Vorgabe; Claude fragt vorher, ob es so gehandhabt werden soll
- Katalogcodes (75 Anspruchsarten, 178 Rechtsformen, Belegarten, Auslagenarten)
- PLZ, IBAN-Prüfziffer, Daten in der Zukunft
- vorgerichtliche Anwaltsvergütung als Haupt- **und** Nebenforderung (verdoppelt die Forderung)
- Barcode-Weg für Rechtsanwälte nur mit Glaubhaftmachung (§ 130d S. 2, 3 ZPO)
- mehr als 5 Punkte über Basiszins ohne Entscheidung zur Verbraucherbeteiligung (§ 288 Abs. 1 vs. 2 BGB)
- Kosten des Mahnverfahrens als Auslage (§ 699 Abs. 3 ZPO)
- rechtliche Weichen, die ausdrücklich entschieden sein müssen: Gegenleistung, streitiges Verfahren,
  Vergütung, Einreichung durch Berufsträger (auch in eigener Sache), vorgerichtliche Anwaltsvergütung als
  Haupt- oder Nebenforderung, Gegenstandswert oder Anrechnungsbetrag ohne vorgerichtliche Vergütung,
  Verbraucherbeteiligung (§ 288 BGB), Prozessgericht

## Tools

| Tool | Wirkung |
|---|---|
| `kataloge_suchen` | Anspruchsart, Rechtsform, Belegart, Auslagenart nachschlagen |
| `antrag_schema` | JSON-Schema des Antrags |
| `antrag_pruefen` | Vorprüfung, nur lesend |
| `portal_ausfuellen` | Portal füllen; hält am Prozessgericht (falls nicht bestätigt) und an der Datenübersicht |
| `ausfuellen_fortsetzen` | nach Bestätigung des angezeigten Prozessgerichts weiterfüllen |
| `eda_herunterladen` | EDA-Datei speichern (nur nach Freigabe) |
| `portal_status` / `portal_schliessen` | Sitzung ansehen / beenden |

Beispielantrag: [`tests/beispiel_antrag.json`](tests/beispiel_antrag.json).

## Umfang v0.1 (bewusst eng)

Unterstützt: ein Antragsteller, ein Antragsgegner (je natürliche Person oder Firma mit einem
gesetzlichen Vertreter), Prozessbevollmächtigter (Reiter „Rechtsanwalt/-beistand“) oder Antragsteller
selbst, **ein** katalogisierter Anspruch mit optional Abtretung und laufenden Zinsen, Auslagen und
Nebenforderungen, Bankverbindung, Versandart EDA-Download oder Barcode.

Abgelehnt statt halb ausgefüllt: mehrere Ansprüche/Parteien/Vertreter, Auslandsanschriften (auch beim
Zedenten), Urkunden-/Scheck-/Wechselmahnverfahren, sonstige Ansprüche, ausgerechnete Zinsen, RA-Gesellschaft/Inkasso als Vertreter, manuelle Gerichtswahl.
Beim Barcode-Weg hält der Ausfüller auf der Übersicht an; Druck und Unterschrift macht der Mensch im Browser.

## Installation

Voraussetzungen: Google Chrome (sonst `uv run playwright install chromium`), macOS oder Linux.

**Als Plugin (Claude Code / Claude Desktop):** Marketplace `eliasreiche/mahnantrag-mcp` hinzufügen
und Plugin `mahnantrag` installieren. uv muss nicht vorinstalliert sein: Das Startskript
`bin/mahnantrag-start.sh` sucht uv an den üblichen Orten und lädt es sonst beim ersten Start einmalig
ohne Adminrechte nach `~/.local/share/mahnantrag-mcp/uv` (fest gepinnte Version aus den GitHub-Releases
von astral-sh/uv, geprüft gegen die im Skript eingetragene SHA-256; kein Installer-Skript, kein Eingriff
in PATH oder Shell-Profile). Danach lädt uv Python und die Abhängigkeiten;
der erste Start dauert deshalb etwa eine Minute. Wo die Kanzlei-IT Downloads aus dem Netz sperrt, uv
vorab zentral verteilen (z. B. per MDM) oder `MAHNANTRAG_UV_HOME` auf einen Ordner mit einer
freigegebenen `uv`-Datei setzen. Windows: uv manuell installieren und den Server direkt einbinden (unten).

**Direkt als MCP-Server:**

```bash
claude mcp add mahnantrag -- uv run --directory /pfad/zu/mahnantrag-mcp mahnantrag-mcp
```

Umgebungsvariablen (optional):

| Variable | Bedeutung |
|---|---|
| `MAHNANTRAG_AUSGABE` | Zielordner für EDA-Dateien (Standard `~/Documents/Mahnantraege`); je Antrag ein Unterordner `<Zeitpunkt>_<Geschäftszeichen>`, darin die Datei unter dem **unveränderten Portal-Namen** (z. B. `EDA_MBA_09_11_2026_930226_<32 Hex>.eda`), schreibgeschützt |
| `MAHNANTRAG_BROWSER_KANAL` | Playwright-Kanal (Standard `chrome`) |
| `MAHNANTRAG_BROWSER_PFAD` | expliziter Pfad zu einem Chromium |
| `MAHNANTRAG_UV_HOME` | Ordner, in dem das Startskript uv sucht bzw. installiert (Standard `~/.local/share/mahnantrag-mcp/uv`) |

## Datenschutz und Berufsrecht

Die Antragsdaten (Parteien, Forderung) laufen durch das Sprachmodell. In Kanzleien deshalb nur mit
einem berufsrechtlich abgesicherten Modellzugang nutzen (z. B. Claude über Amazon Bedrock in der EU
mit § 43e-BRAO-Vereinbarung), nicht mit einem Verbraucherkonto. Der Server selbst schreibt nur die
heruntergeladene EDA-Datei auf die Platte, in einen Ordner `<Zeitpunkt>_<Geschäftszeichen>`. Das Protokoll
bleibt im Arbeitsspeicher; Fehlermeldungen zur Antragsstruktur nennen Feldpfade, nicht die eingegebenen Werte.

Das Portal (verantwortlich: Justizministerium Baden-Württemberg, Koordinierungsstelle für das
automatisierte Mahnverfahren) hat laut Analyse keinen Bot-Schutz und keine Nutzungsbedingung gegen
automatisierte Bedienung. Der Ausfüller klickt die Zustimmung zum Datenschutzhinweis des Portals nur,
wenn `datenschutzhinweis_akzeptiert=true` übergeben wird.

## Entwicklung

```bash
uv sync
uv run pytest                                              # Unit-Tests, offline
uv run python scripts/mcp_rauchtest.py                     # MCP über stdio
uv run python scripts/live_probelauf.py tests/beispiel_antrag.json --sichtbar   # Live bis Übersicht, kein Download
uv run python scripts/live_probelauf.py tests/beispiel_antrag.json --gericht-bestaetigen --download /tmp/eda   # inkl. Download (nur Fantasiedaten!)
```

Portalwissen: [`docs/referenz/`](docs/referenz/) (Masken, Felder, zwölf Fallen). Neue Erkenntnisse
aus Live-Läufen stehen als Kommentar am Code (z. B. Begründungspflicht für sonstige Auslagen).

## Sicherheit

Sicherheitslücken bitte privat melden, siehe [SECURITY.md](SECURITY.md). CI führt bei jedem Push die
Offline-Tests (inklusive der Freigabesperren) und einen gitleaks-Scan aus.

## Quellen und Lizenz

Code: **GPL-3.0-or-later**, siehe [LICENSE](LICENSE).

Ausgenommen sind die Inhalte aus der Portal-Analyse
[nbindewald-legal/mahnantrag-portal-reference](https://github.com/nbindewald-legal/mahnantrag-portal-reference):
`docs/referenz/` (unveränderte Kopie) und die daraus abgeleiteten Kataloge in
`src/mahnantrag_mcp/daten/*.json` stehen unter **CC BY 4.0**. Namensnennung und Änderungen: [NOTICE](NOTICE).

Keine Rechtsberatung. Die Verantwortung für Inhalt und Einreichung des Antrags liegt bei der antragstellenden Person bzw. dem Prozessbevollmächtigten.
