# 📡 Deal-Radar

Sucht bis einschließlich **Black Friday (27.11.2026, 23:59 Uhr)** alle 2 Stunden automatisch nach guten
Angeboten für deine Produkte, schickt dir eine **Telegram-Nachricht**, wenn ein Deal gut ist, und zeigt auf
einer **Startseite** für jedes Produkt den aktuell günstigsten Preis.

- **Startseite:** https://mjkschule.github.io/deal-radar/
- **Läufe ansehen / manuell starten:** Reiter **Actions** im Repo
- **Produkte:** Datei [`products.yaml`](products.yaml) · **Einstellungen:** [`config.yaml`](config.yaml)

---

## 1. Einrichtung (einmalig, ca. 20 Minuten)

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

### 1.6 Sofort-Antworten im Bot (Cloudflare Worker, kostenlos)

Ohne diesen Schritt beantwortet der Bot Befehle erst beim nächsten Suchlauf (bis zu 2 Stunden). Mit dem
**Cloudflare Worker** antwortet er sofort und startet die Suchläufe zuverlässig alle 2 Stunden selbst. Der
Zeitplan von GitHub bleibt als Reserve; doppelte Läufe innerhalb von 60 Minuten werden übersprungen.

**a) GitHub-Token für den Worker** (darf nur `products.yaml` ändern und Läufe starten)
1. GitHub → oben rechts dein Bild → **Settings** → ganz unten **Developer settings** →
   **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
2. Name: `deal-radar-bot`, Expiration: **Custom** → z. B. 31.12.2026.
3. **Repository access:** *Only select repositories* → `deal-radar`.
4. **Permissions → Repository permissions → Contents:** *Read and write* (Metadata wird automatisch gesetzt).
5. **Generate token** → den Token (`github_pat_…`) kopieren. Er wird nur einmal angezeigt.

**b) Worker hochladen** (im Terminal, im Ordner `worker/`)
```bash
cd worker && npm install
```
```bash
npx wrangler login
```
(öffnet den Browser → bei Cloudflare anmelden → **Allow**)
Einmalig einen kleinen Speicher anlegen (Cloudflare KV, kostenlos). Der Bot merkt sich darin
Link-Vorschauen und welche Meldungen schon verschickt sind:
```bash
npx wrangler kv namespace create deal-radar-bot
```
Die ausgegebene `id` in `worker/wrangler.toml` bei `[[kv_namespaces]]` eintragen. Dann hochladen:
```bash
npx wrangler deploy
```
Am Ende steht die Adresse des Workers, z. B. `https://deal-radar-bot.<name>.workers.dev`.

**c) Geheime Werte im Worker speichern**: Jeder Befehl fragt nach dem Wert; die Eingabe ist unsichtbar.
```bash
npx wrangler secret put TELEGRAM_BOT_TOKEN
```
```bash
npx wrangler secret put TELEGRAM_CHAT_ID
```
```bash
npx wrangler secret put GITHUB_TOKEN
```
```bash
openssl rand -hex 32 | npx wrangler secret put WEBHOOK_SECRET
```
(Der letzte erzeugt ein zufälliges Passwort, mit dem Telegram sich beim Worker ausweist. Du musst es dir nicht merken.)

**d) Bot mit dem Worker verbinden:** Rufe im Browser einmal `https://deal-radar-bot.<name>.workers.dev/setup`
auf. Dort sollte `"ok":true` stehen. Damit ist der Webhook gesetzt, und die Befehle sind bei Telegram
registriert (Menü beim Tippen von `/`).

**Worker wieder entfernen:** Rufe `https://api.telegram.org/bot<DEIN-TOKEN>/deleteWebhook` auf. Dann
holt der Suchlauf die Befehle wieder selbst ab (alle 2 Stunden).

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

### Variante C: Shop-Link schicken (am einfachsten)
Schick deinem Bot einfach den **Link zur Produktseite** (z. B. aus der Teilen-Funktion der Shop-App).
Der Bot
1. prüft die **robots.txt** des Shops (verbietet sie das Auslesen, sagt er das und ruft nichts ab),
2. liest **Name, EAN und aktuellen Preis** aus den maschinenlesbaren Angaben der Seite (schema.org),
3. schlägt einen **Zielpreis 10 % unter dem bekannten Tiefstpreis** vor (bei neuen Produkten: dem
   aktuellen Preis) und zeigt die Buttons **Übernehmen**, **Zielpreis ändern** und **Abbrechen**.

Bei „Zielpreis ändern“ schickst du danach einfach die Zahl, z. B. `49,99`. Das neue Produkt bekommt den
Link als `shop_urls` (der Preis dort wird bei jedem Lauf gelesen) und Suchbegriffe aus der Modellnummer.
Getestet: BAUR und Office-Partner klappen (inkl. EAN). Shops mit Bot-Schutz geben die Seite nicht an
Programme heraus – dann sagt der Bot das ehrlich, und du nimmst Variante D.

