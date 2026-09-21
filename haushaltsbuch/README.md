# Haushaltsbuch

Haushaltsbuch zur Verwaltung von Ein- und Ausgaben über mehrere Bankkonten hinweg – direkt
in Home Assistant, ohne Cloud.

- **CSV-Import** von Kontoauszügen mit wiederverwendbaren Mapping-Profilen (eines pro Bank),
  automatischer Erkennung von Trennzeichen/Kodierung/Datumsformat und Duplikat-Erkennung
- **Kategorien** (Ober-/Unterkategorien), Mehrfachzuweisung, Bargeld-Aufteilung
- **Umbuchungserkennung** zwischen den eigenen Konten
- **Dashboard** mit Zeitraum-Navigation, Kennzahlen und Kategorie-Diagramm inkl. Drilldown
- Suche, Filter, Sortierung und eine mobile Ansicht für das Smartphone

Die App erscheint nach der Installation als Eintrag **„Haushaltsbuch“** in der Seitenleiste
von Home Assistant (Ingress, kein zusätzlicher Port nötig). Alle Daten liegen lokal in einer
SQLite-Datei im persistenten App-Verzeichnis und werden von den Home-Assistant-Backups erfasst.

Ausführliche Hinweise zu Nutzung, Backup und Fehlersuche stehen im Reiter **Dokumentation**.
