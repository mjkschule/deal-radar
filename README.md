# 📡 Deal-Radar

Sucht bis einschließlich **Black Friday (27.11.2026, 23:59 Uhr)** alle 2 Stunden automatisch nach guten
Angeboten für deine Produkte, schickt dir eine **Telegram-Nachricht**, wenn ein Deal gut ist, und zeigt auf
einer **Startseite** für jedes Produkt den aktuell günstigsten Preis.

- **Startseite:** https://mjkschule.github.io/deal-radar/
- **Läufe ansehen / manuell starten:** Reiter **Actions** im Repo
- **Produkte:** Datei [`products.yaml`](products.yaml) · **Einstellungen:** [`config.yaml`](config.yaml)

---

## 1. Einrichtung (einmalig, ca. 10 Minuten)

Das Repo, GitHub Pages und die Workflows sind schon eingerichtet. Es fehlen nur noch deine
Telegram-Zugangsdaten (und optional die eBay-Schlüssel).

### 1.1 Telegram-Bot anlegen (@BotFather)

1. Öffne Telegram (Handy oder Desktop) und suche nach **@BotFather** (blauer Haken!).
2. Tippe auf **Start** und sende `/newbot`.
3. BotFather fragt nach einem **Namen** (frei wählbar, z. B. `Mein Deal-Radar`).
4. Danach nach einem **Benutzernamen**; er muss auf `bot` enden, z. B. `mein_dealradar_bot`.
5. Du bekommst eine Nachricht mit dem **Token**, er sieht etwa so aus:
   `7123456789:AAH...langer-Text...`
   ⚠️ Der Token ist wie ein Passwort: nicht weitergeben, nicht in Dateien im Repo speichern.

### 1.2 Deine Chat-ID herausfinden

1. Suche in Telegram deinen neuen Bot (den Benutzernamen aus Schritt 4) und tippe auf **Start**.
   Schreib ihm irgendwas, z. B. „Hallo“.
2. Öffne im Browser diese Adresse (setze deinen Token statt `<TOKEN>` ein):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Suche in der Antwort die Stelle `"chat":{"id":123456789` → diese Zahl ist deine **Chat-ID**.
   (Steht dort nur `{"ok":true,"result":[]}`, schreib dem Bot noch einmal und lade die Seite neu.)

### 1.3 Token und Chat-ID als GitHub-Secrets speichern

Secrets sind verschlüsselt; niemand (auch nicht in einem öffentlichen Repo) kann sie lesen.

**Variante Webbrowser:**
1. Öffne https://github.com/mjkschule/deal-radar/settings/secrets/actions
2. Klicke **New repository secret**.
3. Name: `TELEGRAM_BOT_TOKEN`, Secret: dein Token → **Add secret**.
4. Nochmal **New repository secret**: Name `TELEGRAM_CHAT_ID`, Secret: deine Chat-ID → **Add secret**.

**Variante Terminal** (die Eingabe ist unsichtbar, einfach einfügen und Enter drücken):
```bash
gh secret set TELEGRAM_BOT_TOKEN --repo mjkschule/deal-radar
```
```bash
gh secret set TELEGRAM_CHAT_ID --repo mjkschule/deal-radar
```

### 1.4 Testnachricht schicken

1. Öffne https://github.com/mjkschule/deal-radar/actions/workflows/radar.yml
2. Rechts **Run workflow** → Haken bei **„Nur eine Telegram-Testnachricht senden“** → grüner Knopf **Run workflow**.
3. Nach ca. 30 Sekunden sollte auf deinem Handy „✅ Deal-Radar ist eingerichtet!“ ankommen.

Oder im Terminal:
```bash
gh workflow run radar.yml --repo mjkschule/deal-radar -f test_telegram=true
```

### 1.5 eBay (optional)

Ohne eBay-Schlüssel steht die Quelle auf der Startseite einfach auf „aus“. So richtest du sie ein:

1. Gehe zu https://developer.ebay.com → **Register** (kostenlos, mit deinem normalen eBay-Konto möglich).
2. Nach der Bestätigung: oben **Hi <Name>** → **Application Keysets** → bei **Production** einen
   Namen eingeben (z. B. `dealradar`) → **Create a keyset**.
3. eBay verlangt eine Einstellung zu „Marketplace Account Deletion Notifications“. Wähle die Option
   **„Not persisting eBay data“** bzw. „exempted“; das Radar speichert keine eBay-Kontodaten.
   Erst danach wird das Production-Keyset aktiv (das kann bis zu 1 Werktag dauern).
4. Kopiere **App ID (Client ID)** und **Cert ID (Client Secret)**.
5. Lege zwei Secrets an (wie in 1.3): `EBAY_CLIENT_ID` und `EBAY_CLIENT_SECRET`.

Beim nächsten Lauf ist eBay automatisch aktiv.

---

## 2. Produkte hinzufügen und verwalten

### Variante A: `products.yaml` im GitHub-Webeditor
1. Öffne [`products.yaml`](products.yaml) auf GitHub und klicke oben rechts auf den **Stift** (Edit).
2. Ganz unten steht ein **Beispiel**. Kopiere es, entferne die `#` am Zeilenanfang und passe es an.
   Wichtig: mit **Leerzeichen** einrücken (keine Tabs), genau wie die anderen Einträge.
