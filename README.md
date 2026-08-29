# findmy-map

Zeigt die Standorte deiner bei Google „Mein Gerät finden" registrierten Geräte
(Smartphone, ESP32-Tracker, …) auf einer echten Karte (Leaflet + OpenStreetMap)
statt nur als Google-Maps-Link im Terminal. Zusätzlich: Verlaufs-Track pro
Zeitraum und eine textorientierte Historie der besuchten Orte (ähnlich der
Google-Zeitachse).

Der Dienst baut auf der Bibliothek
[`leonboe1/GoogleFindMyTools`](https://github.com/leonboe1/GoogleFindMyTools)
auf und ist als **Zusatz-Container neben einem bereits eingerichteten
GoogleFindMyTools-Container** gedacht: Er teilt sich dessen `Auth/secrets.json`,
sodass **keine erneute Anmeldung** nötig ist.

> Dieses Projekt steht in keiner Verbindung zu Google oder Apple. Nutzung auf
> eigene Verantwortung und nur für Geräte/Konten, für die du berechtigt bist.

## Voraussetzungen

- Ein bereits **angemeldeter** GoogleFindMyTools-Container; seine
  `Auth/secrets.json` existiert und enthält gültige Tokens.

## Setup

```bash
git clone https://github.com/EXxT4ZzY/google-findmy-map.git && cd google-findmy-map
cp .env.example .env
# .env editieren: GFM_SECRETS_FILE, GFM_DATA_DIR, PUID/PGID, PROXY_NETWORK
docker compose up -d --build
```

Wichtige `.env`-Werte:

| Variable | Bedeutung |
|---|---|
| `GFM_SECRETS_FILE` | Host-Pfad zur **einen** `secrets.json` des bestehenden GoogleFindMyTools-Containers. Wird read-write eingebunden, damit Token-Refreshes zwischen beiden Containern synchron bleiben. **Nicht** den ganzen `Auth/`-Ordner mounten – nur diese Datei. |
| `GFM_DATA_DIR` | Host-Verzeichnis für die SQLite-DB dieses Dienstes (`history.db`). Enthält Standort-Rohdaten – wie personenbezogene Daten behandeln. |
| `PUID` / `PGID` | Besitzer der beiden Pfade oben (und UID, unter der der Container läuft). Prüfen: `stat -c '%u:%g' "$GFM_SECRETS_FILE"`. Ein Init-Schritt chownt `GFM_DATA_DIR` passend. |
| `PROXY_NETWORK` | Name des externen Docker-Netzes deines Reverse Proxy. |

Alle weiteren (optionalen) Variablen sind in `.env.example` dokumentiert.

## Web-UI

- **Hell/Dunkel-Umschalter** (☀/☾ im Kopf beider Seiten), Wahl im Browser
  gemerkt. Im Dark Mode werden die OSM-Kacheln per CSS-Filter abgedunkelt
  (Gebäudeumrisse/Wege/Beschriftungen bleiben erhalten); kein API-Key.
- Die Karte füllt den Bildschirm; die Geräteliste liegt als **schwebendes
  Panel** darüber (Desktop oben rechts, an den Inhalt angepasst; auf schmalen
  Screens als ein-/ausklappbares Bottom-Sheet). Sortiert nach zuletzt
  gesendetem Standort; Klick zentriert die Karte.
- Jedes Gerät hat eine eigene Pin-Farbe; die letzten 5 Positionen sind als
  Linie verbunden.
- **Geräte bearbeiten:** ✎-Button je Zeile → Anzeigename ändern, Pin-Farbe
  aus einer Palette wählen. **Standard** setzt beide Overrides zurück.
- **Zeitachse** (`timeline.html`): Gerät + Von/Bis-Datum wählen → kompletter
  Track als Linie, plus eine **Liste der besuchten Orte** (Adresse,
  Ankunft–Abfahrt, Dauer) mit nummerierten Markern. Ein Aufenthalt entsteht
  nur, wenn im gespeicherten Verlauf mehrere Reports von *einem* Ort (Radius
  `GFM_VISIT_RADIUS_M`) über mind. `GFM_VISIT_MIN_MINUTES` liegen – bei noch
  dünnem Verlauf steht ein Hinweis, es füllt sich mit der Zeit.

## Wie es funktioniert

- `Dockerfile` klont `GoogleFindMyTools` (per `ARG GFM_UPSTREAM_REF` gepinnter
  Commit) nach `/app/vendor`.
- `docker-compose.yml` mountet nur die eine `secrets.json` in den vendorten
  `Auth`-Ordner – Login-Daten/Token-Refresh geteilt statt dupliziert, ohne
  den restlichen vendorten Auth-Code zu überschreiben. Ein `findmy-map-init`
  (Alpine, root) chownt das Daten-Volume auf `PUID:PGID` und beendet sich.
- `service/locations.py` nutzt die Bibliotheksfunktionen, gibt aber
  strukturierte Daten zurück statt sie nur auszudrucken.
- `service/main.py` – FastAPI + Hintergrund-Poll-Thread. Endpunkte:
  `GET /api/locations` (inkl. `palette`), `GET /api/history`,
  `GET /api/visits`, `POST /api/refresh`, `PUT /api/devices/{id}`. Die
  mutierenden Endpunkte weisen Cross-Site-Requests ab (Fetch-Metadata).
- `service/store.py` – SQLite: voller Verlauf (`add`/`recent`/`range` +
  einmalige `history.json`-Migration), Geräte-Overrides, Geocode-Cache.
- `service/colors.py` (Pin-Farbe, mit Validierung), `service/augment.py`
  (Track/Name/Farbe je Gerät), `service/visits.py` (Cluster zu Aufenthalten),
  `service/geocode.py` (Reverse-Geocoding via Nominatim, ≤ 1 Anfrage/1,1 s,
  Negativ-Cache + Backoff).
- `web/index.html`, `web/timeline.html`, `web/app.css`, `web/app.js`.

## Environment-Variablen

Siehe `.env.example`. Kurzfassung:

| Variable | Default | Zweck |
|---|---|---|
| `GFM_POLL_INTERVAL_SECONDS` | `120` | Abfrageintervall |
| `GFM_HISTORY_DB` | `/data/history.db` | SQLite-DB (voller Verlauf + Settings + Geocode-Cache) |
| `GFM_HISTORY_FILE` | `/data/history.json` | nur für einmalige Migration aus einer Vorversion |
| `GFM_DEVICE_COLORS` | – | JSON `{id-oder-name: hex/keyword}`. Priorität: UI-Farbe → env → Palette |
| `GFM_NOMINATIM_URL` | öffentliches OSM-Nominatim | Reverse-Geocoding; **leer = aus** |
| `GFM_GEOCODE_EMAIL` | – | Kontakt-E-Mail als `email=`-Parameter (OSM-Richtlinie) |
| `GFM_VISIT_RADIUS_M` / `GFM_VISIT_MIN_MINUTES` | `100` / `15` | Definition „besuchter Ort" |

## Bekannte Einschränkungen

- Der Standortverlauf wächst unbegrenzt (keine Aufräum-Logik). Für SQLite
  unkritisch, aber `history.db` wächst mit der Zeit.
- Die Geräte-Auswahl der Zeitachse listet nur Geräte, die die aktuelle
  Abfrage zurückgibt (entfernte Geräte verschwinden trotz Verlaufsdaten).
- „Semantic Locations" (benannte Orte ohne Koordinaten) bekommen keinen
  Marker.
- Bei einem Owner-Key-Versionswechsel muss `secrets.json` im bestehenden
  Container neu erzeugt werden.
- `secrets.json` wird von beiden Containern nicht-atomar geschrieben; ein
  Konflikt bei exakt gleichzeitigem Token-Refresh ist theoretisch möglich,
  praktisch unwahrscheinlich.

## Lizenz

[MIT](LICENSE)