### Variante D: Telegram-Befehl
Schreibe deinem Bot:
```
/neu Bosch PSR 18 LI-2; 89; PSR 18 LI-2, PSR18
```
Format: `/neu Name; Zielpreis; Suchbegriff1, Suchbegriff2`. Der Bot bestätigt **sofort** mit der Nummer
des neuen Produkts und startet einen Suchlauf. Nur Nachrichten aus **deinem** Chat werden angenommen.

**Tipp zu Suchbegriffen:** Ein Angebot passt, wenn *alle Wörter eines Begriffs* im Titel stehen.
Modellnummern wie `DHP490RFX3` werden auch als `DHP 490 RFX3` erkannt. mydealz-Gruppen findest du in der
Adresszeile: `mydealz.de/gruppe/kaffeevollautomaten` → Gruppe `kaffeevollautomaten`.

### Alle Bot-Befehle

Der Bot antwortet **sofort** (über den Cloudflare Worker, siehe Abschnitt 1.6). In Telegram erscheinen die
Befehle auch im Menü, wenn du `/` tippst.

| Befehl | Beispiel | Was passiert |
|---|---|---|
| `/liste` | `/liste` | Alle Produkte mit **Nummer**, Zielpreis, aktuell günstigstem Effektivpreis (inkl. Versand, bei Leasing die effektive Rate), Shop und **Deal-Score** |
| `/top` | `/top` | Die 5 besten Deals nach Deal-Score, mit Link |
| `/status` | `/status` | Letzter und nächster Suchlauf, Zustand jeder Quelle, Anzahl Produkte |
| *(Link)* | `https://www.baur.de/p/…` | Produkt per Shop-Link anlegen (Variante C) |
| `/neu` | `/neu Philips HD9255; 55; HD9255, Airfryer 5000` | Produkt anlegen (Name; Zielpreis; Suchbegriffe) |
| `/ziel` | `/ziel 3 49,99` oder `/ziel makita 199` | Zielpreis ändern |
| `/pause` | `/pause 3` | Produkt vorübergehend **nicht überwachen** (setzt `aktiv: false`); auf der Startseite ausgegraut am Ende |
| `/fortsetzen` | `/fortsetzen 3` | Wieder überwachen (setzt `aktiv: true`) |
| `/loeschen` | `/loeschen 3` oder `/löschen Makita` | Produkt entfernen; der Bot nennt, **welches** gelöscht wurde |
| `/ruhe` | `/ruhe aus`, `/ruhe an`, `/ruhe` | Ruhezeiten aus-/einschalten bzw. Stand anzeigen (ändert `config.yaml`) |
| `/hilfe` | `/hilfe` | Alle Befehle mit Beispielen |

**Buttons unter jeder Deal-Meldung**

| Button | Was passiert |
|---|---|
| ✅ Gekauft | Produkt wird nicht mehr überwacht und verschwindet von der Startseite. In `data/geloescht.json` steht „gekauft“ mit Preis, Link und Datum; der Preisverlauf bleibt. |
| 🙈 Ignorieren | Genau **dieses** Angebot wird nie wieder gemeldet (gespeichert in `data/ignoriert.json`). Andere Angebote fürs gleiche Produkt kommen weiter. |
| 🎯 Ziel −10 € | Zielpreis um 10 € senken |
| ⏸ Pausieren | wie `/pause` |
| 🔗 Zum Angebot | öffnet das Angebot |

Die Meldung selbst bleibt stehen; der gedrückte Button zeigt danach das Ergebnis (z. B. „✅ Gekauft“).

Legende in `/liste`: ✅ Ziel erreicht · 🟡 bis 10 % darüber · 🔴 darüber · ⚪ kein Angebot · ⏸ pausiert ·
🆕 neu (wird beim nächsten Lauf gesucht).

- **Nummer oder Name:** Bei einem Namen reicht ein Teil, z. B. `/pause lenovo`. Passt er auf mehrere
  Produkte (z. B. zwei Airfryer), fragt der Bot mit **Buttons** nach – einfach antippen.
- **Nummern** entsprechen der Reihenfolge in `products.yaml`. Nach dem Löschen rücken die Nummern dahinter
  auf; im Zweifel vorher `/liste` schicken.
- **Was passiert bei Änderungen?** Der Worker ändert `products.yaml` per Commit über die GitHub-API
  (Kommentare bleiben erhalten), bestätigt sofort und startet einen Suchlauf. Die Startseite ist nach
  ein paar Minuten aktuell.
- **Preise** in `/liste`, `/top` und `/status` stammen aus `docs/bot.json`, die jeder Suchlauf neu schreibt.
- **Deal-Score (vorläufig):** 0–100, berechnet nur aus dem **eigenen** Preisverlauf der letzten 90 Tage,
  nie aus UVP oder Streichpreisen. 50 = üblicher Preis, 75 = 10 % unter dem Median, 100 = 20 % oder mehr
  darunter, +10 auf dem Allzeit-Tiefstpreis. Unter 5 Messpunkten steht „–“.
- **Preisverlauf beim Löschen:** bleibt in `data/verlauf.json` und `data/verlauf.csv` erhalten, wird aber
  nicht mehr angezeigt. Der gelöschte Eintrag wird in `data/geloescht.json` aufgehoben (zum Wiederherstellen
  zurück in `products.yaml` kopieren).
