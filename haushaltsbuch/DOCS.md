# Haushaltsbuch – Dokumentation

## Installation

1. In Home Assistant: **Einstellungen → Apps → App-Store → ⋮ (oben rechts) → Repositories**.
2. `https://github.com/nstueber/HAFin` hinzufügen.
3. „Haushaltsbuch“ im Store öffnen, **Installieren** und **Starten**.
4. Optional „In der Seitenleiste anzeigen“ aktivieren – die App öffnet sich über den Eintrag
   **Haushaltsbuch** in der Seitenleiste (Ingress).

Die App hat bewusst **keinen eigenen Netzwerk-Port**: sie ist nur über den Home-Assistant-
Ingress erreichbar und damit durch die Authentifizierung von Home Assistant geschützt.

## Optionen

Die App hat **keine Konfigurationsoptionen** (`options`/`schema` sind nicht definiert) – alles
wird in der App selbst eingestellt.

## Erste Schritte in der App

1. **Einstellungen → Konten** → „Neues Konto“ anlegen (Name, IBAN).
2. **Einstellungen → Mapping-Profile** → „Neues Profil anlegen“: eine Beispiel-CSV der Bank hochladen; Trennzeichen,
   Kodierung, Datumsformat und Spaltenzuordnung werden erkannt und lassen sich prüfen.
3. **Import** → Konto und Profil wählen, CSV hochladen. Bereits vorhandene Buchungen werden als
   Duplikate übersprungen (übersprungene Zeilen lassen sich bei Bedarf trotzdem importieren).
4. **Buchungen** → Kategorien zuweisen, Umbuchungen bestätigen, Bargeld aufteilen.
5. **Übersicht** → Kennzahlen und Kategorie-Diagramm; ein Klick auf eine Zahl oder einen Balken
   zeigt die zugrunde liegenden Buchungen.

## Daten und Backup

- Die Datenbank ist die SQLite-Datei `/data/haushaltsbuch.db` im persistenten App-Verzeichnis.
- Die App ist mit `backup: cold` konfiguriert: Supervisor **stoppt sie kurz vor jedem Backup** und
  startet sie danach wieder. So entsteht garantiert ein konsistenter Snapshot der SQLite-Datei.
- **Wiederherstellen:** Backup in Home Assistant einspielen (nur diese App oder komplett).
- Schema-Änderungen bei Updates werden beim Start der App automatisch eingespielt. Trotzdem:
  vor einem Update ein Backup anlegen (Home Assistant bietet das im Update-Dialog an).

## Backup & Restore in der App (portables JSON-Backup)

Zusätzlich zum Home-Assistant-Backup gibt es in der App unter **Einstellungen → Backup & Restore** eine eigene Export-/Import-Funktion. Sie erzeugt
ein **portables, menschenlesbares JSON-Backup** der fachlichen Daten (unabhängig von Supervisor-Snapshots) –
z. B. für den Umzug von der Test- auf die produktive Instanz.

**Exportieren:** Datengruppen per Checkbox wählen (Konten, Kategorien, Mapping-Profile, Buchungen inkl.
Bargeld-Splits) → Datei `haushaltsbuch-backup-<Zeitstempel>.json` wird heruntergeladen. „Buchungen“
benötigen Konten und Kategorien – diese werden dann automatisch mitexportiert. Mit enthalten sind auch
die vom Nutzer abgelehnten Umbuchungs-Vorschläge („Keine Umbuchung“), damit sie nach einem Umzug nicht
erneut vorgeschlagen werden.

**Importieren:** Datei auswählen → **Vorschau** (Format, Version, Kennzahlen, Warnungen) → Datengruppen
wählen (eine Teilmenge ist möglich, z. B. nur Konten + Kategorien + Mapping-Profile) → Modus wählen:

| Modus | Voraussetzung | Wirkung |
| --- | --- | --- |
| **In leere Datenbank importieren** | Zieldatenbank enthält keine Konten und keine Buchungen | Fügt die Daten hinzu. Die Systemkategorien „Umbuchung“/„Bargeld“ werden nicht neu angelegt, sondern über ihren festen `system_key` mit den vorhandenen verknüpft. |
| **Bestehende Daten vollständig ersetzen** | Bestätigung durch Eingabe des Wortes `LÖSCHEN` | **Destruktiv:** löscht die bestehenden Daten der gewählten Gruppen und ersetzt sie. Vorher wird automatisch ein **Sicherheits-Backup** des aktuellen Bestands erzeugt (Download nach dem Import; abgelegt unter `/data/backups/`, die neuesten 10 bleiben). Werden Konten oder Kategorien ersetzt, müssen auch alle bestehenden Buchungen gelöscht werden – die Vorschau zeigt vorab, wie viele Datensätze verloren gehen. |

Der Import läuft in **einer einzigen Datenbank-Transaktion**: schlägt irgendetwas fehl, wird alles
zurückgerollt und der vorherige Zustand bleibt erhalten. Danach zeigt ein Ergebnis-Report die importierten
Datensätze je Typ, die ein-/ausgeschlossenen Datengruppen und Warnungen (z. B. ignorierte oder mit
Standardwerten gefüllte Felder älterer Backups).

**Skript-/Automatisierungs-Zugriff** (dieselben Endpunkte wie die Oberfläche; hinter dem Ingress nur aus
der App heraus erreichbar, lokal z. B. per `curl`):

```bash
# Export (ohne groups = alles)
curl -OJ "http://localhost:8000/backup/export?groups=accounts&groups=categories&groups=transactions"
# Import in eine leere Instanz, Ergebnis als JSON
curl -H "Accept: application/json" -F file=@haushaltsbuch-backup-....json -F mode=empty \
     http://localhost:8000/backup/import
# Ersetzen (Bestätigungswort nötig)
curl -H "Accept: application/json" -F file=@backup.json -F mode=replace -F confirm_text=LÖSCHEN \
     http://localhost:8000/backup/import
```

**Format:** ein JSON-Dokument, beginnend mit einem `meta`-Block (`format`, `schema_version` – eigene, von der
App-Version unabhängige Versionsnummer des Backup-Formats –, `app_version`, `exported_at`, enthaltene Gruppen,
Kennzahlen). Alle Verknüpfungen verwenden exportinterne UUIDs (`export_id`) statt Datenbank-IDs, deshalb ist das
Backup in jede andere Instanz importierbar.

## Kategorisierungsregeln

Unter **Einstellungen → Kategorisierungsregeln** legst du Regeln an, die neu importierte Buchungen automatisch einer
Kategorie zuordnen: *Feld* (Verwendungszweck oder Auftraggeber/Empfänger) + *Bedingung* (enthält, beginnt mit, ist
exakt) + *Vergleichswert* → *Ziel-Kategorie*. Groß-/Kleinschreibung spielt keine Rolle. Die Regeln werden von oben nach
unten geprüft, **die erste passende gewinnt** – mit den Pfeilen änderst du die Reihenfolge. Bereits vorhandene oder
manuell kategorisierte Buchungen werden nie verändert.

- **Beim CSV-Import** werden die Regeln automatisch auf neue Buchungen angewendet (die Ergebnisseite zeigt, wie viele).
- **Fest zuweisen oder nur vorschlagen:** Bei „Nur als Vorschlag anzeigen“ bleibt die Buchung unkategorisiert; in der Buchungsliste
  erscheint „Vorschlag: … übernehmen“ (ein Klick setzt die Kategorie).
- **Rückwirkend mit Vorschau:** „Vorschau ansehen…“ listet die Treffer auf bereits vorhandene, noch unkategorisierte Buchungen.
  Du wählst einzelne Treffer ab und bestätigst erst mit „Ausgewählte anwenden“.
- **Schnell anlegen:** im Detailfenster einer Buchung „Regel aus dieser Buchung erstellen“ – das Formular ist mit
  Verwendungszweck/Auftraggeber und der Kategorie der Buchung vorausgefüllt.

## Budgets

Unter **Einstellungen → Budgets** legst du pro Kategorie (Ober- oder Unterkategorie) einen Monatsbetrag fest (leer oder 0 =
kein Budget). In der **Übersicht** erscheint bei den Zeiträumen „Monat“ und „Jahr“ (dort Monatsbetrag × 12) der Bereich „Budgets“ mit
einem Fortschrittsbalken je Kategorie (grün bis 79 %, gelb 80–100 %, rot darüber); ein Klick zeigt die zugehörigen Buchungen. Ausgaben einer Unterkategorie zählen auch in das Budget ihrer
Oberkategorie. Gezählt werden alle Konten, ohne Umbuchungen.

