# Katalog `_bKatalogArt` — Anspruchskatalog (Schritt 4, Maske "KatAnspruch")

75 Sachanspruchsarten plus Leeroption. Der Code steht zusätzlich in Klammern im Anzeigetext.

Feld `KatNr` (Text, max 2) erlaubt die direkte Eingabe der Nummer statt der Auswahl aus der Liste —
**für ein Skript der einfachere Weg**: Nummer in `KatNr` schreiben statt die Auswahlliste zu bedienen.

Achtung: `KatNr` hat max=2, Codes bis 95 passen, dreistellige gibt es nicht.

| Code | Anspruchsart |
|---|---|
| (leer) | Leeroption |
| 1 | Anzeigen in Zeitungen u.a. |
| 2 | Ärztliche oder zahnärztliche Leistung |
| 95 | Beiträge zur privaten Pflegeversicherung |
| 3 | Bürgschaft |
| 4 | Darlehensrückzahlung |
| 5 | Dienstleistungsvertrag |
| 69 | Entgeltforderung gem. Telekom-Rechnung |
| 81 | Entschädigung d. Sortenschutzinhabers f. Nachbau |
| 49 | Erhöhtes Beförderungsentgelt für eine Fahrt ohne gült. Fahrausweis ..Linie.. am ... |
| 6 | Frachtkosten |
| 7 | Geschäftsbesorgung durch Selbständige |
| 85 | Güterrechtlicher Ausgleichsanspruch bei Beendigung des Güterstandes |
| 8 | Handwerkerleistung |
| 9 | Heimunterbringung |
| 10 | Hotelkosten |
| 50 | Inkassokst. f. außerger. Vergleich/Abzahl.vereinb. |
| 11 | Kaufvertrag |
| 70 | Kindertagesstättenbeitrag |
| 12 | Kontokorrentabrechnung |
| 13 | Krankenhauskosten -Pflege/Behandlung- |
| 77 | Krankentransportkosten |
| 74 | Kreditkartenvertrag |
| 14 | Lagerkosten |
| 15 | Leasing/Mietkauf |
| 16 | Lehrgangs-/Unterrichtskosten |
| 21 | Miete (sonstige) |
| 17 | Miete für Geschäftsraum einschl. Nebenkosten |
| 18 | Miete für Kraftfahrzeug |
| 19 | Miete für Wohnraum einschl. Nebenkosten |
| 20 | Mietnebenkosten - auch Renovierungskosten - nur bei Wohnraummiete |
| 22 | Mitgliedsbeitrag |
| 23 | Pacht |
| 83 | Prämienrückstand für Krankheitskostenvers. gem. § 193 Abs. 6 VVG |
| 82 | Prämienzuschlag für Krankheitskostenvers. wegen Nichtversicherung gem. § 193 Abs. 4 VVG |
| 24 | Rechtsanwalts-/Rechtsbeistandshonorar |
| 75 | Reisevertrag |
| 25 | Rentenrückstände |
| 26 | Reparaturleistung |
| 80 | Rückgriff aus Bürgschaft oder Garantie |
| 27 | Rückgriff aus Versich.vertrag wg. Unfall/Vorfall |
| 72 | Rückzahlg. aus grundpfandrechtl. gesichert. Kreditvertr. / gleichgest. Darl. n. Bausp.kassenges. |
| 54 | Rückzahlg. v. Handelsvertreterprovis. § 87a(2) HGB |
| 84 | Säumniszuschlag für Prämienrückstand zur Krankheitskostenvers. gem. § 193 Abs. 6 VVG |
| 28 | Schadenersatz aus ...-Vertrag |
| 29 | Schadenersatz aus Unfall/Vorfall |
| 30 | Scheck/Wechsel |
| 31 | Scheck-/Wechselprovision (1/3 %) |
| 32 | Scheck-/Wechselunkosten -Spesen/Protest- |
| 33 | Schuldanerkenntnis |
| 86 | Sonstiger familienrechtlicher Anspruch nach § 112 Ziff. 3 FamFG |
| 34 | Speditionskosten |
| 76 | Telekommunikationsleistungen |
| 78 | Tierärztliche Leistung |
| 35 | Tilgungs-/Zinsraten |
| 36 | Überziehung des Bankkontos |
| 37 | Ungerechtfertigte Bereicherung |
| 38 | Unterhaltsrückstände |
| 57 | Urheberrecht: gesetzl. Vergütungsanspruch nach § 27 UrhG |
| 73 | Urheberrecht: gesetzl. Vergütungsanspruch nach § 54 UrhG |
| 56 | Urheberrechtl. geschützte Werke: unerlaubte Nutzung aus dem Repertoire des Antragstellers |
| 58 | Urheberrechtl. Nutzungsrechte: fällige Pauschale aus Vertrag |
| 39 | Vergleich (außergerichtlicher) |
| 40 | Vermittlungs-/Maklerprovision (nicht Eheverm.) |
| 79 | Verpflegungskosten |
| 41 | Versicherungsprämie/-beitrag (ohne Pflegevers.) |
| 60 | Versorgungsleistung |
| 42 | Versorgungsleistung -Strom/Wasser/Gas/Wärme- |
| 71 | Verzugsschaden (n. anrechenbare RA-Kosten aus vorger. Tätigkeit) |
| 61 | Wahlleistungen bei stationärer Behandlung |
| 43 | Warenlieferung-en |
| 44 | Werkvertrag/Werklieferungsvertrag |
| 90 | Wohn-/Hausgeld für Wohnungseigentümergemeinschaft |
| 55 | Zahlung kassiert und nicht abgeführte Inkassogelder |
| 45 | Zeitungs-/Zeitschriftenbezug |
| 46 | Zinsrückstände/Verzugszinsen |

## Katalog `_aspAspGr` — Anspruchsgrundlage (Belegart), 10 Optionen

Die Werte sind **Klartext-Strings, keine Zahlen**.

| Wert | Anzeigetext |
|---|---|
| (leer) | – |
| `Schreiben` | Schreiben |
| `Rechnung` | Rechnung |
| `Mahnung` | Mahnung |
| `Kontoauszug` | Kontoauszug |
| `Aufstellung` | Aufstellung |
| `Vertrag` | Vertrag |
| `Stromrechnung` | Stromrechnung |
| `Gasrechnung` | Gasrechnung |
| `Sonstiger` | andere &nbsp;&nbsp;← Wert und Anzeigetext weichen ab |

Falle: bei `Sonstiger` ist der übertragene Wert `Sonstiger`, angezeigt wird aber "andere".
Bei allen anderen Optionen sind Wert und Text identisch.
