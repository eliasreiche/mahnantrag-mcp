# online-mahnantrag.de — Implementierungsspezifikation für ein Python-Automatisierungsskript
Stand: 07.09.2026. Grundlage: vollständig mitgeschnittener Durchgang (Bundesland Berlin,
Antragsteller eine UG, Antragsgegner eine GmbH, ein Anspruch mit Abtretung und
laufenden Zinsen, EDA-Download).
Alles hier Genannte ist beobachtet, nicht aus Dokumentation abgeleitet. Nicht verifizierte Punkte
sind als **UNVERIFIZIERT** markiert.

---

## 1. Grundarchitektur

| Eigenschaft | Wert |
|---|---|
| Einstieg | `https://www.online-mahnantrag.de/` -> Cookie-Zustimmung (Link "Ich stimme zu") |
| Anwendung | `https://www.online-mahnantrag.de/omahn/Mahnantrag` |
| Technik | klassische serverseitige Anwendung, **kein** JavaScript-Framework, **keine** SPA |
| Seitenaufbau | **Frameset** (echte `<frame>`, keine iframes) |
| Endpunkt | **alle** Schritte gehen als `POST` auf `/omahn/Mahnantrag` (`action="Mahnantrag"`, relativ) |
| Schrittsteuerung | ausschließlich über das versteckte Feld **`Command`** |
| URL | bleibt bei **jedem** Schritt identisch — **kein Schrittindex in der URL** |
| Feld-`id` | **existiert nicht.** Selektor ist immer `name`, innerhalb des richtigen Frames |
| Cookies | Pflicht. Session-Cookie + Zustimmungs-Cookie. Session endet mit dem Browser |

### 1.1 Framestruktur — wechselt je Schritt
Basis (immer):
```
top (FRAMESET)
 ├─ left10   -> /omahn/html/leer.html   (leer, Layout)
 ├─ head     -> Titelzeile, zeigt Bundesland + Gerichts-Hotline
 └─ main     -> Inhalt
```
Bei Schritten mit Mehrfacherfassung (Antragsteller, Antragsgegner, Ansprüche) wird `main`
**selbst zum Frameset**:
```
 └─ main (FRAMESET)
     ├─ wahl        -> Kopf + Baumdarstellung der bereits erfassten Einträge
     ├─ platzhalter -> leer
     └─ form        -> DAS EIGENTLICHE FORMULAR
```
In diesem Zustand ist `main.document.title` **leer**.

**Regel für das Skript:**
```python
def content_frame(page):
    main = page.frame(name="main")
    form = page.frame(name="form")     # Kindframe von main, nur zeitweise vorhanden
    return form if form else main
```
Frame-Pfad **nie fest verdrahten**. Pro Schritt prüfen, ob `main` Kindframes hat.

### 1.2 Bedienelemente
- Weiter-Buttons sind **`<input type="image">`** (GIF). Der POST enthält zusätzlich `name.x`/`name.y`.
- **Der `name` des Weiter-Buttons wechselt von Maske zu Maske** (`Weiter (Alt+W)`, `Weiter`,
  `Weiter AS`, `Nein`, `neuer Antrag`, `EDA-Datei herunterladen (Alt+E`).
  -> **Nicht über den Namen selektieren.** `input[type=image]` innerhalb des Formulars, ggf. über
  das GIF (`butt_weiter_60x19.gif`, `butt_weiter_rund.gif`, `butt_speichern_80x19.gif`,
  `butt_neuerAntrag_120x19.gif`).
- Manche Verzweigungen sind **GET-Links** (`<a>` mit GIF), keine Submits. Betroffen: die drei Wege
  auf "Für wen erfassen Sie diesen Antrag?", alle "Ja"-Zweige der Ja/Nein-Masken, alle Reiterwechsel,
  alle Zurück-Links, alle "bearbeiten"-Links der Datenübersicht.
- **alt-Texte sind als Selektor unbrauchbar**: teils wortgleich für verschiedene Ziele
  (Alt+P/Alt+E auf der PV-Frage), teils uneinheitlich formuliert
  ("Zum Anfang dieses Schritts" / "dieses Schrittes" / "des Schritts"), teils gar nicht gesetzt
  (Download-Button).

---

## 2. Ablaufsteuerung — Zustandsmaschine, keine feste Sequenz

**Die Maskenfolge ist nicht deterministisch.** Bereits beantwortete Schritte werden übersprungen
(beobachtet: nach erneutem Absenden der Bundeslandwahl ging es direkt auf Schritt 1, Versandart und
Schrittübersicht wurden übersprungen).

Nach **jedem** POST muss das Skript den erreichten Zustand feststellen. Reihenfolge der Prüfung:

```python
1. Frame bestimmen (main oder main/form)
2. form = frame.query_selector("form")
3. command = form.query_selector("input[name=Command]").get_attribute("value")
4. title   = frame.title()
5. text    = form.inner_text()
6. if "Warnung:" in text:  -> Warnungsbehandlung (Abschnitt 2.2)
7. Zustand = command   (NICHT der Titel, NICHT der Formularname)
```

### 2.1 `Command` ist das einzige verlässliche Zustandsmerkmal
Formularnamen und Titel sind **mehrdeutig**:

| Kollision | Betroffen | Unterscheidung |
|---|---|---|
| Formularname `NatuerlichePerson`, Felder `_bAnrede`,`_bName1`,`_bName2`,`_bStr`,`_bPLZ`,`_bOrt`,`_bNation` | Antragsteller **und** Antragsgegner | `saveAntragstellerNatPers` vs. `saveAntragsgegnerNatPers` |
| Formularname `Firma`, Felder `_bName1..4`,`_bStr`,`_bPLZ`,`_bOrt`,`_bNation`,`_bRechtsform` | Antragsteller **und** Antragsgegner | `saveAntragstellerFirma` (**UNVERIFIZIERT**) vs. `saveAntragsgegnerFirma` |
| Felder `_gvVertreterFunktion`,`_gvName1`,`_gvStr`,`_gvPLZ`,`_gvOrt`,`_gvNation`,`_gvGmbHUndCoKGMM` | AS-Vertreter **und** AG-Vertreter | `saveAntragstellerGV` vs. `saveAntragsgegnerGV` |
| **Formularname `ProzessVertreter` UND Titel `Online-Mahnantrag - PV`** | Adressdaten (Schritt 1) **und** Vergütung (Schritt 5b) | **nur** `saveProzessVertreter` vs. `saveProzessVertreterVerguetung` |

Der letzte Fall ist der kritische: dort sind Formularname **und** Titel identisch. Ein Skript, das
nur nach Feldnamen sucht, füllt die falsche Partei bzw. die falsche Maske — ohne jede Warnung.

Auch der `Command`-Wert der **aktuellen** Maske sagt nichts über den nächsten Schritt: die Werte
`display` (mehrfach) und `anspruchWeiter` sind nichtssagend bzw. für mehrere Ziele identisch.

### 2.2 Zwei getrennte Meldungsmechanismen — beide behandeln

**A) Serverseitige Warnung, nicht blockierend, bestätigungspflichtig**
- Erkennung: `"Warnung:"` im `inner_text` des Formulars. **Kein** CSS-Anker, keine `id`, keine `class`,
  keine Farbe, kein `<b>` — reiner Text im Fluss.