## Alle Daten löschen

Unter **Einstellungen → Backup & Restore → Alle Daten löschen** setzt du die Datenbank komplett zurück (Konten,
Kategorien außer den Systemkategorien, Mapping-Profile, Regeln, Budgets, Buchungen). Zur Sicherheit musst du `LÖSCHEN`
eingeben; direkt vor dem Löschen wird automatisch ein Sicherheits-Backup erstellt, das du danach herunterladen kannst.
Kategorisierungsregeln und Budgets sind auch Teil des Backups (eigene Datengruppen beim Export/Import).

## Version und Lizenzen

Die installierte Version steht unten in der Seitenleiste und auf der Seite **Einstellungen**. Dort führt auch der
Link **Lizenzinformationen** zu den verwendeten Drittkomponenten und ihren Lizenzen.

## Fehlersuche

| Symptom | Ursache / Lösung |
| --- | --- |
| Seite bleibt leer oder ohne Formatierung | Im Reiter **Protokoll** der App nach Fehlern suchen. Einige Bibliotheken (Tabellen-Sortierung, Auswahlfelder, Diagramm) werden vom Browser aus dem Internet (CDN) geladen – ohne Internetzugriff des Browsers fehlen diese Funktionen. |
| Links/Buttons führen ins „Nichts“ oder zur Home-Assistant-Startseite | Die App schreibt URLs hinter dem Ingress-Pfad automatisch um. Tritt das trotzdem auf: Seite neu laden; sonst bitte im Protokoll nachsehen und ein Issue mit der betroffenen Seite anlegen. |
| App startet nicht / startet neu | Protokoll ansehen. Häufigste Ursache: beschädigte oder gesperrte Datenbankdatei – App stoppen, aus einem Backup wiederherstellen, erneut starten. |
| Direkter Aufruf `http://<HA-IP>:8000` funktioniert nicht | Gewollt – nur über den Ingress (Seitenleiste) erreichbar. |
| Alles zurücksetzen | App deinstallieren (löscht die Daten!) oder Backup einspielen. Vorher unbedingt ein Backup anlegen. |

---

# Für Entwickler: Releases und lokales Testen

## Versionierung (SemVer)

