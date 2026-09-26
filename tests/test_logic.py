"""Test logici su scraper e logica in-onda (SPEC Verifiche)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "guida_tv"))
from datetime import datetime, timezone
import scraper

CH_HTML = '''
<div data-testid="channel-card"><a href="/canali/rai-1"><div class="channel_card"><div class="image"><img alt="Logo canale Rai 1" src="http://logo/rai1.png"/></div><h5 class="channel-name">#<!-- -->1<!-- --> <span>Digitale Terrestre</span></h5></div></a></div>
<div data-testid="channel-card"><a href="/canali/rsi-la1"><div class="channel_card"><div class="image"><img alt="Logo canale RSI LA1" src="http://logo/rsi.png"/></div><h5 class="channel-name">#<!-- -->CH1<!-- --> <span>Digitale Terrestre</span></h5></div></a></div>
<div data-testid="channel-card"><a href="/canali/sky-uno-hd"><div class="channel_card"><div class="image"><img alt="Logo canale Sky Uno HD" src="http://logo/sky.png"/></div><h5 class="channel-name">#<!-- -->108<!-- --> <span>Sky Intrattenimento</span></h5></div></a></div>
'''

RSC = r'''x\"other\":1},{\"id\":\"a1\",\"title\":\"Programma Uno\",\"description\":\"Città e società, perché sì.\",\"durata\":\"60\",\"genre\":\"Film\",\"category\":\"Film\",\"image\":\"http://img/1.jpg\",\"director\":null,\"inizio\":\"2026-09-26T19:00:00.000Z\",\"fine\":\"2026-09-26T20:00:00.000Z\",\"year\":\"2020\"},{\"id\":\"a2\",\"title\":\"Programma Due\",\"description\":\"Segue.\",\"durata\":\"30\",\"genre\":\"News\",\"category\":\"News\",\"image\":\"http://img/2.jpg\",\"director\":null,\"inizio\":\"2026-09-26T20:00:00.000Z\",\"fine\":\"2026-09-26T20:30:00.000Z\",\"year\":null}'''

def test_channels():
    ch = scraper.parse_channels(CH_HTML)
    assert len(ch) == 3
    assert ch[0] == {"slug":"rai-1","name":"Rai 1","number":"1","logo":"http://logo/rai1.png","category":"Digitale Terrestre"}
    assert ch[1]["number"] == "CH1"
    assert ch[2]["category"] == "Sky Intrattenimento"
    print("1. parse_channels (DTT + CH + Sky): OK")

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

if __name__ == "__main__":
    test_channels(); test_programs(); test_accents()
    test_malformed_channel(); test_empty_stream()
    test_current_next_logic(); test_dedup_sort()
    print("\nTUTTI I 7 TEST PASSATI")