3. **Commit changes…** → **Commit changes**. Ab dem nächsten Lauf wird das Produkt beobachtet.
   (Hat die Datei einen Tippfehler, schlagen die Tests im Reiter „Actions“ rot an und der Lauf
   meldet „Konfigurationsfehler“ mit der Zeile, die nicht stimmt.)

### Variante B: Issue-Formular „Neues Produkt“
1. Reiter **Issues** → **New issue** → **Neues Produkt**.
2. Formular ausfüllen → **Submit new issue**.
3. Ein Workflow trägt das Produkt automatisch ein und schließt das Issue mit einer Bestätigung.
   (Aus Sicherheitsgründen nur für dich als Besitzer; Issues von Fremden werden ignoriert.)

### Variante C: Telegram-Befehl
Schreibe deinem Bot:
```
/neu Bosch PSR 18 LI-2; 89; PSR 18 LI-2, PSR18
```
Format: `/neu Name; Zielpreis; Suchbegriff1, Suchbegriff2`. Der Bot antwortet mit der Nummer des
neuen Produkts. Der Befehl wird beim nächsten Lauf
verarbeitet (spätestens nach 2 Stunden), dann kommt eine Bestätigung. Nur Nachrichten aus **deinem**
Chat werden angenommen.

**Tipp zu Suchbegriffen:** Ein Angebot passt, wenn *alle Wörter eines Begriffs* im Titel stehen.
Modellnummern wie `DHP490RFX3` werden auch als `DHP 490 RFX3` erkannt. mydealz-Gruppen findest du in der
Adresszeile: `mydealz.de/gruppe/kaffeevollautomaten` → Gruppe `kaffeevollautomaten`.

### Produkte anzeigen, löschen und pausieren (Telegram)

| Befehl | Was passiert |
|---|---|
| `/liste` | Alle Produkte mit **Nummer**, Zielpreis und aktuell günstigstem Preis (Stand: letzter Lauf). ✅ Ziel erreicht · 🟡 knapp darüber · 🔴 darüber · ⚪ kein Angebot · ⏸ pausiert |
| `/loeschen 3` oder `/loeschen Makita` | Entfernt das Produkt aus `products.yaml` (Commit über die GitHub-API) und bestätigt, **welches** Produkt gelöscht wurde. Es verschwindet beim Seitenbau im selben Lauf von der Startseite. `/löschen` geht auch. |
| `/pause 3` | Produkt vorübergehend **nicht überwachen**, ohne es zu löschen (setzt `aktiv: false`). Auf der Startseite erscheint es ausgegraut am Ende. |
| `/fortsetzen 3` | Wieder überwachen (setzt `aktiv: true`). |
| `/hilfe` | Kurze Übersicht der Befehle. |

- **Nummer oder Name:** Bei einem Namen reicht ein Teil, z. B. `/pause lenovo`. Passt der Name auf
  mehrere Produkte (z. B. zwei Airfryer), fragt der Bot nach und listet die Treffer mit Nummer auf.
  Dann einfach mit der Nummer antworten, z. B. `/loeschen 9`.
- **Nummern:** Sie entsprechen der Reihenfolge in `products.yaml`. Nach einem Löschen rücken die
  Nummern dahinter auf. Schick im Zweifel vorher `/liste`. Mehrere Befehle, die du zwischen zwei Läufen
  schickst, beziehen sich alle auf dieselbe Nummerierung.
- **Preisverlauf:** Beim Löschen bleibt der Verlauf in `data/verlauf.json` und `data/verlauf.csv`
  erhalten (archiviert), wird aber nicht mehr angezeigt. Der gelöschte Eintrag selbst wird in
  `data/geloescht.json` aufgehoben. Zum Wiederherstellen kopierst du ihn von dort zurück in `products.yaml`.
- **Sicherheit:** Befehle werden **nur aus deinem eigenen Chat** (`TELEGRAM_CHAT_ID`) angenommen.
  Nachrichten aus anderen Chats oder Gruppen ignoriert der Bot.
- **Wann?** Der Bot fragt seine Nachrichten bei jedem Lauf ab, also alle 2 Stunden. Sofort geht es mit
  **Actions → Deal-Radar → Run workflow**.
- **Ohne Telegram:** Löschen kannst du auch im Web-Editor (Eintrag entfernen). Zum Pausieren schreibst
  du `aktiv: false` in den Eintrag.

---

## 3. Manuell auslösen

**Actions** → **Deal-Radar** → **Run workflow** → **Run workflow** (ohne Haken).
Oder im Terminal:
```bash
gh workflow run radar.yml --repo mjkschule/deal-radar
```

## 4. Enddatum ändern

In [`config.yaml`](config.yaml) die Zeile `enddatum: "2026-11-27T23:59"` ändern (z. B. auf
`"2026-12-01T23:59"` für Cyber Monday) und committen.

