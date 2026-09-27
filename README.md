# Guida TV for Home Assistant

[![hassfest](https://github.com/dvbit/ha-guida-tv/actions/workflows/hassfest.yml/badge.svg)](https://github.com/dvbit/ha-guida-tv/actions/workflows/hassfest.yml)
[![HACS](https://github.com/dvbit/ha-guida-tv/actions/workflows/hacs.yml/badge.svg)](https://github.com/dvbit/ha-guida-tv/actions/workflows/hacs.yml)

Brings the Italian TV channel list (name + number, DTT and Sky) and the
programme guide into Home Assistant by scraping
[guidatv.org](https://guidatv.org). Designed to feed external dashboards such as
**Astrion**.

🇮🇹 [Leggi in italiano](README.it.md)

## Features

- **Channel list** with number (1–738 and RSI `CH1`/`CH2`), name, logo and
  category (DTT, Sky Cinema, Sky Sport, …).
- **Now / next** sensor per channel, updated at programme change with no polling.
- **Programme guide** from yesterday to the day after tomorrow (the site does
  not expose 7 days).
- **`get_schedule` service** returning a filtered, reusable JSON payload.
- Daily refresh at a configurable time, plus on-demand refresh.
- Guide **survives restarts** (on-disk cache).
- UI configuration, localised in EN/IT/FR/ES/DE.

> **Note on coverage.** guidatv.org only publishes yesterday → day-after-tomorrow
> on the web; further days redirect to its app. A full 7-day guide is therefore
> not available from this source.

## Installation (HACS)

1. HACS → ⋮ → *Custom repositories* → add `dvbit/ha-guida-tv`, category
   *Integration*.
2. Install **Guida TV**, then restart Home Assistant.
3. *Settings → Devices & Services → Add Integration → Guida TV*.

## Entities

| Entity | State | Key attributes |
|---|---|---|
| `sensor.guida_tv_channels` | number of channels | `channels`: list of `{number, name, slug, logo, category}` |
| `sensor.guida_tv_<slug>` | title on air now | `number, logo, logo_local, category, start, stop, progress, image, genre, description, next_title, next_start` |
| `sensor.guida_tv_last_update` | `ok` / `errori` | `last_update, channel_count, program_count, errors` |

## Options

| Option | Default | Meaning |
|---|---|---|
| Daily refresh hour | `5` | Hour (0–23) of the daily scrape |
| Daily refresh minute | `0` | Minute (0–59) |
| Delay between requests | `1.0` s | Pause between HTTP requests |
| Include yesterday | on | Add yesterday to the guide |

## Services

### `guida_tv.refresh`
Forces an immediate update of channels and guide.

```yaml
action: guida_tv.refresh
```

### `guida_tv.get_schedule`
Returns the filtered guide (service with response).

```yaml
action: guida_tv.get_schedule
data:
  channel: ["rai-1", "rai-2"]
  date: "oggi"          # or YYYY-MM-DD / ieri / domani / dopodomani
  time_from: "20:00"
  time_to: "23:30"
response_variable: schedule
```

Example response shape:

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

## Dashboard example (now on air)

```yaml
type: markdown
content: >
  ## {{ state_attr('sensor.guida_tv_rai_1','number') }} — Rai 1
  **{{ states('sensor.guida_tv_rai_1') }}**
  ({{ state_attr('sensor.guida_tv_rai_1','progress') }}%)
  → next: {{ state_attr('sensor.guida_tv_rai_1','next_title') }}
```

## Using it from Astrion

The `sensor.guida_tv_channels` attribute `channels` is an ordered list ready to
render a channel grid; each per-channel sensor exposes the current programme and
artwork. For a full listing, call `guida_tv.get_schedule` and consume the JSON.

## Disclaimer

Unofficial integration. Data belongs to guidatv.org and its providers; use it in
accordance with the site's terms. Keep the request delay reasonable.

## License

MIT
