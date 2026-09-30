"""Test logici su scraper e logica in-onda (SPEC Verifiche)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "guida_tv"))
from datetime import datetime, timezone
import scraper

CH_HTML = '''
<div data-testid="channel-card"><a href="/canali/rai-1"><div class="channel_card"><div class="image"><img alt="Logo canale Rai 1" src="http://logo/rai1.png"/></div><p class="text-light fs-5 fw-light mt-3">#<!-- -->1</p></div></a></div>
<div data-testid="channel-card"><a href="/canali/rsi-la1"><div class="channel_card"><div class="image"><img alt="Logo canale RSI LA1" src="http://logo/rsi.png"/></div><p class="text-light fs-5 fw-light mt-3">#<!-- -->CH1</p></div></a></div>
<div data-testid="channel-card"><a href="/canali/sky-uno-hd"><div class="channel_card"><div class="image"><img alt="Logo canale Sky Uno HD" src="http://logo/sky.png"/></div><p class="text-light fs-5 fw-light mt-3">#<!-- -->108</p></div></a></div>
'''

RSC = r'''x\"other\":1},{\"id\":\"a1\",\"title\":\"Programma Uno\",\"description\":\"Città e società, perché sì.\",\"durata\":\"60\",\"genre\":\"Film\",\"category\":\"Film\",\"image\":\"http://img/1.jpg\",\"director\":null,\"inizio\":\"2026-09-26T19:00:00.000Z\",\"fine\":\"2026-09-26T20:00:00.000Z\",\"year\":\"2020\"},{\"id\":\"a2\",\"title\":\"Programma Due\",\"description\":\"Segue.\",\"durata\":\"30\",\"genre\":\"News\",\"category\":\"News\",\"image\":\"http://img/2.jpg\",\"director\":null,\"inizio\":\"2026-09-26T20:00:00.000Z\",\"fine\":\"2026-09-26T20:30:00.000Z\",\"year\":null}'''

def test_channels():
    ch = scraper.parse_channels(CH_HTML)
    assert len(ch) == 3
    assert ch[0] == {"slug":"rai-1","name":"Rai 1","number":"1","logo":"http://logo/rai1.png","category":None}
    assert ch[1]["number"] == "CH1"
    assert ch[2]["number"] == "108"
    print("1. parse_channels (numero da <p>, DTT + CH + Sky): OK")

def test_programs():
    pr = scraper.parse_programs(RSC)
    assert len(pr) == 2, f"attesi 2, trovati {len(pr)}"
    assert pr[0]["title"] == "Programma Uno"
    assert pr[0]["start"] == "2026-09-26T19:00:00.000Z"
    assert pr[1]["year"] is None
    print("2. parse_programs (oggetti RSC bilanciati): OK")

def test_accents():
    pr = scraper.parse_programs(RSC)
    assert "à" in pr[0]["description"] and "perché" in pr[0]["description"], pr[0]["description"]
    print("3. accenti UTF-8 preservati: OK")

def test_malformed_channel():
    bad = '<div data-testid="channel-card"><a href="/altro/x">no</a></div>' + CH_HTML
    ch = scraper.parse_channels(bad)
    assert len(ch) == 3  # la card non-canale è scartata
    print("4. card malformata scartata: OK")

def test_empty_stream():
    assert scraper.parse_programs("nessun dato qui") == []
    print("5. stream vuoto -> lista vuota: OK")

def test_current_next_logic():
    # Replica la logica di _current_and_next in isolamento
    progs = scraper.parse_programs(RSC)
    def parse(v): return datetime.fromisoformat(v.replace("Z","+00:00"))
    now = datetime(2026,9,26,19,30,tzinfo=timezone.utc)  # dentro Programma Uno
    cur = next((p for p in progs if parse(p["start"])<=now<parse(p["stop"])), None)
    nxt = next((p for p in progs if parse(p["start"])>now), None)
    assert cur["title"]=="Programma Uno"
    assert nxt["title"]=="Programma Due"
    # progress %
    pct = (now-parse(cur["start"]))/(parse(cur["stop"])-parse(cur["start"]))*100
    assert round(pct,1)==50.0
    print("6. logica in-onda + successivo + progress 50%: OK")

def test_dedup_sort():
    # due giorni con overlap: dedup per (start,title), ordina per start
    doubled = RSC + "," + RSC
    pr = scraper.parse_programs(doubled)
    seen=set(); uniq=[]
    for p in sorted(pr, key=lambda x:x["start"]):
        k=(p["start"],p["title"])
        if k not in seen: seen.add(k); uniq.append(p)
    assert len(uniq)==2
    assert uniq[0]["start"] <= uniq[1]["start"]
    print("7. dedup + ordinamento cronologico: OK")

def test_channel_h5_fallback():
    # Se manca il <p> con #, usa l'h5.channel-name (pagina dettaglio)
    html = '<div data-testid="channel-card"><a href="/canali/rai-1"><div class="image"><img alt="Logo canale Rai 1" src="x"/></div><h5 class="channel-name">#<!-- -->1<!-- --> <span>Digitale Terrestre</span></h5></div></a></div>'
    ch = scraper.parse_channels(html)
    assert ch[0]["number"] == "1", ch[0]
    assert ch[0]["category"] == "Digitale Terrestre", ch[0]
    print("8. fallback h5.channel-name (numero + categoria): OK")

def test_sanitize_slug():
    # Slug reali di guidatv.org con caratteri non validi per un entity_id
    cases = {
        "rai-1": "rai_1",
        "super!": "super",
        "sky-cinema-uno-+24-hd": "sky_cinema_uno_24_hd",
        "rtl-102.5-tv": "rtl_102_5_tv",
        "zona-dazn-2": "zona_dazn_2",
    }
    valid = __import__("re").compile(r"^[a-z0-9_]+$")
    for raw, expected in cases.items():
        got = scraper.sanitize_slug(raw)
        assert got == expected, f"{raw} -> {got} (atteso {expected})"
        assert valid.match(got), f"{got} non valido come object_id"
    print("9. sanitize_slug su slug problematici (super!, +24, .5): OK")

def test_detail_category_and_logo_helpers():
    d = '<h5 class="channel-name">#<!-- -->50<!-- --> <span class="x">Digitale Terrestre</span></h5>'
    assert scraper.parse_detail_category(d) == "Digitale Terrestre"
    assert scraper.parse_detail_category("<div>no h5</div>") is None
    proxy = "/_next/image?url=https%3A%2F%2Fimg-guidatv.org%2Floghi%2Fb%2F%2Frai1.png&w=3840&q=75"
    assert scraper.logo_source_url(proxy) == "https://img-guidatv.org/loghi/b//rai1.png"
    assert scraper.logo_source_url("https://img-guidatv.org/x.png") == "https://img-guidatv.org/x.png"
    assert scraper.logo_source_url(None) is None
    assert scraper.logo_filename("https://x/loghi/rai1.png", "rai_1") == "rai_1.png"
    assert scraper.logo_filename("https://x/y.jpeg", "super") == "super.jpg"
    print("10. categoria dettaglio + helper logo (source/filename): OK")

def test_filter_and_sort_channels():
    channels = [
        {"slug": "rai-1", "number": "1", "name": "Rai 1"},
        {"slug": "rsi-la1", "number": "CH1", "name": "RSI LA1"},
        {"slug": "sky-uno-hd", "number": "108", "name": "Sky Uno HD"},
        {"slug": "canale-20", "number": "20", "name": "Canale 20"},
    ]
    # selected_slugs=None -> nessun filtro (retrocompatibilità entry vecchie)
    assert scraper.filter_selected_channels(channels, None) == channels
    # selezione esplicita: solo gli slug richiesti, nell'ordine originale
    sel = scraper.filter_selected_channels(channels, ["sky-uno-hd", "rai-1"])
    assert [c["slug"] for c in sel] == ["rai-1", "sky-uno-hd"]
    # lista vuota esplicita -> nessun canale
    assert scraper.filter_selected_channels(channels, []) == []

    # sort_channels: numerici in ordine crescente, poi alfanumerici (CH1) in coda
    ordered = scraper.sort_channels(channels)
    assert [c["slug"] for c in ordered] == ["rai-1", "canale-20", "sky-uno-hd", "rsi-la1"]

    # channel_choice_label: "NUMERO - Nome", fallback su slug/? se mancanti
    assert scraper.channel_choice_label(channels[0]) == "1 - Rai 1"
    assert scraper.channel_choice_label({"slug": "x"}) == "? - x"
    print("11. filter_selected_channels + sort_channels + channel_choice_label: OK")

if __name__ == "__main__":
    test_channels(); test_programs(); test_accents()
    test_malformed_channel(); test_empty_stream()
    test_current_next_logic(); test_dedup_sort()
    test_channel_h5_fallback(); test_sanitize_slug()
    test_detail_category_and_logo_helpers()
    test_filter_and_sort_channels()
    print("\nTUTTI I 11 TEST PASSATI")