**Nach dem Enddatum:** Der nächste Lauf beendet sich sofort ohne Fehler und **schaltet den Workflow ab**.
Danach gibt es keine Läufe mehr. Zum Reaktivieren: Enddatum in die Zukunft setzen, dann
**Actions** → **Deal-Radar** → **Enable workflow**.

---

## 5. Wann wird gemeldet?

| Regel | Bedeutung |
|---|---|
| ✅ Zielpreis | Preis **inkl. Versand** ≤ Zielpreis (Leasing: Monatsrate ≤ Zielpreis) |
| ✅ Preissturz | Preis mindestens **10 % unter dem bisher niedrigsten** vom Radar gesehenen Preis |
| 🔁 Keine Doppelmeldung | Gleiches Angebot (Shop + Link oder Shop + Preis) nur einmal; erneut nur, wenn es billiger wird |
| 🚫 Ausgeschlossen | Ausschlusswort im Titel oder Mindestwert unterschritten (z. B. nur 60 Hz) |
| ⚠️ Verdächtig | Preis < 40 % des Medians der gesehenen Preise (Bezugswert höchstens der Zielpreis) |
| 🚗 Nicht passend (Leasing) | andere Laufzeit als 36 Monate, < 15.000 km/Jahr, nur Gewerbe, Sonderzahlung > 1.000 € |

Ist der Versand nicht ermittelbar, steht „Versand unbekannt“ in Nachricht und Karte.
Leasing: **Effektive Rate** = (Rate × Monate + Sonderzahlung + Bereitstellung) / Monate.
Die Startseite zeigt pro Produkt das günstigste passende Angebot der letzten 48 Stunden.

## 6. Datenquellen (rechtlich geprüft am 24.11.2026)

| Quelle | Status | Hinweis |
|---|---|---|
| mydealz Gruppen-RSS | ✅ | öffentliche Feeds; die mydealz-*Suche* ist per robots.txt gesperrt und wird nicht genutzt |
| eBay Browse API | ⏳ optional | offizielle API, braucht Schlüssel (Abschnitt 1.5) |
| Shop-Seiten | ✅ | nur maschinenlesbare Preise (schema.org), nur wenn robots.txt es erlaubt |
| LeasingMarkt.de | ✅ | Ergebnisliste + wenige Detailseiten (Zwischenspeicher 24 h) |
| Sparneuwagen.de | ✅ | nur der Haupt-Feed (Kategorie-Feeds sind per robots.txt gesperrt) |
| idealo, notebooksbilliger, cyberport, kaufland, bauhaus, galaxus, null-leasing | ❌ | Bot-Schutz (403/Timeout); wird nicht umgangen |
| Amazon | ❌ | Nutzungsbedingungen verbieten automatisches Auslesen (Amazon-Deals kommen über mydealz) |
| Geizhals, baustoffshop | ❌ | Nutzungsbedingungen unklar bzw. robots.txt verbietet es |

Alle Abrufe: eigener User-Agent (`DealRadar/1.0 …`), robots.txt-Prüfung vor jedem Abruf,
mindestens 3 Sekunden Pause pro Webseite, ein Lauf alle 2 Stunden. Antwortet eine Seite mit
Captcha/403/429, wird das nur als Fehler angezeigt und nicht umgangen. Fällt eine Quelle aus,
laufen die anderen weiter; der Status steht oben auf der Startseite.

---

## 7. Dateien

```
products.yaml            deine Produkte
config.yaml              Enddatum, Quellen an/aus, Regeln
dealradar/               der Python-Code (gut kommentiert)
  sources/               ein Modul je Datenquelle
data/state.json          gemeldete Angebote, Tiefstpreise, gesehene Angebote (vom Workflow gepflegt)
data/verlauf.json        Preisverlauf pro Lauf (für die Sparklines)
data/verlauf.csv         alle gesehenen Angebote (mit ; getrennt, öffnet in Excel)
data/geloescht.json      per /loeschen entfernte Produkte (zum Wiederherstellen)
docs/index.html          die Startseite (wird automatisch erzeugt)
.github/workflows/       radar.yml (alle 2 Std.), add-product.yml (Issue → Produkt), tests.yml
```

## 8. Lokal ausprobieren (für Neugierige)

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```
```bash
.venv/bin/python -m pytest -q
```
```bash
.venv/bin/python -m dealradar.main --dry-run --out /tmp/dealradar-test
```
`--dry-run` schickt nichts an Telegram, sondern gibt die Nachrichten im Terminal aus.

## 9. Probleme?

- **Keine Telegram-Nachricht:** Testnachricht auslösen (1.4) und im Log des Laufs nachsehen.
  Häufigster Fehler: Chat-ID falsch oder dem Bot nie „Start“ geschrieben.
- **Lauf rot:** Reiter **Actions** → Lauf anklicken → roten Schritt aufklappen; meist ist es ein
  Tippfehler in `products.yaml`.
- **Läufe kommen unregelmäßig:** GitHub startet geplante Läufe oft 5–30 Minuten später; das ist normal.
- **Quelle auf „Fehler“:** Die Webseite war nicht erreichbar oder hat ihren Aufbau geändert. Die
  anderen Quellen laufen weiter. Eine Quelle kann in `config.yaml` unter `quellen:` abgeschaltet werden.