- Titel, Formularname und `Command` bleiben **identisch** mit dem Normalzustand.
  Ein Skript, das nur diese drei prüft, hält den Zustand für "nicht weitergeschaltet".
- `Changed` wechselt dabei von `true` auf `false` (zweiter Indikator).
- Quittierung: **dasselbe Formular unverändert erneut absenden.** Kein Bestätigungsfeld,
  kein eigener Button. Die zurückgelieferten (normalisierten) Feldwerte einfach zurückschicken.
- Warnungen werden durch das Quittieren **nicht gelöscht** — sie erscheinen erneut in der
  Datenübersicht (Schritt 7). Die Übersicht ist damit die **Sammelprüfung** aller offenen Warnungen.
- Bekannte Warnung Nr. 1, wörtlich:
  > "Warnung: Bitte überprüfen Sie Ihre Eingabe, es wurde ein Streitwert für eine vorgerichtliche
  > Tätigkeit und/oder ein Minderungsbetrag angegeben, ohne dass hierfür eine Anwaltsvergütung
  > angegeben wurde."
  Auslöser: `_bVorgerStreitwert` und/oder `_bVorgerMinderungsbetrag` gefüllt bei
  `_bVorgerAnwaltsverguetung = 0,00 EUR`. Kann fachlich gewollt sein -> darf dann quittiert werden.
- **Nie blind quittieren.** Wortlaut auslesen, gegen eine Liste bekannter Warnungen prüfen,
  bei unbekanntem Wortlaut abbrechen und melden.

**B) Clientseitiger modaler `alert()`, blockierend**
- Beobachtet auf der Download-Maske beim Klick ohne gesetztes `hinweisGelesen`:
  > "Bitte lesen Sie die Hinweise zum EDA-Download und bestätigen Sie die Kenntnisnahme" — Button: OK
- **Nicht aus dem HTML lesbar.** Solange der Dialog offen ist, ist der Renderer blockiert:
  DOM-Zugriff und Screenshot schlagen fehl. Von außen **nicht von einem Absturz zu unterscheiden**.
- Playwright: `page.on("dialog", lambda d: d.accept())` **vor** dem ersten Klick registrieren.
  Ohne Handler hängt der Durchlauf **ohne Fehlermeldung** (Klick kehrt nicht zurück, folgende
  Leseoperationen laufen in Timeouts).
- Präventiv: `hinweisGelesen` immer setzen, bevor der Download-Button geklickt wird.

**C) Echte Fehlermeldung** — existiert laut Maskentext (Prozessgericht: eine Änderung bei
ausschließlicher Zuständigkeit "führt zu einer Fehlermeldung"), **UNVERIFIZIERT**: Wortlaut und
Verhalten unbekannt. Kandidat für die Erkennung: das versteckte Feld **`FehlerDa`** in der
Datenübersicht (im Erfolgsfall `false`).

### 2.3 Session-Grenzen
| Grenze | Verhalten |
|---|---|
| **Timeout ~30 Min Untätigkeit** | Session endet serverseitig. **Ohne Fehlermeldung, ohne Hinweisseite** — die Anwendung fällt still auf die Bundeslandauswahl zurück, alle Daten sind verloren. Real beobachtet: 10:05:53 letzte Aktion -> 10:37 auf Bundeslandmaske. |
| Erkennung | kommt nach einem POST `Command=saveBundesland` / Formular `Bundesland` statt der erwarteten Maske -> Session tot |
| Wiederaufsetzen | **nicht möglich.** Keine Antrags-ID, kein serverseitiger Zwischenspeicher. Zwischenstand muss im Skript gehalten werden |
| Wartungsfenster | **erster Mittwoch im Monat, 8:00–10:00 Uhr.** Laufende Anträge werden zu Beginn systemseitig abgebrochen |
| Browser-Zurück | ausdrücklich untersagt ("Der Browser kennt nicht den Status der Anwendung") |
| Konsequenz | ein Durchlauf muss **deutlich unter 30 Minuten** bleiben; pro Fall ein frischer Durchlauf |

### 2.4 Bot-Schutz
**Kein CAPTCHA, keine Bot-Erkennung, kein Rate-Limit-Hinweis, keine Nutzungsbedingung gegen
automatisierten Zugriff** auf allen 26 gesehenen Masken. Nur die Cookie-Einwilligung und
Datenschutzhinweise. Rechtliche Schranke ist der Papier-/Barcode-Weg (§ 130d S. 2, 3 ZPO),
nicht die Automatisierung.

---

## 3. Ablauf und Masken in Reihenfolge

Legende: **F** = Formularname, **C** = `Command`-Wert, **Frame** = `main` oder `main/form`

### 3.0 Vorschaltung
| # | Maske | Aktion |
|---|---|---|
| 0 | Startseite `/` | Link **"Ich stimme zu"** (Cookie-Einwilligung; ohne sie ist die Anwendung gesperrt) |

### 3.1 Bundeslandauswahl
**F** `Bundesland` · **C** `saveBundesland` · Frame `main`
| Feld | Typ | Max | Hinweis |
|---|---|---|---|
| `Bundesland` | select | – | 16 Optionen. Vorbelegung `BW`. **Keine Leeroption** |
| `_ts` | hidden | – | serverseitiger Zeitstempel, unverändert zurückschicken |
| `Reload` | hidden | – | `false` |

Werte: `BW` `BAY` `BER` `BRB` `HB` `HH` `HES` `MBV` `NDS` `NRW` `RPF` `SLD` `SAC` `SAH` `SH` `THU`
Maskenhinweis: "Antragsteller mit Sitz/Wohnsitz im Ausland wählen 'Berlin'."
**Beispiel `BER`** -> zuständiges Mahngericht AG Wedding, Zentrales Mahngericht Berlin-Brandenburg,
13343 Berlin. Der `head`-Frame füllt sich danach automatisch mit Bundesland + Gerichts-Hotline.

### 3.2 Versandart
**F** `Antragsart` · **C** `saveVersandart` · Frame `main`
| Feld | Typ | Werte |
|---|---|---|
| `_bVersandart` | radio | **`EDA-Download`** (vorbelegt) · `Barcode` · `eID` |

**Für Rechtsanwälte zwingend `EDA-Download`** — der Barcode-/Papierweg ist für Rechtsanwälte nur zulässig,
wenn eine elektronische Einreichung aus vorübergehenden Gründen unmöglich ist und dies glaubhaft
gemacht wird (§ 130d S. 2, 3 ZPO).
Radiogruppen übertragen **nur den gewählten Wert**; die übrigen Radios gehen nicht mit.

### 3.3 Schrittübersicht
**F** `NeuerMBAntrag` · **C** `neuerMBAntrag` · Frame `main` · keine Eingabefelder
| Element | Technik | Wirkung |
|---|---|---|
| `weiter` | GET-Link | aktueller Antrag bleibt erhalten |
| **`neuer Antrag`** | POST `input[type=image]` name=`neuer Antrag` | **löscht alle erfassten Daten** |
| `zurück` | GET-Link | zur Bundeslandauswahl |

Für einen frischen Fall: **`neuer Antrag`**. Nur dieser Weg zeigt anschließend Maske 3.4.