Es gilt [Semantic Versioning](https://semver.org/lang/de/) (`MAJOR.MINOR.PATCH`). Bei **jedem** Release
müssen diese drei Stellen synchron sein, bevor getaggt wird:

1. `version` in `haushaltsbuch/config.yaml` (z. B. `"0.2.0"`)
2. der Git-Tag `vX.Y.Z` (z. B. `v0.2.0`) – der Image-Tag ist die Version **ohne** `v`
3. ein Eintrag `## [X.Y.Z] - Datum` in `haushaltsbuch/CHANGELOG.md`

Der Release-Workflow bricht ab, wenn Tag, `config.yaml` und Changelog nicht zusammenpassen oder
der getaggte Commit nicht auf `main` liegt.

## Release-Ablauf

1. Features/Bugfixes auf `main` (oder kurzlebigen Branches, die nach `main` gemergt werden).
2. **Vor dem Release** die HA-spezifischen Punkte in der lokalen Test-Instanz prüfen (siehe unten):
   Ingress, Backup/Restore, Update-Pfad.
3. `version` in `config.yaml` erhöhen und `CHANGELOG.md` ergänzen („Unveröffentlicht“ → neue Version).
4. Committen, dann taggen und pushen:
   ```bash
   git commit -am "Release 0.2.0"
   git tag v0.2.0
   git push origin main v0.2.0
   ```
5. GitHub Actions (`.github/workflows/release.yml`) baut `amd64` + `aarch64`, veröffentlicht die
   Images nach `ghcr.io/nstueber/hafin-haushaltsbuch` (Tags `0.2.0` und `latest`) und das
   Multi-Arch-Manifest. Home Assistant zeigt das Update danach im Store an.

**Einmalig nach dem allerersten Push:** das GHCR-Package in den GitHub-Paketeinstellungen auf
**„Public“** stellen (siehe Kommentar im Workflow), sonst kann Supervisor das Image nicht ohne
Zugangsdaten ziehen.

## Lokale Test-Instanz (Devcontainer)

> **Wichtig:** Dafür **nicht** die produktive Home-Assistant-Instanz verwenden, die das Zuhause
> steuert. Der Devcontainer startet eine komplett getrennte Test-Instanz von Supervisor und
> Home Assistant mit eigenen Daten.

Der schnelle Dev-Loop ohne Supervisor bleibt davon unabhängig: `docker compose up --build`
(siehe Root-README) bzw. `uvicorn` direkt.

**Voraussetzungen:** Docker, VS Code mit Erweiterung „Dev Containers“.

1. Repository in VS Code öffnen → „In Container erneut öffnen“ (nutzt `.devcontainer/devcontainer.json`).
2. Im Container: **Terminal → Task ausführen → „Start Home Assistant“** (führt `supervisor_run` aus).
3. Home Assistant unter <http://localhost:7123> öffnen und das Onboarding durchlaufen (Test-Benutzer anlegen).
4. **App installieren:** Der Workspace ist im Container als „Lokale Apps“-Repository eingehängt, die App
   erscheint nach **Einstellungen → Apps → App-Store → ⋮ → Nach Updates suchen** unter „Lokale Apps“ als
   **„Haushaltsbuch“** (Slug `local_haushaltsbuch`, Ordner `haushaltsbuch/` dieses Repositories – es gibt keine
   separate Kopie). Da `config.yaml` ein `image:` enthält, zieht Supervisor `ghcr.io/nstueber/hafin-haushaltsbuch:<version>`;
   installierbar ist also nur eine bereits veröffentlichte Version.
5. **DEV-Stand mit neuer Buildnummer testen:** `config.yaml` enthält die Release-Version (z. B. `0.3.1`). Für jeden DEV-Stand
   ```bash
   bash .devcontainer/sync-dev-app.sh --dev-build    # Version "0.3.1-dev.<N>", N zählt bei jedem Aufruf hoch
   ```
   Das kommentiert `image:` aus (Supervisor baut lokal aus dem Dockerfile) und vergibt eine **neue Buildnummer**
   (Zähler in `.devcontainer/.dev-build-number`, nicht im Git; bei neuer Basisversion wieder ab 1). Für Supervisor ist jeder Stand eine
   neue Version: nach „Nach Updates suchen“ zeigt der Store „Update verfügbar“, „Aktualisieren“ baut den aktuellen Code. Die
   Buildnummer steht in der App (Seitenleiste, Einstellungen, `meta.app_version` der Backups) – auch im lokalen Docker-Image, wenn es
   aus demselben Stand gebaut wird. Nach dem Test `bash .devcontainer/sync-dev-app.sh --reset` (Basisversion ohne Buildnummer, `image:`
   wieder aktiv). **Das Skript ändert die echte `config.yaml`;** der Release-Workflow bricht ab, falls ein auskommentiertes `image:`
   committet wurde. Ohne `--dev-build` bleibt `image:` aktiv: das Update wird erkannt, das Ausführen zieht aber `…:<version>` aus GHCR
   und gelingt erst nach dem Release.

**Was vor einem Release geprüft werden soll:**

| Bereich | Prüfung |
| --- | --- |
| Ingress | App über die Seitenleiste öffnen; alle Seiten durchklicken, Formulare abschicken, CSV hochladen, Dashboard-Drilldown, Dialoge (kein Link darf ins HA-Root führen). |
| Options-Schema | Die App hat keine Optionen – Reiter „Konfiguration“ zeigt nichts; sicherstellen, dass das so bleibt, bzw. bei neuen Optionen `options`/`schema` in `config.yaml` ergänzen. |
| Backup/Restore | Daten anlegen → Backup erstellen (App wird dafür kurz gestoppt) → Daten ändern → Backup einspielen → Daten müssen wieder da sein. |
| Update-Pfad | Installierte Version → `sync-dev-app.sh --dev-build` → „Nach Updates suchen“ → Store zeigt „Update verfügbar“ → Update anstoßen (lokaler Build) → Daten und Schema müssen erhalten bleiben (Auto-Migration beim Start). Danach `sync-dev-app.sh --reset`. |
