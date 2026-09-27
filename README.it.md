# Guida TV per Home Assistant

[![hassfest](https://github.com/dvbit/ha-guida-tv/actions/workflows/hassfest.yml/badge.svg)](https://github.com/dvbit/ha-guida-tv/actions/workflows/hassfest.yml)
[![HACS](https://github.com/dvbit/ha-guida-tv/actions/workflows/hacs.yml/badge.svg)](https://github.com/dvbit/ha-guida-tv/actions/workflows/hacs.yml)

Porta in Home Assistant la lista canali italiani (nome + numero, DTT e Sky) e la
programmazione TV, facendo scrape di [guidatv.org](https://guidatv.org). Pensata
per alimentare dashboard esterne come **Astrion**.

🇬🇧 [Read in English](README.md)

## Caratteristiche

- **Lista canali** con numero (1–738 e RSI `CH1`/`CH2`), nome, logo e categoria
  (DTT, Sky Cinema, Sky Sport, …).
- Sensore **in onda ora / successivo** per canale, aggiornato al cambio
  programma senza polling.
- **Programmazione** da ieri a dopodomani (il sito non espone 7 giorni).
- **Servizio `get_schedule`** che restituisce un JSON filtrato e riusabile.
- Refresh giornaliero a orario configurabile, più aggiornamento su richiesta.
- La guida **sopravvive ai riavvii** (cache su disco).
- Configurazione da UI, localizzata in EN/IT/FR/ES/DE.

> **Nota sulla copertura.** guidatv.org pubblica sul web solo da ieri a
> dopodomani; i giorni successivi rimandano alla sua app. Una guida completa a 7
> giorni non è quindi ottenibile da questa fonte.

## Installazione (HACS)

1. HACS → ⋮ → *Repository personalizzati* → aggiungi `dvbit/ha-guida-tv`,
   categoria *Integration*.
2. Installa **Guida TV**, poi riavvia Home Assistant.
3. *Impostazioni → Dispositivi e servizi → Aggiungi integrazione → Guida TV*.

## Entità

| Entità | Stato | Attributi principali |
|---|---|---|
| `sensor.guida_tv_channels` | numero canali | `channels`: lista di `{number, name, slug, logo, category}` |
| `sensor.guida_tv_<slug>` | titolo in onda ora | `number, logo, logo_local, category, start, stop, progress, image, genre, description, next_title, next_start` |
| `sensor.guida_tv_last_update` | `ok` / `errori` | `last_update, channel_count, program_count, errors` |

## Opzioni

| Opzione | Default | Significato |
|---|---|---|
| Ora refresh giornaliero | `5` | Ora (0–23) dello scrape quotidiano |
| Minuto refresh giornaliero | `0` | Minuto (0–59) |
| Pausa tra le richieste | `1.0` s | Attesa tra le richieste HTTP |
| Includi ieri | attivo | Aggiunge ieri alla guida |

## Servizi

### `guida_tv.refresh`
Forza un aggiornamento immediato di canali e guida.

```yaml
action: guida_tv.refresh
```

### `guida_tv.get_schedule`
Restituisce la guida filtrata (servizio con risposta).

```yaml
action: guida_tv.get_schedule
data:
  channel: ["rai-1", "rai-2"]
  date: "oggi"          # oppure YYYY-MM-DD / ieri / domani / dopodomani
  time_from: "20:00"
  time_to: "23:30"
response_variable: schedule
```

Forma della risposta:

```yaml
schedule:
  rai-1:
    channel: { slug: rai-1, name: "Rai 1", number: "1", logo: "…", category: "Digitale Terrestre" }
    programs:
      - title: "Affari Tuoi"
        start: "2026-09-26T18:30:00.000Z"
        stop:  "2026-09-26T19:30:00.000Z"
        genre: "Intrattenimento"
        image: "https://img-guidatv.org/1/affari-tuoi/6.jpg"
```

## Esempio dashboard (in onda ora)

```yaml
type: markdown
content: >
  ## {{ state_attr('sensor.guida_tv_rai_1','number') }} — Rai 1
  **{{ states('sensor.guida_tv_rai_1') }}**
  ({{ state_attr('sensor.guida_tv_rai_1','progress') }}%)
  → poi: {{ state_attr('sensor.guida_tv_rai_1','next_title') }}
```

## Uso da Astrion

L'attributo `channels` di `sensor.guida_tv_channels` è una lista ordinata pronta
per costruire una griglia canali; ogni sensore per-canale espone il programma
corrente e l'artwork. Per l'elenco completo, chiama `guida_tv.get_schedule` e
consuma il JSON.

## Avvertenza

Integrazione non ufficiale. I dati appartengono a guidatv.org e ai suoi
fornitori; usali nel rispetto dei termini del sito. Mantieni una pausa tra le
richieste ragionevole.

## Licenza

MIT