### 3.4 "Für wen erfassen Sie diesen Antrag?"
**F** `PVJaNein` · Frame `main` · **keine Radiogruppe**, drei getrennte Bedienelemente
| Weg | Technik | Bedeutung |
|---|---|---|
| 1 | **GET-Link** (alt "... (Alt+P)") | "Ich bin Prozessbevollmächtigter (z.B. Rechtsanwalt) des Antragstellers. Ordnungsgemäße Bevollmächtigung versichere ich." |
| 2 | **GET-Link** (alt "... (Alt+E)") | "Ich bin Rechtsanwalt/Rechtsbeistand und stelle den Antrag in eigener Sache." |
| 3 | POST `input[type=image]` name=`Weiter AS`, C `leereViewDocumentASundShowAS` | "Ich bin Antragsteller." |

Die alt-Texte von 1 und 2 sind **wortgleich** bis auf das Tastenkürzel -> Auswahl über
Dokumentreihenfolge oder Alt-Taste, nicht über den alt-Text.
**Beispiel Weg 1** (Kanzlei = Prozessbevollmächtigte, Mandantin = Antragstellerin).

### 3.5 Prozessbevollmächtigter — Adressdaten
**F** `ProzessVertreter` · **C** `saveProzessVertreter` · Frame `main` · `Changed=true`
| Feld | Beschriftung | Typ | Max |
|---|---|---|---|
| `_pvBeauftragungsdatum` | Beauftragungsdatum | text (Datum) | 10 |
| `_pvBetrag` | Auslagen (statt Pauschale Nr. 7002 VV RVG) | text | 15 |
| `_pvErklaerungVorsteuer` | "Der Antragsteller ist nicht zum Vorsteuerabzug berechtigt." | checkbox `value=false` | – |
| `_pvUmsatzsteuerBefreit` | "Der Prozessbevollmächtigte ist von der Zahlung von Umsatzsteuer befreit." | checkbox `value=true` | – |
| `_pvKennziffer` | Prozessvertreter-Kennziffer | text | **8** |
| `_pvTitelMM` | Bezeichnung | select | – |
| `_pvName1` | Vor-/Nachname bzw. Bezeichnung | text | 105 |
| `_pvStr` | Straße/Hausnummer | text | 35 |
| `_pvPLZ` | PLZ | text | 5 |
| `_pvOrt` | Ort | text | 27 |
| `_pvNation` | Ausl.Kz. | text | 3 |
| `_pvMehrwertsteuersatz` | Mehrwertsteuersatz | text | 7 |

`_pvTitelMM`: `R` (leer, vorbelegt) · `1` Rechtsanwalt · `2` Rechtsanwälte · `3` Rechtsbeistand ·
`5` Rechtsanwältin · `6` Rechtsanwältinnen — **Code `4` fehlt** (Lücke im Katalog).

Reiter oben (Links, ändern den PV-Typ, **nicht erfasst**): Rechtsanwalt/-beistand · RA-Gesellschaft ·
Herr/Frau · Inkasso-/Kreditdienstleister · Verbraucherzentr./Verbraucherverb.
**`_pvKennziffer` ist optional** — Maskentext: "für die Antragstellung nicht zwingend erforderlich",
"Bitte 8-stellig eingeben, evtl. eine führende 0 einfügen". Leer abgeschickt und **ohne Fehler
akzeptiert**. Alternative laut Maske: "Oder geben Sie Ihre Daten ein" -> Kennziffer **oder** Adressdaten.

### 3.6 Antragsteller (verschachteltes Frameset ab hier)
Reiter im Frame `main/form`: **Herr, Frau** · **Firma** · **Kennziffer** · **Sonstige** (vier).
Reiterwechsel = GET-Link, löst kompletten Neuaufbau des verschachtelten Framesets aus.

**Natürliche Person** — **F** `NatuerlichePerson` · **C** `saveAntragstellerNatPers`
| Feld | Typ | Max |
|---|---|---|
| `_bAnrede` | select: `0` (leer) · `1` Herr · `2` Frau | – |
| `_bName1` Vorname / `_bName2` Nachname | text | 35 / 35 |
| `_bStr` / `_bPLZ` / `_bOrt` / `_bNation` | text | 35 / 5 / 27 / 3 |

**Firma** — **F** `Firma` · **C** `saveAntragstellerFirma` (**UNVERIFIZIERT**, aus Symmetrie zum
Antragsgegner geschlossen; die Maske selbst wurde nicht mitgeschnitten)
Felder mit hoher Wahrscheinlichkeit wie 3.10. Belegt sind nur die Werte des Testlaufs:
Rechtsform `UG (haftungsbeschränkt)` (Code `131`) sowie Name, Straße, PLZ und Ort einer Berliner UG.

### 3.7 Antragsteller — gesetzlicher Vertreter
**F** `AntragstellerGV` · **C** `saveAntragstellerGV` · Frame `main/form`
| Feld | Typ | Max |
|---|---|---|
| `_gvGmbHUndCoKGMM` | hidden | – (`false`; vermutlich Sonderfall GmbH & Co. KG) |
| `_gvVertreterFunktion` | select | – |
| `_gvName1` | text | 35 |
| `_gvStr` | text | 35 |
| `_gvPLZ` | text | 5 |
| `_gvOrt` | text | 27 |
| `_gvNation` | text | 3 |

`_gvVertreterFunktion`: `0` (leer) · `47` Geschäftsführende Gesellschafterin ·
`49` Geschäftsführender Gesellschafter · `52` Geschäftsführer · `53` Geschäftsführerin ·
`219` Managing Director.
**Codes nicht fortlaufend** — Katalogwerte, fest hinterlegen.
Nur 6 Funktionen, unabhängig von der Rechtsform. **Für AG-Vorstand, Komplementär oder ausländische
Vertretertypen ist keine passende Funktion vorhanden** (offene Frage).
Funktion und Name werden **nicht gegeneinander geprüft** (belegt: `47` weibliche Form zu einem männlichen Vornamen
wurde ohne Hinweis übernommen und erscheint wörtlich im Bescheid).

### 3.8 "Weiteren gesetzlichen Vertreter zum Antragsteller?"
**F** `mehrASGV` · **C** `mehrAntragsteller` · Frame `main/form` · nur hidden
| Antwort | Technik |
|---|---|
| Ja | GET-Link |
| **Nein** | POST `input[type=image]` name=`Nein` |

### 3.9 "Weiteren Antragsteller?"
**F** `mehrAS` · **C** `showAGEinstieg` · nur hidden · Ja = GET-Link, Nein = POST name=`Nein`

### 3.9b Überleitung zum Antragsgegner
**F** `GasamtschuldnerJaNein` (**Schreibfehler der Anwendung**, exakt so verwenden) ·
**C** `saveErklaerungAuslaendischeRechtsformAS` · Frame `main` · keine Eingabefelder
Überschrift "Angaben zum Antragssteller" (ebenfalls Schreibfehler, doppeltes s).
Hier wird implizit die Erklärung zur **ausländischen Rechtsform des Antragstellers** gespeichert.
Bei ausländischem Antragsteller ist eine Zusatzmaske zu erwarten (**UNVERIFIZIERT**).
Der Formularname deutet darauf hin, dass bei **mehreren Antragsgegnern** hier die
**Gesamtschuldner-Frage** erscheint (**UNVERIFIZIERT**, nur ein Gegner getestet).