- **Sicherheit:** Der Bot antwortet **nur deinem eigenen Chat** (`TELEGRAM_CHAT_ID`). Den Worker erreicht
  Telegram nur mit dem geheimen `WEBHOOK_SECRET`; alle anderen Anfragen werden abgewiesen.
- **Ohne Telegram:** Löschen geht auch im Web-Editor (Eintrag entfernen); zum Pausieren `aktiv: false`
  in den Eintrag schreiben.

---

## 3. Manuell auslösen

**Actions** → **Deal-Radar** → **Run workflow** → **Run workflow** (ohne Haken).

**Beispiel-Meldung mit Buttons** (zum Ausprobieren): beim **Run workflow** in das Feld
„Nur eine Beispiel-Meldung …“ die **Nummer aus `/liste`** eintragen. Dann kommt eine als 🧪 TESTMELDUNG
gekennzeichnete Nachricht mit allen Buttons. Achtung: Die Buttons wirken auf das **echte** Produkt
(„Gekauft“ entfernt es also) – am besten mit einem Testprodukt ausprobieren.
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

**Welche Angebote kommen überhaupt in Frage?**

| Regel | Bedeutung |
|---|---|
| ✅ Zielpreis | Preis **inkl. Versand** ≤ Zielpreis (Leasing: Monatsrate ≤ Zielpreis) |
| ✅ Preissturz | Preis mindestens **10 % unter dem bisher niedrigsten** vom Radar gesehenen Preis |
| 🔁 Keine Doppelmeldung | Gleiches Angebot (Shop + Link oder Shop + Preis) nur einmal; erneut nur, wenn es billiger wird |
| 🙈 Ignoriert | Angebote, unter denen du „Ignorieren“ gedrückt hast |
| 🚫 Ausgeschlossen | Ausschlusswort im Titel oder Mindestwert unterschritten (z. B. nur 60 Hz) |
| ⚠️ Verdächtig | Preis < 40 % des Medians der gesehenen Preise (Bezugswert höchstens der Zielpreis) |
| 🚗 Nicht passend (Leasing) | andere Laufzeit als 36 Monate, < 15.000 km/Jahr, nur Gewerbe, Sonderzahlung > 1.000 € |

**Wann und wie kommt die Nachricht?** (Einstellungen in `config.yaml` unter `meldungen` und `ruhezeiten`)

| Fall | Nachricht |
|---|---|
| Zielpreis erreicht **oder** Deal-Score ≥ 85 | **sofort** (mit Buttons) |
| alle anderen guten Deals (z. B. Preissturz mit Score 70) | in der **Tagesübersicht um 19:00** |
| Sofort-Meldung in einer **Ruhezeit** (Mo–Fr 7:30–14:00, täglich 22:00–7:00) | wird zurückgehalten und **direkt nach der Ruhezeit** nachgeliefert (um 7:00 bzw. 14:00) |
| … außer Score ≥ 90 oder Zielpreis um **mehr als 15 %** unterboten | kommt **trotz Ruhezeit sofort** |

Die **Tagesübersicht** zeigt: alle Produkte mit erreichtem Zielpreis, die weiteren guten Deals seit der
letzten Übersicht und eine Kurzliste aller Produkte. Übersicht und Nachlieferung verschickt der
Cloudflare Worker (stündlicher Zeitplan); die Meldungen dafür stehen in `docs/bot.json`.
Ruhezeiten ausschalten: `/ruhe aus` (oder `aktiv: false` in `config.yaml`).

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
data/geloescht.json      per /loeschen oder „Gekauft“ entfernte Produkte (zum Wiederherstellen)
data/ignoriert.json      per Button „Ignorieren“ ausgeblendete Angebote
docs/index.html          die Startseite (wird automatisch erzeugt)
docs/bot.json            aktuelle Preise für den Telegram-Bot (wird automatisch erzeugt)
worker/                  der Telegram-Bot als Cloudflare Worker (JavaScript)
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
- **Bot antwortet nicht:** Rufe `https://deal-radar-bot.<name>.workers.dev/setup` auf. Steht dort
  `"ok":true` und bei `letzter_fehler` nichts, ist alles verbunden. Sonst fehlt meist ein Secret
  (Abschnitt 1.6 c). Live-Log des Workers: `cd worker && npx wrangler tail`.
- **Bot meldet „Hat nicht geklappt: GitHub … 401/403“:** Der GitHub-Token ist abgelaufen oder hat nicht
  die Berechtigung *Contents: Read and write*. Neuen Token anlegen (1.6 a) und mit
  `npx wrangler secret put GITHUB_TOKEN` ersetzen.
- **Keine Läufe alle 2 Stunden:** Im Cloudflare-Dashboard → Workers → `deal-radar-bot` → **Settings →
  Triggers** prüfen, ob der Cron `17 */2 * * *` eingetragen ist. Übersprungene Läufe (weniger als
  60 Minuten nach dem letzten) sind normal und stehen im Log als „Zeitplan-Lauf übersprungen“.
