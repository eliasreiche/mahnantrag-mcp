# mahnantrag-mcp

MCP-Server (und Claude-Plugin), mit dem Claude einen **Antrag auf Erlass eines Mahnbescheids** über
[online-mahnantrag.de](https://www.online-mahnantrag.de) vorbereitet:

1. **Vorprüfung** – deterministisch, bevor das Portal den Antrag sieht
2. **Ausfüllen** des Portals bis zur Datenübersicht – im sichtbaren Browser, Mensch kann jederzeit übernehmen
3. **EDA-Download** – erst nach ausdrücklicher Freigabe; Datei wird schreibgeschützt gespeichert und gehasht

**Eingereicht wird nie durch diesen Server.** Die EDA-Datei geht unverändert über einen sicheren
Übermittlungsweg (beA, § 130a Abs. 4 ZPO) an das Mahngericht. Das macht der Mensch.

> Status: **v0.1, privat.** Ende-zu-Ende gegen das Live-Portal getestet (09.11.2026, Fantasiedaten,
> bis zur Datenübersicht). Der EDA-Download selbst ist noch nicht live erprobt.

## Warum eine Vorprüfung?

Das Portal prüft fast nichts. Vierstellige PLZ, eine weibliche Vertreterfunktion zu einem männlichen
Namen oder eine doppelt eingetragene vorgerichtliche Anwaltsvergütung gehen ohne Meldung durch.
`antrag_pruefen` fängt unter anderem ab:

- Feldlängen des Portals (Firmenname 35 Zeichen je Zeile, Ort 27, Kennziffer 8 Ziffern …)
- Katalogcodes (75 Anspruchsarten, 178 Rechtsformen, Belegarten, Auslagenarten)
- PLZ, IBAN-Prüfziffer, Daten in der Zukunft
- vorgerichtliche Anwaltsvergütung als Haupt- **und** Nebenforderung (verdoppelt die Forderung)
- Barcode-Weg für Rechtsanwälte nur mit Glaubhaftmachung (§ 130d S. 2, 3 ZPO)
- 9 Punkte über Basiszins gegen natürliche Personen (§ 288 Abs. 1 vs. 2 BGB)
- Kosten des Mahnverfahrens als Auslage (§ 699 Abs. 3 ZPO)
- rechtliche Weichen, die ausdrücklich entschieden sein müssen: Gegenleistung, streitiges Verfahren,
  Vergütung, Gerichtsstand (Weiterklicken gilt als Wahl nach § 35 ZPO)

## Tools

| Tool | Wirkung |
|---|---|
| `kataloge_suchen` | Anspruchsart, Rechtsform, Belegart, Auslagenart nachschlagen |
| `antrag_schema` | JSON-Schema des Antrags |
| `antrag_pruefen` | Vorprüfung, nur lesend |
| `portal_ausfuellen` | Portal bis zur Datenübersicht füllen, dort anhalten |
| `eda_herunterladen` | EDA-Datei speichern (nur nach Freigabe) |
| `portal_status` / `portal_schliessen` | Sitzung ansehen / beenden |

Beispielantrag: [`tests/beispiel_antrag.json`](tests/beispiel_antrag.json).

## Umfang v0.1 (bewusst eng)

Unterstützt: ein Antragsteller, ein Antragsgegner (je natürliche Person oder Firma mit einem
gesetzlichen Vertreter), Prozessbevollmächtigter (Reiter „Rechtsanwalt/-beistand“) oder Antragsteller
selbst, **ein** katalogisierter Anspruch mit optional Abtretung und laufenden Zinsen, Auslagen und
Nebenforderungen, Bankverbindung, Versandart EDA-Download oder Barcode.

Abgelehnt statt halb ausgefüllt: mehrere Ansprüche/Parteien/Vertreter, Auslandsanschriften,
sonstige Ansprüche, ausgerechnete Zinsen, RA-Gesellschaft/Inkasso als Vertreter, manuelle Gerichtswahl.
Beim Barcode-Weg hält der Ausfüller auf der Übersicht an; Druck und Unterschrift macht der Mensch im Browser.

## Installation

Voraussetzungen: [uv](https://docs.astral.sh/uv/), Google Chrome (sonst `uv run playwright install chromium`).

**Als Plugin (Claude Code / Claude Desktop):** Marketplace `eliasreiche/mahnantrag-mcp` hinzufügen
und Plugin `mahnantrag` installieren. Bei privatem Repo braucht der Rechner GitHub-Zugriff.

**Direkt als MCP-Server:**

```bash
claude mcp add mahnantrag -- uv run --directory /pfad/zu/mahnantrag-mcp mahnantrag-mcp
```

Umgebungsvariablen (optional):

| Variable | Bedeutung |
|---|---|
| `MAHNANTRAG_AUSGABE` | Zielordner für EDA-Dateien (Standard `~/Documents/Mahnantraege`) |
| `MAHNANTRAG_BROWSER_KANAL` | Playwright-Kanal (Standard `chrome`) |
| `MAHNANTRAG_BROWSER_PFAD` | expliziter Pfad zu einem Chromium |

## Datenschutz und Berufsrecht

Die Antragsdaten (Parteien, Forderung) laufen durch das Sprachmodell. In Kanzleien deshalb nur mit
einem berufsrechtlich abgesicherten Modellzugang nutzen (z. B. Claude über Amazon Bedrock in der EU
mit § 43e-BRAO-Vereinbarung), nicht mit einem Verbraucherkonto. Der Server selbst speichert nur die
heruntergeladene EDA-Datei, kein Protokoll mit Mandatsdaten.

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
```

Portalwissen: [`docs/referenz/`](docs/referenz/) (Masken, Felder, zwölf Fallen). Neue Erkenntnisse
aus Live-Läufen stehen als Kommentar am Code (z. B. Begründungspflicht für sonstige Auslagen).

## Quellen und Lizenz

Portal-Analyse und Kataloge: [nbindewald-legal/mahnantrag-portal-reference](https://github.com/nbindewald-legal/mahnantrag-portal-reference),
CC BY 4.0, siehe [NOTICE](NOTICE). Lizenz dieses Repos: noch offen (privat).