### 3.10 Antragsgegner
Reiter: **Herr, Frau** · **Firma** · **Sonstige** (drei — **keine Kennziffer-Variante**, anders als
beim Antragsteller).

**Natürliche Person** — **F** `NatuerlichePerson` · **C** `saveAntragsgegnerNatPers`
Felder wie 3.6, **plus** ein Feld mehr:
| Feld | Beschriftung | Typ |
|---|---|---|
| `_bNatoTruppenstatut` | "Der Antragsgegner fällt unter das Zusatzabkommen zum NATO-Truppenstatut." | checkbox `value=true` |

**Firma** — **F** `Firma` · **C** `saveAntragsgegnerFirma`
| Feld | Beschriftung | Typ | Max |
|---|---|---|---|
| `_bName1` | **vollst. Firmenname** | text | 35 |
| `_bName2` `_bName3` `_bName4` | Firmenname Zeile 2–4 | text | je 35 |
| `_bStr` | Straße/Hausnummer | text | 35 |
| `_bPLZ` | PLZ | text | 5 |
| `_bOrt` | Ort | text | 27 |
| `_bNation` | Ausl.Kz. | text | 3 |
| `_bRechtsform` | Rechtsform | select, **178 Optionen** | – |

Maskenhinweis zu `_bName1`: "einschl. der in der Bezeichnung enthaltenen Rechtsform"
-> Firmenname **mit** Rechtsformzusatz **und** `_bRechtsform` separat codieren. **Beides.**
Firmierungen über 35 Zeichen müssen auf `_bName2..4` umbrochen werden; wo umbrochen wird, bestimmt
die Darstellung im Bescheid -> inhaltliche Entscheidung, nicht dem Skript überlassen.
Katalog `_bRechtsform`: siehe `rechtsform-katalog.md` (178 Codes, nicht fortlaufend).
Fallen: `3` GmbH vs. `60` GmbH i.L. vs. `195` GmbH in Gründung vs. `59` gemeinnützige GmbH vs.
`167` GmbH nach englischem Recht; `6` GmbH & Co KG ist eine **eigene** Rechtsform;
`131` UG (haftungsbeschränkt) vs. `229` gemeinnützige UG vs. `239` gUG haftungsbeschränkt.
Bei EU-Gegnern muss die Zuordnung aus dem **Handelsregisterzusatz** kommen, nicht aus dem
Länderkennzeichen (`63` LTD vs. `126` Limited, `77` S.R.L. vs. `161` SRL,
`128` SP.Z.O.O vs. `263` Sp. z.o.o. sp.k.).
Mehrere Codes bezeichnen praktisch dasselbe (`123` SE, `193`/`194` europäische Aktiengesellschaft,
`226`/`227` Europäische Gesellschaft) — welchen das Gericht erwartet, ist **offen**.

### 3.11 Antragsgegner — gesetzlicher Vertreter
**F** `AntragsgegnerGV` · **C** `saveAntragsgegnerGV` · Felder identisch mit 3.7

### 3.12 "Weiteren gesetzlichen Vertreter zum Antragsgegner?"
**F** `mehrAGGV` · **C** `mehrAntragsgegner` · Ja = GET-Link, Nein = POST name=`Nein`
alt-Texte **wortgleich** mit `mehrASGV` -> nur Formularname/`Command` unterscheiden.

### 3.13 "Weiteren Antragsgegner?"
**F** `mehrAG` · **C** **`display`** · Ja = GET-Link, Nein = POST name=`Nein`
**Achtung:** hier ist der Command nichtssagend (`display`). Das Ziel steht nur im alt-Text
("Nein, weiter zur Eingabe der Hauptforderungs-/Zinsdaten"). Die Regel "Command benennt das Ziel"
gilt **nicht durchgehend**.

### 3.14 Verfahrensart
**F** `VerfahrensArt` · **C** `saveVerfahrensArt` · Frame `main`
| Feld | Typ | Werte |
|---|---|---|
| `_bVerfahrensArt` | radio | **`NMV`** Reguläres Mahnverfahren (vorbelegt) · `UMV` Urkunden · `SMV` Scheck · `WMV` Wechsel |

**Verfahrenswährung: EUR, fest.** Nur Text, **kein Feld** — eine Fremdwährungsforderung ist im
nationalen Mahnverfahren über dieses Portal nicht abbildbar.
**Im Testlauf `NMV`** (deliktische Forderung).

### 3.15 Katalogisierter Anspruch
**F** `KatAnspruch` · **C** `saveKatAnspruch` · Frame `main/form` · `Changed=true`
Reiter: **Katalog. Anspruch** · Sonst. Anspruch (**nicht erfasst**) · ausgerechneter Zins (**nicht erfasst**)
| Feld | Beschriftung | Typ | Max | Vorbelegung |
|---|---|---|---|---|
| `KatNr` | Kat.-Nr. | text | **2** | leer |
| `_bKatalogArt` | Anspruchsart | select, 76 Optionen | – | leer |
| `_aspAspGr` | Anspruchsgrundlage/Belegart | select, 10 Optionen | – | leer |
| `_aspAspGrZusatz` | Zusatz | text | 35 | leer |
| `_bAspNr` | Belegnummer (**Freitext**) | text | 35 | leer |
| `_bVon` | Zeitraum von | text (Datum) | 10 | leer |
| `_bBis` | Zeitraum bis | text (Datum) | 10 | leer |
| `_bBetrag` | Betrag | text | 18 | **`0,00 EUR`** |
| `MehrVerbrKreditGesetz` | Verbraucherkreditgesetz | checkbox | – | aus |

- **`KatNr` und `_bKatalogArt` werden BEIDE übertragen** und tragen denselben Wert. Die Eingabe in
  `KatNr` füllt die Liste mit. **Empfehlung: beide setzen**, `KatNr` ist der robustere Weg
  (Textfeld statt 76er-Auswahlliste).
- `_bBis` darf leer bleiben (Zeitpunkt statt Zeitraum).
- Katalog: siehe `anspruchskatalog.md`. Im Testlauf `24` Rechtsanwalts-/Rechtsbeistandshonorar.
  Weitere Kandidaten bei deliktischen Forderungen: `29` Schadenersatz aus Unfall/Vorfall,
  `71` Verzugsschaden (n. anrechenbare RA-Kosten aus vorger. Tätigkeit). **Rechtsfrage, nicht Skriptlogik.**
- `_aspAspGr` überträgt **Klartext-Strings**, keine Zahlencodes:
  `Schreiben` `Rechnung` `Mahnung` `Kontoauszug` `Aufstellung` `Vertrag` `Stromrechnung`
  `Gasrechnung` `Sonstiger`. **Falle:** die Option zeigt "andere", überträgt aber `Sonstiger`.

**Nach dem Speichern rechnet die Anwendung die Gerichtskosten selbst** und zeigt sie im Frame
`main/wahl`: 326,15 EUR Hauptforderung -> **38,00 EUR** Gerichtsgebühr. Nicht eingeben.
Maskenhinweis: "Die Kosten des Mahnverfahrens (Gerichts- und Anwaltskosten) werden von Amts wegen in
die Bescheide aufgenommen, § 699 Abs. 3 ZPO. Sie dürfen deshalb **nicht** als zusätzliche Auslagen
oder Nebenforderungen eingetragen werden."

