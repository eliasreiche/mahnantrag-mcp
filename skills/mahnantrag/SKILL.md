---
name: mahnantrag
description: Bereitet einen Antrag auf Erlass eines Mahnbescheids über online-mahnantrag.de vor (Vorprüfung, Ausfüllen bis zur Datenübersicht, EDA-Download für beA). Triggert bei Mahnbescheid, Mahnantrag, gerichtliches Mahnverfahren, online-mahnantrag, EDA-Datei.
---

# Mahnantrag vorbereiten

Nutzt die Tools des MCP-Servers `mahnantrag`. Eingereicht wird nie durch Claude: die EDA-Datei
schickt der Mensch über beA an das Mahngericht.

## Ablauf

1. **Daten sammeln.** `antrag_schema` zeigt alle Felder. Aus den Unterlagen übernehmen, was belegt ist.
   Katalognummern und Rechtsform-Codes nur über `kataloge_suchen`.
2. **Rechtliche Weichen erfragen, nie raten** (Feld `entscheidungen`):
   - Hängt der Anspruch von einer Gegenleistung ab, und ist sie erbracht?
   - Bei Widerspruch automatisch ins streitige Verfahren?
   - Vergütung im Mahnverfahren: gesetzlich, vereinbart oder Verzicht?
   - Stellt ein Rechtsanwalt, eine Behörde oder ein Inkassodienstleister den Antrag, auch in eigener Sache?
   - Vorgerichtliche Anwaltsvergütung: keine, als Hauptforderung **oder** als Nebenforderung, nie beides.
   - Gegenstandswert der vorgerichtlichen Tätigkeit oder Anrechnungsbetrag ohne vorgerichtliche Vergütung:
     Ist das so gewollt (`vorgerichtlich_ohne_verguetung_bestaetigt`)? Nur dann quittiert der Ausfüller die Portal-Warnung.
   - Bei mehr als 5 Punkten über Basiszins (auch über 9): Ist ein Verbraucher beteiligt (§ 288 BGB)?
3. **`antrag_pruefen`.** Fehler und Warnungen wörtlich zeigen. Fehler löst der Mensch.
   Firmennamen über 35 Zeichen bricht der Mensch um, weil der Umbruch im Bescheid erscheint.
4. **`portal_ausfuellen`** mit `sichtbar=true`, nachdem der Mensch dem Datenschutzhinweis des
   Portals zugestimmt hat. Bei `angehalten` den Grund zeigen; der Browser bleibt zur Übernahme offen.
   Bei `gericht_bestaetigen` das angezeigte Prozessgericht nennen und erklären, dass Weiterklicken als
   Wahl nach § 35 ZPO gilt. Nur nach Bestätigung `ausfuellen_fortsetzen` mit genau diesem Namen.
5. **Datenübersicht** zeigen: Beträge, Parteien, Prozessgericht, Gerichtsgebühr, Mahngericht.
   Erklärungen (Häkchen) stehen dort nicht verlässlich, also aus dem eigenen Antrag wiederholen.
6. Nur nach ausdrücklicher Freigabe: **`eda_herunterladen`**. Dateipfad und SHA-256 nennen.
   Hinweis: Datei unverändert per beA einreichen, nicht zusätzlich als Barcode.
7. `portal_schliessen`.

Die Portal-Sitzung läuft nach rund 30 Minuten ohne Aktivität ab. Wartung: erster Mittwoch im Monat, 8–10 Uhr.
