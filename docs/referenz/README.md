# mahnantrag-portal-reference

Technische Referenz zum bundesweiten Online-Mahnantrag (`online-mahnantrag.de`):
Maskenabfolge, Formularsteuerung, Feldkatalog und Formatregeln — durch systematische
Analyse des Portals erschlossen.

## Was das ist

Das Portal ist als Frameset ohne stabile Feld-IDs aufgebaut und wird über einen einzigen
versteckten `Command`-Parameter gesteuert. Die URL bleibt über alle Schritte identisch,
die Maskenfolge ist nicht deterministisch. Eine öffentliche Dokumentation der Struktur
existiert nicht.

Wer den Antragsweg programmatisch nachbilden, prüfen oder testen will, muss sich diese
Grundlage selbst erarbeiten. Genau das ist hier dokumentiert.

## Inhalt

| Datei | Inhalt |
|---|---|
| [`implementierung-spec.md`](implementierung-spec.md) | Grundarchitektur, Ablaufsteuerung als Zustandsmaschine, alle 26 Masken mit Feldern, Typen, Maximallängen und Optionswerten, Formatregeln, dokumentierte Fehlerquellen, Skriptgerüst |
| [`anspruchskatalog.md`](anspruchskatalog.md) | Katalog der 75 Sachanspruchsarten und der 10 Anspruchsgrundlagen |
| [`rechtsform-katalog.md`](rechtsform-katalog.md) | Katalog der 178 Rechtsformen, deutsch und ausländisch |

## Methodik

Alles Dokumentierte ist an der laufenden Anwendung beobachtet, nicht aus Herstellerdokumentation
abgeleitet. Punkte, die aus Symmetrie zu anderen Masken erschlossen und nicht direkt belegt sind,
sind im Text als **UNVERIFIZIERT** gekennzeichnet. Abschnitt 7 listet auf, was bewusst nicht
erfasst wurde und warum es relevant ist.

## Nutzung

Der elektronische Versand erfolgt nach § 130a Abs. 4 ZPO über einen sicheren Übermittlungsweg
(beA, beBPo, eBO, absenderbestätigte De-Mail). Die vom Portal erzeugte EDA-Datei darf nach dem
Download **nicht** verändert werden — jede Änderung zerstört ihre Integrität und macht sie für
das Mahngericht unverarbeitbar. Ein rein lesender Abgleich gegen eine Referenzdatei ist davon
nicht betroffen.

## Stand

Erhoben im September 2026. Das Portal kann sich jederzeit ändern; die Angaben sind eine
Momentaufnahme und ersetzen keine eigene Prüfung.

## Lizenz

CC BY 4.0 — Weiterverwendung mit Namensnennung.