### 3.16 Verzweigung "Sie können jetzt:"
**F** `mehrDiverses` · **C** `anspruchWeiter` · Frame `main/form`
**Erste echte Radiogruppe für eine Verzweigung**, gemeinsamer Weiter-Button:
| `MehrAbtretungZinsenAnspruch` | Bedeutung |
|---|---|
| `Abtretung` | Abtretung/Forderungsübergang zum Anspruch erfassen |
| `Zinsen` | Zinsangaben zum Anspruch erfassen |
| `Anspruch` | weiteren Anspruch oder ausgerechnete Zinsen erfassen/ändern |
| `Weiter` | keine weiteren Angaben zu Hauptforderung und Zinsen |

**Diese Gruppe ist zustandsabhängig — dreifach:**
1. **Optionsmenge schrumpft**: nach dem Erfassen einer Abtretung verschwindet `Abtretung`.
   `Zinsen` bleibt dagegen sichtbar, obwohl schon Zinsen erfasst sind. Ausblendlogik **nicht einheitlich**.
2. **Position wechselt**: der erste Radio war zunächst `Abtretung`, später `Zinsen`.
3. **Vorbelegung wechselt**: zunächst keine Option, später `Weiter` vorbelegt, dann wieder keine.

-> **Immer nach `value` selektieren, vorher prüfen, ob der Wert existiert, und den Wert immer
explizit setzen.** Niemals nach Position, niemals auf eine Vorbelegung verlassen.
Der `Command` bleibt `anspruchWeiter` unabhängig von der Wahl — die Verzweigung steckt allein
im Radiowert.

### 3.17 Abtretung / Forderungsübergang
**F** `Abtretung` · **C** `display` · Frame `main/form` · `Changed=true`
| Feld | Beschriftung | Typ | Max |
|---|---|---|---|
| `_IndexAb` | hidden | – | **`-1`** = neuer Eintrag |
| `_bName1` | Früherer Gläubiger (Vor-,Zuname, Firma) | text | **35** |
| `_bPLZ` | PLZ | text | 5 |
| `_bOrt` | Ort | text | 27 |
| `_bNation` | Ausl.Kz. | text | 3 |
| `_bAbgetretenAm` | am: (Datum der Abtretung/des Forderungsübergangs) | text (Datum) | 10 |

Für ein Zessionskonstrukt (Mandant = Zedent, eigene Gesellschaft = Zessionarin):
- **Nur EINE Namenszeile, 35 Zeichen.** Kein `_bName2..4`. Längere Mandantennamen müssen gekürzt werden.
- **Kein Straßenfeld.** Nur PLZ, Ort, Auslandskennzeichen.
- **Keine Rechtsform-Auswahl** für den Zedenten — eine GmbH erscheint nur als Namenstext.
- `_bNation` vorhanden -> ausländischer Zedent abbildbar.

**WARNUNG aus dem Maskentext:** "Bitte beachten Sie, dass sich die Reihenfolge der Ansprüche aus
technischen Gründen ändern kann." `_IndexAb` bindet die Abtretung **per Index** an einen Anspruch.
Bei mehreren Ansprüchen mit je eigener Abtretung darf ein Skript **nicht** annehmen, dass
"Anspruch 1" nach dem Speichern noch Index 1 ist. Zuordnung nach jedem Speichern aus `main/wahl`
gegenlesen.

### 3.18 Laufende Zinsen
**F** `LaufendeZinsen` · **C** `display` · Frame `main/form` · `Changed=true`
| Feld | Beschriftung | Typ | Max | Vorbelegung |
|---|---|---|---|---|
| `_bIsAusgerechnet` | hidden | – | – | **`false`** (Schalter laufende/ausgerechnete Zinsen) |
| `_bZinssatz` | Zinssatz | text | **12** | **`0,000 %`** |
| `_bUeberBasisZinssatz` | "-Punkte über dem Basiszins" | checkbox `value=true` | – | aus |
| `_bZinssatzJMT` | Verzinsung | select | – | `J` |
| `_bBasisBetrag` | zu verz. Betrag (nur wenn abweichend von Hauptforderung) | text | 18 | leer |
| `_bVon` | ab / vom | text (Datum) | 10 | leer |
| `_bBis` | bis | text (Datum) | 10 | leer |

`_bZinssatzJMT`: `J` Jährliche (vorbelegt) · `M` Monatliche · `T` Tägliche

**Zwei Zinsvarianten, gesteuert über die Checkbox:**
- `_bUeberBasisZinssatz` **aus** -> `_bZinssatz` ist ein **fester** Jahreszinssatz
- `_bUeberBasisZinssatz` **an** -> `_bZinssatz` sind **Prozentpunkte ÜBER dem Basiszinssatz**

**Bei einer Forderung gegen einen Unternehmer (§ 288 Abs. 2 BGB — 9 Punkte über Basiszins):
`_bZinssatz = "9,000 %"` PLUS gesetzte Checkbox.** Vorteil: der Basiszins ändert sich halbjährlich,
die dynamische Variante muss das Skript nicht nachrechnen und der Antrag veraltet nicht.
Im Testlauf war die Checkbox **nicht** gesetzt (Anzeige "mit jährlich 9,000 %" ohne Zusatz) —
für den Echtbetrieb prüfen.
`_bBis` leer lassen: "Ab Zustellung des Mahnbescheids wenn kein Datum angegeben."

**FALLE: erneutes Wählen von `Zinsen` legt einen NEUEN Eintrag an, keinen Änderungsmodus.**
Die Maske kommt leer hoch, obwohl bereits Zinsen erfasst sind. Ein Skript, das nach einem
Fehlversuch einfach nochmal `Zinsen` wählt, erzeugt einen **doppelten Zinseintrag** —
die Anwendung blendet die Option nicht aus und warnt nicht.
Vor dem Absenden über `main/wahl` prüfen, ob schon Zinsen hängen.
**Notausgang ohne Speichern:** Zurück-Link (GIF `grf_zurueck.gif`) — kein POST, keine Datenspur.

### 3.19 Auslagen und Nebenforderungen (größte Maske, 35 Felder)
**F** `Auslagen` · **C** `saveAuslagenNebenforderungen` · Frame `main` · nichts ist Pflicht

**Block 1 — Auslagen für dieses Verfahren**
| Feld | Typ | Max | Vorbelegung |
|---|---|---|---|
| `_bVordruckPorto` | text | 14 | `0,00 EUR` |
| `liste1` | select, 24 Optionen | – | leer |
| `_bSonstBetrag` | text | 14 | `0,00 EUR` |
| `_bSonstBezeichnung` | text (wenn "andere") | 35 | leer |

`liste1` überträgt **Klartext-Strings** (Wert = Text), Ausnahme: Anzeigetext "andere" -> Wert `Sonstiger`.
Optionen: Akteneinsichtsgebühr · Auskunft Vollstreckungsportal · Einstellung der Versorgung ·
EMA-Anfrage · Fahrtkosten · Gangkosten/Sperrkosten · Gebühren für Gütestelle ·
Gerichtsvollzieherkosten · Gewerbeamtsanfrage · HR-Auskunft · Kontoführungskosten · Kopien ·
Kosten Vollstreckungsportal · Pauschale § 288 Abs. 5 BGB · Postanfrage · Schreibkosten ·
Schufakosten · Servicepauschale gem. Vereinbarung · Telefax · Telefon · Versandkosten ·
Verzugspauschale § 288 Abs. 5 BGB · `Sonstiger`

