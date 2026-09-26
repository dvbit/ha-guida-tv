# Guida TV — specifica consolidata v1.0.0

Integrazione custom Home Assistant che porta in HA la lista canali (nome +
numerazione, DTT e Sky) e la programmazione TV, facendo scrape di
[guidatv.org](https://guidatv.org). Pensata per alimentare dashboard esterne,
in particolare **Astrion**. Istanza di destinazione: **Bracciano**.
Repository: `dvbit/ha-guida-tv`.

## 1. Fonte dati

- Fonte **unica**: guidatv.org, tramite scraping (nessun XMLTV esterno).
- Motivo: le fonti XMLTV valutate (epgshare01, iptv-org) o non sono ufficiali o
  richiedono un tool Node esterno non eseguibile dentro HA. guidatv.org fornisce
  in un colpo solo numerazione, nome, logo, categoria e artwork per programma.

## 2. Copertura temporale

- Il sito espone solo **ieri, oggi, domani, dopodomani**. La guida a 7 giorni
  **non è ottenibile** dal sito (i giorni successivi rimandano all'app).
- L'inclusione di "ieri" è configurabile (default: incluso).

## 3. Struttura del parsing

- **Canali** (`/canali`): HTML renderizzato server-side. Ogni canale è un
  elemento `data-testid="channel-card"` con slug (href), logo (alt/src), numero
  e categoria (`h5.channel-name`). Il numero può essere numerico (1–738) o
  alfanumerico (`CH1`/`CH2` per RSI).
- **Programmi** (`/canali/<slug>[/<giorno>]`): oggetti JSON incorporati nello
  stream React Server Components (`self.__next_f`). Ogni programma ha
  `title, description, durata, genre, category, image, director, inizio, fine,
  year`, con `inizio`/`fine` in ISO 8601 UTC. L'unescape dello stream è mirato
  (solo `\"` e `\\`) per non corrompere i caratteri UTF-8 accentati.

## 4. Aggiornamento

- Refresh **una volta al giorno** a orario configurabile da UI (default 05:00).
- Servizio `guida_tv.refresh` per aggiornamento **su richiesta**.
- Richieste HTTP distanziate da una pausa configurabile (default 1 s) per non
  sovraccaricare il sito.
- User-Agent da browser (il sito Next.js rifiuta client anonimi).

## 5. Configurazione (interamente da UI)

- Una sola config entry (`single_config_entry`).
- Opzioni: ora e minuto del refresh, pausa tra richieste, includere "ieri".
- Il cambio opzioni ricarica l'integrazione.

## 6. Entità

- `sensor.guida_tv_channels`: stato = numero canali; attributo `channels` =
  lista `{number, name, slug, logo, category}` ordinata per numero (numerici
  prima, alfanumerici in coda).
- Un sensore **per canale** `sensor.guida_tv_<slug>`: stato = titolo in onda ora;
  attributi = numero, logo, categoria, inizio, fine, avanzamento %, immagine,
  genere, descrizione, titolo e inizio del programma successivo. Si aggiorna al
  cambio programma tramite timer puntuale, senza polling.
- Sensore diagnostico `sensor.guida_tv_last_update`: stato `ok`/`errori`;
  attributi = ultimo aggiornamento, conteggio canali, conteggio programmi,
  elenco errori.
- Tutti i valori sopravvivono al riavvio (cache su disco via Store).

## 7. Servizi

- `guida_tv.refresh`: forza un aggiornamento immediato.
- `guida_tv.get_schedule` (con risposta): filtri opzionali `channel` (slug o
  lista), `date` (`YYYY-MM-DD` o `ieri/oggi/domani/dopodomani`), `time_from`,
  `time_to` (ora locale `HH:MM`). Restituisce la programmazione filtrata in
  formato JSON riusabile da Astrion.

## 8. Logging

- DEBUG: ogni pagina scaricata, parsing canali/programmi, timer cambio programma.
- INFO: caricamento cache, programmazione refresh, riepilogo aggiornamento.
- WARNING: pagine o canali falliti, oggetti stream troncati, slug vuoti.
- ERROR: fallimento totale (lista canali non disponibile e nessuna cache).

## 9. Packaging

- Repository HACS, `custom_components/guida_tv/`.
- Localizzazione en/it/fr/es/de.
- README EN e IT con esempi d'uso, questa specifica inclusa, icona,
  `hacs.json`, `manifest.json` versionato (1.0.0), workflow hassfest + HACS.

## Verifiche eseguite (v1.0.0)

- 7 test logici su scraper (canali DTT/CH/Sky, programmi RSC bilanciati,
  accenti UTF-8, card malformate, stream vuoto, logica in-onda + progress,
  dedup + ordinamento): passati.
- ruff (E,F,W,I,UP,B,SIM,D) su codice e test: pulito.
- 19 simboli importati da `homeassistant.*` verificati contro il sorgente
  ufficiale HA 2025.6.0 (minimo dichiarato) e 2026.2.3: tutti risolti
  (`EntityCategory` corretto su `homeassistant.const`).
- Coerenza incrociata manifest / services.yaml / strings.json / icons.json /
  5 file di traduzione: nessuna divergenza.
- Parser validato sui campioni HTML/RSC reali forniti da guidatv.org.
