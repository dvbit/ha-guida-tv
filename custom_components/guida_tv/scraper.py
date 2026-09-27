r"""Scraper di guidatv.org.

Riferimenti alla specifica (SPEC.md §2 "Rilevamento" — qui inteso come parsing):
- Canali: la pagina /canali serve HTML renderizzato lato server; ogni canale è
  un elemento con `data-testid="channel-card"` contenente slug, logo, numero e
  categoria. Parsing con BeautifulSoup su selettori semantici stabili.
- Programmi: le pagine /canali/<slug>[/giorno] incorporano gli oggetti programma
  come JSON nello stream React Server Components (self.__next_f), con gli apici
  JSON scritti come `\\"`. Gli oggetti hanno inizio/fine ISO 8601 espliciti, quindi
  non serve inferire gli orari dall'HTML. L'unescape è mirato (solo `\\"` e `\\\\`)
  per NON corrompere i caratteri UTF-8 accentati (bug noto di unicode_escape).

Questo modulo è puro (nessuna dipendenza da Home Assistant) così da essere
testabile in isolamento; l'I/O di rete è iniettato dal chiamante.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

_LOGGER = logging.getLogger(__name__)

# Prefisso dell'attributo alt dei loghi canale: "Logo canale <Nome>"
_ALT_PREFIX = "Logo canale "


def sanitize_slug(slug: str) -> str:
    """Rende uno slug sicuro per unique_id ed entity_id di Home Assistant.

    Alcuni slug di guidatv.org contengono caratteri non ammessi in un entity_id
    (es. "super!", "sky-cinema-uno-+24-hd", "rtl-102.5-tv"). Se anche un solo
    sensore genera un id non valido, l'intero lotto di async_add_entities viene
    annullato e nessun sensore per-canale viene creato. Qui riduciamo a
    [a-z0-9_], collassando le sequenze e togliendo gli underscore ai bordi; lo
    slug originale resta invariato per lo scraping e negli attributi.
    """
    safe = re.sub(r"[^a-z0-9]+", "_", slug.lower()).strip("_")
    return safe or "channel"


def parse_detail_category(html: str) -> str | None:
    """Estrae la categoria del canale dalla pagina dettaglio /canali/<slug>.

    La categoria è nello <span> dell'h5.channel-name: "#<numero> <span>Categoria</span>"
    (es. "Digitale Terrestre", "Sky Cinema"). È la categoria reale del canale, più
    precisa dei macro-tab della pagina /canali. Questa pagina è già scaricata per la
    guida di "oggi", quindi non comporta richieste aggiuntive (SPEC §3).
    """
    soup = BeautifulSoup(html, "html.parser")
    h5 = soup.find("h5", class_="channel-name")
    if h5:
        span = h5.find("span")
        if span:
            return span.get_text(strip=True) or None
    return None


def logo_source_url(logo: str | None) -> str | None:
    """Ricava l'URL del PNG sorgente dal valore del logo.

    Sul sito il logo è un proxy di Next.js: "/_next/image?url=<encoded>&w=..&q=..".
    Il file reale è nel parametro `url` (es. https://img-guidatv.org/loghi/b//rai1.png).
    Se il valore è già un URL assoluto, viene restituito invariato.
    """
    if not logo:
        return None
    if logo.startswith("http"):
        return logo
    query = parse_qs(urlparse(logo).query)
    if "url" in query and query["url"]:
        return unquote(query["url"][0])
    return None


def logo_filename(source_url: str | None, safe_slug: str) -> str:
    """Nome file locale del logo: <safe_slug>.<ext>, estensione dedotta dall'URL."""
    ext = ".png"
    match = re.search(r"\.(png|jpe?g|webp|gif)(?:$|\?)", source_url or "", re.IGNORECASE)
    if match:
        ext = "." + match.group(1).lower().replace("jpeg", "jpg")
    return f"{safe_slug}{ext}"


def parse_channels(html: str) -> list[dict[str, Any]]:
    """Estrae la lista canali dall'HTML della pagina /canali.

    Ritorna una lista di dict: {slug, name, number, logo, category}.
    Robusto ai canali malformati: quelli senza slug vengono saltati con WARNING.
    """
    soup = BeautifulSoup(html, "html.parser")
    channels: list[dict[str, Any]] = []

    for card in soup.select('[data-testid="channel-card"]'):
        anchor = card.find("a", href=True)
        if not anchor or "/canali/" not in anchor["href"]:
            # Card senza link canale valido: ignora (SPEC §7 WARNING)
            _LOGGER.debug("Card canale senza href valido, saltata")
            continue

        slug = anchor["href"].rsplit("/canali/", 1)[1].strip("/")
        if not slug:
            _LOGGER.warning("Slug canale vuoto in href '%s', saltato", anchor["href"])
            continue

        # Nome: dall'attributo alt del logo ("Logo canale Rai 1")
        name: str | None = None
        logo: str | None = None
        img = card.find("img", alt=True)
        if img:
            if img.get("alt", "").startswith(_ALT_PREFIX):
                name = img["alt"][len(_ALT_PREFIX):].strip()
            logo = img.get("src")

        # Numero e categoria.
        # Nella pagina /canali il numero è in un <p> che inizia con "#":
        #   <p ...>#<!-- -->1</p>  ->  "1"  (o "CH1" per RSI).
        # La categoria NON è nella card in /canali (viene dai tab), quindi resta
        # None qui; è invece presente nell'h5.channel-name della pagina dettaglio,
        # usato come fallback per robustezza se il markup cambia.
        # Il numero può essere numerico (1-738) o alfanumerico (CH1/CH2).
        number: str | None = None
        category: str | None = None

        # 1) Sorgente primaria: <p> con "#" (pagina /canali)
        for para in card.find_all("p"):
            text = para.get_text().strip()
            if text.startswith("#"):
                number = text.lstrip("#").strip() or None
                break

        # 2) Fallback: h5.channel-name "#<numero> <span>categoria</span>"
        if number is None:
            h5 = card.find("h5", class_="channel-name")
            if h5:
                span = h5.find("span")
                if span:
                    category = span.get_text(strip=True)
                    span.extract()  # isola il numero rimuovendo la categoria
                number = h5.get_text().replace("#", "").strip() or None

        if not name:
            # Fallback nome: usa lo slug leggibile
            name = slug.replace("-", " ").title()
            _LOGGER.debug("Nome canale assente per slug '%s', uso fallback", slug)

        channels.append(
            {
                "slug": slug,
                "name": name,
                "number": number,
                "logo": logo,
                "category": category,
            }
        )

    _LOGGER.debug("Parsing canali: %d trovati", len(channels))
    return channels


def _unescape_rsc(text: str) -> str:
    r"""Decodifica gli escape dello stream RSC senza toccare i byte UTF-8.

    Lo stream contiene `\\"` per gli apici JSON e `\\\\` per i backslash letterali.
    NON si usa `bytes.decode('unicode_escape')` perché interpreterebbe i byte UTF-8
    degli accenti come Latin-1, corrompendo "solidarietà" → "solidarietÃ ".
    L'ordine conta: prima i backslash doppi, poi gli apici escaped.
    """
    return text.replace('\\\\', '\\').replace('\\"', '"')


def parse_programs(page_html: str) -> list[dict[str, Any]]:
    """Estrae i programmi dagli oggetti JSON nello stream RSC di una pagina canale.

    Ritorna una lista di dict programma con orari ISO 8601 (UTC) espliciti:
    {title, start, stop, genre, category, description, image, year, director}.
    Scandisce gli oggetti bilanciando le graffe e rispettando le stringhe, così
    da isolare ogni oggetto programma anche senza un array JSON ben formato.
    """
    text = _unescape_rsc(page_html)
    programs: list[dict[str, Any]] = []
    length = len(text)
    cursor = 0

    while True:
        # Ogni programma ha un campo "title": lo usiamo come ancora.
        title_pos = text.find('"title"', cursor)
        if title_pos == -1:
            break

        # Risali alla graffa di apertura dell'oggetto che contiene il title.
        start = text.rfind("{", 0, title_pos)
        if start == -1:
            cursor = title_pos + len('"title"')
            continue

        # Scansione in avanti bilanciando le graffe (ignorando quelle in stringa).
        depth = 0
        in_str = False
        escaped = False
        end = -1
        idx = start
        while idx < length:
            char = text[idx]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_str = not in_str
            elif not in_str:
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        end = idx
                        break
            idx += 1

        if end == -1:
            # Oggetto non chiuso: stream troncato, interrompi (SPEC §7 WARNING).
            _LOGGER.warning("Oggetto programma non terminato nello stream, stop")
            break

        blob = text[start : end + 1]
        cursor = end + 1

        try:
            obj = json.loads(blob)
        except json.JSONDecodeError:
            # Non era un oggetto programma valido: prosegui oltre.
            continue

        # Filtra: un programma valido ha almeno title e inizio (SPEC §3).
        if not isinstance(obj, dict) or "title" not in obj or "inizio" not in obj:
            continue

        programs.append(
            {
                "title": obj.get("title"),
                "start": obj.get("inizio"),
                "stop": obj.get("fine"),
                "genre": obj.get("genre"),
                "category": obj.get("category"),
                "description": obj.get("description"),
                "image": obj.get("image"),
                "year": obj.get("year"),
                "director": obj.get("director"),
            }
        )

    _LOGGER.debug("Parsing programmi: %d estratti", len(programs))
    return programs