**Block 2 — fünf Nebenforderungspositionen, identisches Schema mit je fünf Feldern**
`<Präfix>` (Betrag, max 13) · `<Präfix>Zins` (max 12) · `<Präfix>ZinsUeberBasis` (checkbox) ·
`<Präfix>ZinsVon` (Datum, max 10) · `<Präfix>ZinsBis` (Datum, max 10)
| Position | Präfix |
|---|---|
| Mahnkosten | `_bMahnKosten` |
| Auskünfte | `_bAuskunftsKosten` |
| Bankrücklastkosten | `_bBankruecklastKosten` |
| Inkassokosten | `_bInkassoKosten` |
| Anwaltsvergütung für vorgerichtl. Tätigkeit | `_bVorgerAnwaltsverguetung` |

**Block 3 — nur zur vorgerichtlichen Anwaltsvergütung**
| Feld | Beschriftung | Typ | Max | Vorbelegung |
|---|---|---|---|---|
| `_bVorgerStreitwert` | Gegenstandswert der vorgerichtl. Tätigkeit | text | 18 | `0,00 EUR` |
| `_bVorgerUmfangreich` | Vorgerichtl. Tätigkeit umfangreich/schwierig | checkbox | – | aus |
| `_bVorgerMinderungsbetrag` | Auf die Verfahr.gebühr Nr. 3305 VV RVG ist anzurechnen (ohne Auslagen und ohne MwSt.) | text | 18 | `0,00 EUR` |

Weiterer Link: "Sonstige Nebenforderungen anlegen/bearbeiten" -> Untermaske, **nicht erfasst**.

**Inhaltliche Kollision, muss konfiguriert werden:** die vorgerichtliche RVG-Gebühr lässt sich
entweder als **Hauptforderung** (3.15, Katalognr. 24 bzw. 71) **oder** als **Nebenforderung**
(`_bVorgerAnwaltsverguetung` + Gegenstandswert + Anrechnung) abbilden.
**Beides zu füllen verdoppelt die Forderung**, und die Anwendung moniert das nicht.
Das Skript darf diese Wahl nicht selbst treffen.

### 3.20 Prozessbevollmächtigter — Vergütung
**F** `ProzessVertreter` · **C** `saveProzessVertreterVerguetung` · Frame `main` · Titel **`- PV`**
(**identisch mit 3.5 in Formularname UND Titel — nur `Command` unterscheidet**)
| Feld | Typ | Werte |
|---|---|---|
| `_bVerguetungMM` | radio, **keine Vorbelegung** | `GESETZLICH` · `VEREINBART` · `VERZICHT` |
| `_bVerguetungBetrag` | text, max 14 | `0,00 EUR` (nur bei `VEREINBART` relevant, wird aber immer mitgeschickt) |

Wortlaute: `GESETZLICH` = "Die gesetzliche Vergütung nach dem RVG in voller Höhe zzgl. Auslagen und
Umsatzsteuer in den Mahnbescheid aufzunehmen" · `VEREINBART` = vereinbarter Betrag ·
`VERZICHT` = "Ich verzichte vollständig auf die Aufnahme einer Vergütung in den Mahnbescheid."
Maskenhinweis: "Die Rechtsanwaltsvergütung im Mahnverfahren ist seit 01.06.2025 neu geregelt."
Im Testlauf `GESETZLICH`. **Gebührenentscheidung — konfigurieren, nicht raten.**

### 3.21 Prozessgericht
**F** `Allg` · **C** `showAllgemeineAngaben` · Frame `main` · **keine Eingabefelder**
Das Gericht wird **automatisch aus der Adresse des Antragsgegners** abgeleitet (hier: Amtsgericht
Bühl, 77815 Bühl, Lieferanschrift Hauptstr. 94, Postanschrift 77801 Bühl Postfach 11 55).
Ein Skript muss es **nicht setzen**, sollte es aber **auslesen und protokollieren**.

**Rechtlich relevant, wörtlich:** "Sofern ein Wahlrecht zwischen mehreren Gerichtsständen besteht
(§ 35 ZPO), gilt die Wahl eines Gerichts im Antrag auf Erlass eines Mahnbescheids bereits als
Ausübung dieses Wahlrechts."
-> **Ein Skript, das hier einfach "weiter" klickt, übt die Gerichtsstandswahl implizit aus.**
Bei deliktischer Forderung wäre auch der Handlungsort (§ 32 ZPO) wählbar. Entscheidung vor der
Automatisierung treffen.
Link "bearbeiten" -> manuelle Gerichtswahl, **nicht erfasst**. Laut Maskentext führt eine Änderung
bei ausschließlicher Zuständigkeit zu einer **Fehlermeldung**.

### 3.22 Allgemeine Angaben zum Antrag
**C** `saveAllgemeineAngaben` · Frame `main` · Formularname **nicht erfasst**
| Feld | Beschriftung | Typ | Max |
|---|---|---|---|
| `_bAntragstellerGeschaeftszeichen` | Geschäftszeichen (des Antragstellers/Prozessvertreters) | text | **35** |
| `_bErklaerungVorGegenLeistung1` | "...Anspruch von einer Gegenleistung abhängt, diese aber bereits erbracht ist." | checkbox | – |
| `_bErklaerungVorGegenLeistung2` | "...Anspruch von einer Gegenleistung nicht abhängt." | checkbox | – |
| `_bErklaerungStreitVerfahren` | "Im Falle eines Widerspruchs beantrage ich die Durchführung des streitigen Verfahrens." | checkbox | – |
| `_bKostenstatus` | Kosten-/Geb.freiheit | select | – |
| `_bProzesskostenhilfe` | Prozesskostenhilfe | select | – |
| `_bGerichtsGeschaeftsnummer1` | GNR Mahngericht, Teil 1 | text | **2** |
| `_bGerichtsGeschaeftsnummer2` | GNR Mahngericht, Teil 2 | text | **7** |
| `_bGerichtsGeschaeftsnummer3` | GNR Mahngericht, Teil 3 | text | **1** |
| `_bGerichtsGeschaeftsnummer4` | GNR Mahngericht, Teil 4 | text | **1** |

- **`_bKostenstatus` und `_bProzesskostenhilfe` haben als Leerwert ein LEERZEICHEN (`" "`),
  keinen Leerstring.** Ein Skript, das auf `""` vergleicht oder `""` setzt, trifft den Leerwert nicht.
  Optionslisten konnten nicht ausgelesen werden; aus dem Maskentext: Befreiung von Gerichtskosten /
  Befreiung nur von Gebühren; Prozesskostenhilfe beantragt.
- **`_bAntragstellerGeschaeftszeichen` ist die EINZIGE Stelle im Antrag, über die sich ein
  Rückläufer maschinell einem Fall zuordnen lässt.** Für Massenverfahren zentral — hier gehört die
  Case-Referenz hinein.
- GNR beim Neuantrag leer (vom Gericht vergeben, nur bei Folgeanträgen zu füllen).
- Die beiden Gegenleistungs-Erklärungen sind **Checkboxen, keine Radiogruppe** — technisch könnten
  beide gesetzt werden, was inhaltlich widersprüchlich wäre. Testlauf: nur `..2` (passend zur
  deliktischen Forderung).
