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

1. **Konten** → „Neues Konto“ anlegen (Name, IBAN).
2. **Mapping-Profile** → „Neues Profil anlegen“: eine Beispiel-CSV der Bank hochladen; Trennzeichen,
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
4. **Lokale App bereitstellen:** Solange noch kein Release veröffentlicht ist, würde Supervisor wegen
   des `image:`-Felds versuchen, das (noch nicht vorhandene) Image zu ziehen. Deshalb im Container:
   ```bash
   bash .devcontainer/sync-dev-app.sh          # legt eine lokal baubare Kopie an
   ```
   Sie erscheint nach **Einstellungen → Apps → App-Store → ⋮ → Nach Updates suchen** unter
   „Lokale Apps“ als **„Haushaltsbuch (Dev)“** (ohne `image:`, eigener Slug `haushaltsbuch_dev`,
   wird lokal gebaut). Der Eintrag „Haushaltsbuch“ ohne „(Dev)“ ist derselbe Ordner mit
   `image:`-Feld und für diese Tests nicht relevant.
5. Nach Codeänderungen: Skript erneut ausführen, die App im Store **neu bauen/aktualisieren**.

**Was vor einem Release geprüft werden soll:**

| Bereich | Prüfung |
| --- | --- |
| Ingress | App über die Seitenleiste öffnen; alle Seiten durchklicken, Formulare abschicken, CSV hochladen, Dashboard-Drilldown, Dialoge (kein Link darf ins HA-Root führen). |
| Options-Schema | Die App hat keine Optionen – Reiter „Konfiguration“ zeigt nichts; sicherstellen, dass das so bleibt, bzw. bei neuen Optionen `options`/`schema` in `config.yaml` ergänzen. |
| Backup/Restore | Daten anlegen → Backup erstellen (App wird dafür kurz gestoppt) → Daten ändern → Backup einspielen → Daten müssen wieder da sein. |
| Update-Pfad | Installierte Version → `sync-dev-app.sh 0.1.1` (überschreibt die Version der Dev-Kopie) → Update im Store anstoßen → Daten und Schema müssen erhalten bleiben (Auto-Migration beim Start). |
