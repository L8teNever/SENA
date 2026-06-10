# SENA — Gmail Automatisierung

SENA ist eine webbasierte, containerisierte Python-Anwendung zur automatischen Sortierung und Verwaltung deines Gmail-Postfachs. 

Das Interface ist im modernen **Android 16 / Material You Design** (Dark-Mode, Glassmorphismus, flüssige Animationen) gehalten und ermöglicht die vollständige Konfiguration aller Automatisierungsregeln.

## Features
- **OAuth2 Login**: Sichere Anmeldung über Google OAuth2. Token werden lokal und verschlüsselt gespeichert und ermöglichen Offline-Hintergrundverarbeitung.
- **Benutzerdefinierte Regeln**: 
  - E-Mails von bestimmten Absendern filtern.
  - E-Mails an bestimmte Empfänger (z.B. Aliase) filtern.
  - Kombination aus Absender und Betreff-Stichwörtern filtern.
  - E-Mails anhand von Betreff-Schlüsselwörtern filtern.
  - Automatische Archivierung (aus Posteingang verschieben) und Markierung als unwichtig bei Übereinstimmung.
- **Automatische Verifizierungscode-Archivierung**:
  - Erkennt Codes und Einmalpasswörter (z.B. "Dein Verifizierungscode", "Bestätige deine E-Mail", "One-Time Password").
  - Archiviert diese automatisch aus Inbox & Important nach **24 Stunden** in das Label `SENA/Verifizierungen`.
- **Super Wichtig Kontakte**:
  - Erkennt Personen, an die du E-Mails sendest, und fügt sie automatisch zu deiner VIP-Liste hinzu.
  - E-Mails von diesen Kontakten erhalten automatisch das Label `Super Wichtig`.
- **Lokale Logs**: Echtzeit-Logkonsole, die alle Aktionen des Hintergrund-Workers direkt im Browser anzeigt.
- **Kein E-Mail-Inhalt im Web**: Aus Sicherheitsgründen werden die Mail-Inhalte selbst nicht auf der Webseite geladen oder angezeigt.

---

## 🛠️ Google Cloud Einrichtung (OAuth2)

Um die Gmail-API nutzen zu können, musst du Client-Zugangsdaten in der Google Cloud erstellen:

1. Gehe in die [Google Cloud Console](https://console.cloud.google.com/).
2. Erstelle ein neues Projekt mit dem Namen **SENA**.
3. Suche nach **Gmail API** und aktiviere diese für dein Projekt.
4. Gehe auf den **OAuth-Zustimmungsbildschirm** (OAuth Consent Screen):
   - Wähle **Extern** (oder Intern, falls verfügbar).
   - Trage die Pflichtfelder ein.
   - Füge unter **Bereiche (Scopes)** die Scopes `.../auth/gmail.modify` und `openid` hinzu.
   - Füge unter **Testnutzer** deine eigene Gmail-Adresse hinzu (solange das Projekt im Status "Test" ist, können sich nur eingetragene Testnutzer anmelden!).
5. Gehe auf **Anmeldedaten** (Credentials):
   - Klicke auf **Anmeldedaten erstellen** -> **OAuth-Client-ID**.
   - Anwendungstyp: **Webanwendung**.
   - Name: `SENA Web App`.
   - Autorisierte JavaScript-Herkunfte: `http://localhost:8000`.
   - Autorisierte Weiterleitungs-URIs: `http://localhost:8000/oauth2callback`.
   - Klicke auf **Erstellen** und kopiere die **Client-ID** und das **Client-Secret**.

---

## 🚀 Starten mit Docker Compose

Du kannst die App direkt über Docker Compose starten:

1. Öffne ein Terminal im Projektordner.
2. Starte die Container mit:
   ```bash
   docker-compose up --build -d
   ```
3. Öffne [http://localhost:8000](http://localhost:8000) im Browser.
4. Du wirst nach deiner Google Client-ID und deinem Client-Secret gefragt. Füge diese ein und klicke auf Speichern.
5. Klicke anschließend auf **"Mit Google anmelden"**.

### Starten ohne Docker (Lokale Entwicklung)

Falls du das Skript direkt ausführen möchtest:

1. Installiere die Abhängigkeiten:
   ```bash
   pip install -r requirements.txt
   ```
2. Kopiere die Datei `.env.example` zu `.env` und trage optional deine Zugangsdaten ein:
   ```bash
   cp .env.example .env
   ```
3. Starte den Uvicorn-Server:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
4. Öffne [http://localhost:8000](http://localhost:8000) im Browser.