- **`_bErklaerungStreitVerfahren` ist eine Prozessentscheidung mit Kostenfolge**, keine Formalie:
  gesetzt = bei Widerspruch automatisch ins streitige Verfahren; ungesetzt = der Fall bleibt liegen,
  bis aktiv ein Antrag gestellt wird.

### 3.23 Bankverbindung
**F** `BankVerbindung` · **C** `saveBankVerbindung` · Frame `main`
| Feld | Typ | Max | Vorbelegung |
|---|---|---|---|
| `_bIban` | text | **42** | leer |
| `_bBic` | text | **11** | leer |
| `_bKontoZuordnung` | select, 2 Optionen, **keine Leeroption** | – | `1` |

`_bKontoZuordnung`: `1` "Der erste/einzige Antragsteller ist Kontoinhaber." (vorbelegt) ·
`2` "Der Prozessbevollmächtigte ist Kontoinhaber."
Maskenhinweis: "Sind Ihre Bankdaten bereits in Ihren Kennziffer-Daten vermerkt, so sind hier
grundsätzlich keine Angaben nötig." -> **entfällt, sobald die Kennziffer erteilt ist.**
`_bBic` leer wird nicht beanstandet.

### 3.24 Datenübersicht
**F** `MBUebersicht` · **C** `saveMBAntragUebersicht` · Frame `main` · **keine Eingabefelder**
| Hidden | Wert | Bedeutung |
|---|---|---|
| `MGChecked` | `false` | Mahngericht geprüft (vermutet) |
| `_MGNr` | `0` | Mahngerichtsnummer (vermutet) |
| **`FehlerDa`** | **`false`** | **Fehlerflag** — potenziell der beste maschinelle Freigabe-Indikator |

`FehlerDa` **UNVERIFIZIERT**: im Testlauf kein Fehlerfall erzeugt. Ein Durchgang mit absichtlichem
Fehler wäre nötig, um zu belegen, dass das Feld dann `true` trägt. Alle drei Felder werden
unverändert zurückgeschickt — vorher auslesen und prüfen.

13x `<a>` mit `butt_bearbeiten.gif` — je Abschnitt ein Sprung zurück in die zugehörige Maske.

**Verwendung als Kontrollpunkt:** die Übersicht enthält den vollständigen Antragsinhalt als Text
(Beträge, Namen, Adressen, Katalogwerte, Zinssatz, Gerichtsgebühr, zuständiges Mahngericht).
**Aber: Checkbox-Zustände sind NICHT ablesbar** — die Übersicht listet Checkbox-Beschriftungen
unabhängig davon, ob sie gesetzt sind (belegt an vier ungesetzten Checkboxen). Kein Häkchen-Bild,
keine erkennbare Markierung. **Ein Skript muss Checkbox-Zustände aus seinen eigenen POST-Daten
führen, nicht aus der Übersicht.**
Für Beträge, Namen, Daten und Katalogwerte ist die Übersicht verlässlich.

### 3.25 Abgabe / EDA-Download
**F** `AbgabeEDA` · **C** `abgabeMBEda` · Frame `main` · `Changed=true`
Reiter: Barcode · **EDA-Download** · eID-Personalausw. · Ausdruck
| Feld | Beschriftung | Typ | Besonderheit |
|---|---|---|---|
| **`hinweisGelesen`** | "Ich habe die Hinweise gelesen und werde sie beachten." | checkbox | **kein `value`-Attribut** |

- **`hinweisGelesen` ist ein Pflicht-Gate.** Ohne Häkchen: modaler `alert()`
  ("Bitte lesen Sie die Hinweise zum EDA-Download und bestätigen Sie die Kenntnisnahme", Button OK),
  **kein Download, kein POST**.
- **Der POST überträgt `hinweisGelesen=` — leerer Wert, nicht `true`.** Anders als alle anderen
  Checkboxen dieser Anwendung (`value="true"`). Also die Checkbox im DOM anklicken oder den leeren
  Wert setzen, **nicht** `hinweisGelesen=true`.
- Download-Button: `input[type=image]`, **name `EDA-Datei herunterladen (Alt+E`**
  (30 Zeichen, **schließende Klammer fehlt** — Fehler der Anwendung), **`alt` ist nicht gesetzt**,
  GIF `butt_speichern_80x19.gif`. -> Selektion über das GIF, nicht über name/alt.
- **Keine separate Download-URL.** Der Download ist die Antwort auf denselben POST an
  `/omahn/Mahnantrag` mit `Command=abgabeMBEda`. Die Antwort ist als Datei zu behandeln
  (Content-Disposition), nicht als HTML. Die Maske bleibt danach unverändert stehen,
  es folgt keine weitere Maske.
- **Dateiname und Content-Type nicht erfasst** (Netzwerkaufzeichnung war nicht aktiv).
  Ob das Portal einer eigenen Namenskonvention folgt, ist **nicht belegt**.

Maskenhinweise, rechtlich relevant:
- Einreichung nur über sicheren Übermittlungsweg gem. § 130a Abs. 4 ZPO (beA, beBPo, MJP, eBO,
  DE-Mail mit "absenderbestätigt"). Einfache E-Mail unzulässig.
- **"Änderungen des Antrags sind nicht zulässig. Wenn Sie die Daten nach dem Download ändern,
  zerstören Sie die Integrität der Datei, sie kann vom Mahngericht nicht mehr verarbeitet werden."**
  -> Die Portal-Datei darf **nicht** nachbearbeitet werden (auch nicht, um eine Kennziffer
  nachzutragen). Ein Diff gegen eine eigene Referenzdatei ist unproblematisch, solange die
  Portal-Datei unverändert eingereicht wird.
- Keine HTML-Antragsübersicht mitsenden. **Nicht zusätzlich als Barcode-Ausdruck** übersenden
  (verursacht zusätzliche Kosten).

---

## 4. Formatregeln

| Typ | Format | Beleg |
|---|---|---|
| Datum | **`TT.MM.JJJJ`**, max 10 | `11.02.2026`, `10.12.2025`, `26.02.2026` |
| Betrag | **`<Betrag mit Dezimalkomma> EUR`** — Währungskürzel **im Feldwert** | Vorbelegung `0,00 EUR`, gesendet `326,15 EUR` |
| Zinssatz | **`<Satz mit drei Dezimalstellen> %`** — Prozentzeichen **im Feldwert** | Vorbelegung `0,000 %`, angezeigt `9,000 %` |
| Anzeigeformat Beträge | `3.000,00 EUR` (Tausenderpunkt **und** Dezimalkomma) | Rückgabe des Servers |

**Serverseitige Normalisierung — belegt in zwei Fällen:**
- `3000 EUR` (getippt) -> `3.000,00 EUR` (zurückgeliefert)
- `DE55 1001 0123 7975 6449 10` (getippt) -> `DE55100101237975644910` (zurückgeliefert)

-> Lose Eingaben werden angenommen. **Aber:** aus einem POST allein lässt sich nicht ablesen, was
der Server daraus macht. Wenn der exakte Wert zählt, den **zurückgelieferten** Feldwert gegenlesen.
Vorbelegungen (`0,00 EUR`, `0,000 %`) immer **überschreiben, nie anhängen**.

**Keine Formatprüfung beobachtet bei:**
- PLZ: `1043` (vierstellig) wurde ohne Fehlermeldung akzeptiert und durchgelassen.
  **Die Anwendung fängt fehlerhafte PLZ nicht ab** — Prüfung muss im eigenen Code passieren.
- Funktion/Name: weibliche Funktionsbezeichnung zu männlichem Namen wurde übernommen.

---

## 5. Die zwölf Fallen — Checkliste fürs Skript

1. **Frame-Pfad wechselt** je Schritt (`main` vs. `main/form`). Pro Schritt prüfen.
2. **Kein `id` an Feldern.** Nur `name`, innerhalb des richtigen Frames.
3. **`Command` ist das einzige verlässliche Zustandsmerkmal.** Formularname und Titel sind
   mehrdeutig — bei `ProzessVertreter` sind **beide** identisch für zwei verschiedene Masken.
4. **Weiter-Button-Namen wechseln.** Über `input[type=image]` bzw. GIF selektieren.
5. **alt-Texte taugen nicht als Selektor** (wortgleich, uneinheitlich, teils nicht gesetzt).
6. **Zwei Meldungsmechanismen**: Text-Warnung im Formular (bestätigungspflichtig durch erneutes
   Absenden) und blockierender `alert()` (Dialog-Handler nötig).
7. **Warnung ändert Titel/Formularname/Command NICHT.** Nur Textsuche auf `Warnung:` erkennt sie.
8. **Radiogruppe `MehrAbtretungZinsenAnspruch` ist zustandsabhängig** in Optionsmenge, Position und
   Vorbelegung. Immer nach `value` selektieren, Existenz prüfen, Wert explizit setzen.
9. **Erneutes Wählen von `Zinsen` legt einen Doppeleintrag an** (kein Änderungsmodus, keine Warnung).
10. **`_IndexAb` bindet per Index**, und die Anwendung sortiert Ansprüche eigenmächtig um.
    Zuordnung aus `main/wahl` gegenlesen.
11. **Leerwerte sind teils ein Leerzeichen** (`_bKostenstatus`, `_bProzesskostenhilfe`), nicht `""`.
12. **`hinweisGelesen` überträgt einen leeren Wert**, nicht `true`.

Zusätzlich: **Session-Timeout ist stumm** (Rückfall auf Bundesland ohne Meldung) und
**Checkbox-Zustände sind in der Datenübersicht nicht verifizierbar**.

---

## 6. Empfohlener Skriptaufbau

```python
from playwright.sync_api import sync_playwright

BEKANNTE_WARNUNGEN = [
    "es wurde ein Streitwert für eine vorgerichtliche Tätigkeit und/oder ein "
    "Minderungsbetrag angegeben, ohne dass hierfür eine Anwaltsvergütung angegeben wurde",
]

def content_frame(page):
    """Formular-Frame ermitteln: main, oder dessen Kindframe 'form' wenn vorhanden."""
    f = page.frame(name="form")
    return f or page.frame(name="main")

def zustand(page):
    """Zustand IMMER über Command lesen, nie über Titel/Formularname."""
    fr = content_frame(page)
    form = fr.query_selector("form")
    cmd = form.query_selector("input[name=Command]").get_attribute("value")
    txt = form.inner_text()
    warnungen = [l for l in txt.splitlines() if l.strip().startswith("Warnung:")]
    return fr, form, cmd, warnungen

def submit(page, fr):
    """Weiter-Button über input[type=image] klicken, nicht über den Namen."""
    fr.query_selector("form input[type=image]").click()
    page.wait_for_load_state("load")

def schritt(page, erwartet, fuellen):
    fr, form, cmd, warn = zustand(page)
    if cmd == "saveBundesland" and erwartet != "saveBundesland":
        raise SessionAbgelaufen("stiller Rückfall auf Bundeslandauswahl")
    if cmd != erwartet:
        raise UnerwarteterZustand(erwartet, cmd)
    fuellen(fr)
    submit(page, fr)
    # Warnungsbehandlung: gleiche Maske kommt mit Warntext zurück
    fr, form, cmd2, warn = zustand(page)
    while cmd2 == erwartet and warn:
        for w in warn:
            if not any(b in w for b in BEKANNTE_WARNUNGEN):
                raise UnbekannteWarnung(w)
        submit(page, fr)            # unverändert erneut absenden = quittieren
        fr, form, cmd2, warn = zustand(page)
    return cmd2

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page()
    page.on("dialog", lambda d: d.accept())     # PFLICHT vor dem ersten Klick
    ...
```

**Ablaufgerüst** (Command-Kette des dokumentierten Durchgangs):
```
saveBundesland -> saveVersandart -> neuerMBAntrag -> [GET-Link Alt+P]
-> saveProzessVertreter -> saveAntragstellerFirma* -> saveAntragstellerGV
-> mehrAntragsteller(Nein) -> showAGEinstieg(Nein)
-> saveErklaerungAuslaendischeRechtsformAS -> saveAntragsgegnerFirma
-> saveAntragsgegnerGV -> mehrAntragsgegner(Nein) -> display(Nein)
-> saveVerfahrensArt -> saveKatAnspruch
-> anspruchWeiter(Abtretung) -> display[Abtretung]
-> anspruchWeiter(Zinsen)    -> display[LaufendeZinsen]
-> anspruchWeiter(Weiter)
-> saveAuslagenNebenforderungen [+Warnung quittieren]
-> saveProzessVertreterVerguetung -> showAllgemeineAngaben
-> saveAllgemeineAngaben -> saveBankVerbindung
-> saveMBAntragUebersicht -> abgabeMBEda [Download]
```
`*` = Command **UNVERIFIZIERT**

---

## 7. Nicht erfasst — offene Punkte

| Punkt | Warum relevant |
|---|---|
| Antragsteller-Maske "Firma" (Feldnamen, `Command`) | Kernmaske bei juristischen Personen als Antragsteller; Werte belegt, Feldnamen nur erschlossen |
| Reiter "RA-Gesellschaft" beim Prozessbevollmächtigten | bei einer Rechtsanwaltsgesellschaft mbH voraussichtlich der richtige Reiter |
| Reiter "Kennziffer" und "Sonstige" (Antragsteller), "Sonstige" (Antragsgegner) | Alternative Erfassungswege |
| Reiter "Sonst. Anspruch" und "ausgerechneter Zins" | Alternative Anspruchsarten |
| Untermaske "Sonstige Nebenforderungen anlegen/bearbeiten" | zusätzliche Nebenforderungen |
| Untermaske "bearbeiten" beim Prozessgericht | manuelle Gerichtsstandswahl (§ 32 ZPO bei Delikt) |
| Gesamtschuldner-Frage bei **mehreren** Antragsgegnern | Massenfälle mit mehreren Gegnern |
| Zusatzmaske bei **ausländischem** Antragsteller/Antragsgegner | EU-Fälle |
| Verhalten bei einem **echten Fehler** (nicht Warnung) | Erkennung; `FehlerDa=true`? |
| Wortlaut weiterer Warnungen | Liste bekannter Warnungen für die Quittierung |
| Dateiname / Content-Type der EDA-Datei | Nachbau des Downloads |
| Maske "Ausdruck" nach dem Download | Aktenexemplar |
| Ob `_bKostenstatus`/`_bProzesskostenhilfe` weitere Optionswerte haben | Auslesen war blockiert |
