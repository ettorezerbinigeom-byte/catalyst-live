"""Catalyst Live: i prezzi in tempo reale di un piano di trading sui catalyst binari.

Il piano (posizioni, stop, calendario, decisioni FDA, osservati al ribasso) arriva da
dati.json, oppure da dati.enc (cifrato) quando la pagina gira online.
I prezzi arrivano da Yahoo Finance e si aggiornano da soli ogni minuto.

Avvio sul PC:  streamlit run app.py

Online (Streamlit Community Cloud) servono due valori in Secrets:
  chiave = "..."   chiave privata che apre dati.enc
  codice = "..."   codice d'accesso: la pagina si apre solo con ?k=<codice> o scrivendolo
"""
import base64
import datetime as dt
import hmac
import html
import json
import re
import time
from pathlib import Path
from statistics import fmean
from zoneinfo import ZoneInfo

import requests
import streamlit as st

ROMA = ZoneInfo("Europe/Rome")
NY = ZoneInfo("America/New_York")
DATI = Path(__file__).with_name("dati.json")
CIFRATI = Path(__file__).with_name("dati.enc")
LIMITE_DEFAULT = 0

# Borsa USA chiusa o chiusura anticipata (13:00 a New York = 19:00 a Roma)
CHIUSO = {"2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15",
          "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05"}
CORTO = {"2026-11-27", "2026-12-24", "2027-11-26"}

# Titoli che su Yahoo hanno un simbolo diverso
SIMBOLO = {"CAMX": "CAMX.ST"}
VALUTA = {"CAMX.ST": "kr"}
GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
SPIKE = {"meta": "nel verdetto tieni metà", "quarto": "nel verdetto tieni un quarto",
         "no": "vendi tutto prima del verdetto"}
LIVELLO = {"alto": "rischio alto", "medio": "rischio medio", "basso": "rischio basso"}
COLORE_TXT = {"rosso": "Rosso", "giallo": "Giallo", "verde": "Verde"}
COLORE_COSA = {
    "rosso": "Onde alte: niente acquisti nuovi. Le vendite in calendario si fanno, gli stop restano.",
    "giallo": "Compri solo le date in calendario, con prezzo limite non sopra la chiusura di ieri.",
    "verde": "Mercato tranquillo: piano normale.",
}

st.set_page_config(page_title="Catalyst Live", page_icon="🚦", layout="centered",
                   initial_sidebar_state="collapsed")

# ---------------------------------------------------------------- stile
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@600;800&family=IBM+Plex+Mono:wght@500&family=Public+Sans:wght@400;600;700&display=swap');
:root{--bg:#EDF0F3;--sf:#FFFFFF;--sf2:#F5F7F9;--ink:#111B25;--mut:#5A6673;--line:#D6DCE2;--acc:#2545C4;--acc-s:#E2E8FB;
--yes:#12784A;--yes-s:#DDF1E6;--no:#BE3128;--no-s:#FAE2DF;--may:#9E6410;--may-s:#F6E9D0;--house:#17212B;--off:#2C3845;
--l-rosso:#F0453A;--l-giallo:#F2B233;--l-verde:#2FBF71;--mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;}
html,body,[class*="st-"],.stMarkdown{font-family:"Public Sans",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;}
.stApp{background:var(--bg);}
.block-container{padding:0.8rem 1rem 3rem;max-width:720px;}
/* Su Streamlit Cloud la barra in alto (60px, sopra a tutto) copriva le sezioni e il codice: la nascondo */
header[data-testid="stHeader"]{display:none !important;}
#MainMenu,footer,[data-testid="stToolbar"] [data-testid="stToolbarActions"]{visibility:hidden;}
.cb-top{margin:6px 2px 10px;}
.cb-top h1{font-family:Archivo,"Arial Narrow",sans-serif;font-weight:800;font-size:1.45rem;letter-spacing:-.01em;margin:0;padding:0;color:var(--ink);}
.cb-top .ora{font-family:var(--mono);font-size:.76rem;color:var(--mut);line-height:1.4;margin-top:3px;}
.cb-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px;vertical-align:1px;}
.card{background:var(--sf);border:1px solid var(--line);border-radius:14px;padding:14px 15px;margin:0 0 10px;box-shadow:0 1px 2px rgba(17,27,37,.06),0 4px 14px rgba(17,27,37,.05);color:var(--ink);}
.card h3{font-family:Archivo,"Arial Narrow",sans-serif;font-size:1.02rem;font-weight:800;margin:0 0 6px;padding:0;color:var(--ink);}
.eyebrow{font-size:.72rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--mut);margin:16px 2px 6px;}
.row{display:flex;justify-content:space-between;align-items:baseline;gap:10px;padding:5px 0;border-top:1px solid var(--line);font-size:.92rem;}
.row:first-of-type{border-top:0;}
.row .k{color:var(--mut);}
.row .v{font-family:var(--mono);font-weight:500;text-align:right;}
.big{font-family:Archivo,"Arial Narrow",sans-serif;font-weight:800;font-size:2rem;line-height:1.05;letter-spacing:-.01em;}
.sub{color:var(--mut);font-size:.86rem;line-height:1.4;margin-top:3px;}
.mono{font-family:var(--mono);}
.up{color:var(--yes);} .down{color:var(--no);} .flat{color:var(--mut);}
.tag{display:inline-block;font-size:.72rem;font-weight:700;padding:2px 8px;border-radius:99px;background:var(--sf2);color:var(--mut);border:1px solid var(--line);margin-left:6px;vertical-align:2px;}
.tag.yes{background:var(--yes-s);color:var(--yes);border-color:transparent;}
.tag.no{background:var(--no-s);color:var(--no);border-color:transparent;}
.tag.may{background:var(--may-s);color:var(--may);border-color:transparent;}
.tag.acc{background:var(--acc-s);color:var(--acc);border-color:transparent;}
.alert{border-radius:12px;padding:10px 12px;margin:0 0 8px;font-size:.92rem;line-height:1.4;border:1px solid transparent;}
.alert b{font-weight:700;}
.alert.no{background:var(--no-s);color:#7d1d17;}
.alert.may{background:var(--may-s);color:#6b430a;}
.alert.yes{background:var(--yes-s);color:#0b4f30;}
.alert.acc{background:var(--acc-s);color:#1a3191;}
.sema{display:flex;gap:14px;align-items:center;}
.lamp{background:var(--house);border-radius:14px;padding:8px 7px;display:flex;flex-direction:column;gap:6px;flex:none;}
.lamp i{display:block;width:20px;height:20px;border-radius:50%;background:var(--off);}
.lamp i.on.rosso{background:var(--l-rosso);box-shadow:0 0 12px var(--l-rosso);}
.lamp i.on.giallo{background:var(--l-giallo);box-shadow:0 0 12px var(--l-giallo);}
.lamp i.on.verde{background:var(--l-verde);box-shadow:0 0 12px var(--l-verde);}
.bar{height:8px;border-radius:99px;background:var(--sf2);border:1px solid var(--line);overflow:hidden;margin:8px 0 2px;}
.bar span{display:block;height:100%;border-radius:99px;}
.tk{display:flex;justify-content:space-between;align-items:center;gap:10px;}
.tk .n{font-family:Archivo,"Arial Narrow",sans-serif;font-weight:800;font-size:1.15rem;}
.tk .nm{color:var(--mut);font-size:.82rem;}
.tk .p{text-align:right;font-family:var(--mono);}
.tk .p b{font-size:1.05rem;}
.when{display:inline-block;min-width:74px;margin-right:8px;font-family:var(--mono);font-size:.8rem;color:var(--mut);}
.btn{display:block;text-align:center;background:var(--acc);color:#fff !important;text-decoration:none !important;font-weight:700;padding:12px;border-radius:12px;margin:6px 0 10px;}
.btn.sec{background:var(--sf);color:var(--acc) !important;border:1px solid var(--line);}
.passi{margin:8px 0 0;padding-left:22px;font-size:.95rem;line-height:1.45;}
.passi li{margin:0 0 6px;padding-left:2px;}
.foot{color:var(--mut);font-size:.78rem;line-height:1.45;margin-top:14px;}
div[data-testid="stSegmentedControl"] button p{font-weight:700;}
.st-key-vista [data-testid="stButtonGroup"]>div{flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none;padding-bottom:2px;}
.st-key-vista [data-testid="stButtonGroup"]>div::-webkit-scrollbar{display:none;}
.st-key-vista button{flex:none;}
.res{font-family:Archivo,"Arial Narrow",sans-serif;font-weight:800;font-size:2.3rem;line-height:1;letter-spacing:-.02em;}
.wl{display:flex;height:9px;border-radius:99px;overflow:hidden;background:var(--sf2);border:1px solid var(--line);margin:10px 0 4px;}
.wl i{display:block;height:100%;}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:0 0 10px;}
.grid2 .card{margin:0;padding:11px 12px;}
.grid2 b{font-family:Archivo,"Arial Narrow",sans-serif;font-size:1.35rem;font-weight:800;display:block;line-height:1.1;}
.op{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:9px 0;border-top:1px solid var(--line);}
.op:first-child{border-top:0;padding-top:2px;}
.op .l{min-width:0;}
.op .t{font-family:var(--mono);font-weight:600;}
.op .d{font-family:var(--mono);font-size:.76rem;color:var(--mut);}
.op .r{text-align:right;font-family:var(--mono);font-weight:600;white-space:nowrap;}
.op .r small{display:block;font-weight:500;font-size:.74rem;color:var(--mut);}
.op.todo .r{color:var(--may);font-size:.8rem;}
.day{display:grid;grid-template-columns:54px 1fr;gap:10px;margin:0 0 10px;}
.dbox{background:var(--sf);border:1px solid var(--line);border-radius:10px;text-align:center;padding:5px 0;line-height:1.1;height:max-content;}
.dbox .w{font-family:var(--mono);font-size:.66rem;text-transform:uppercase;color:var(--mut);}
.dbox .n{font-family:Archivo,"Arial Narrow",sans-serif;font-weight:800;font-size:1.25rem;}
.dbox.oggi{background:var(--acc);border-color:var(--acc);}
.dbox.oggi *{color:#fff;}
.ev{background:var(--sf);border:1px solid var(--line);border-radius:12px;padding:9px 11px;margin:0 0 6px;font-size:.92rem;}
.ev.ord{border-color:#b5c1ef;}
.ev.mer{background:transparent;border-style:dashed;}
.ev.fatto b{text-decoration:line-through;color:var(--mut);}
.mese{font-family:Archivo,"Arial Narrow",sans-serif;font-weight:800;font-size:1.15rem;margin:16px 2px 8px;text-transform:capitalize;}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:1px;}
details.sk{margin-top:8px;border-top:1px solid var(--line);padding-top:6px;}
details.sk summary{cursor:pointer;font-weight:700;color:var(--acc);font-size:.9rem;}
details.sk p{margin:6px 0 0;font-size:.9rem;line-height:1.45;}
.ctl{display:flex;gap:8px;align-items:flex-start;margin:6px 0 0;font-size:.88rem;line-height:1.4;}
.ctl .m{flex:none;width:22px;height:22px;border-radius:6px;display:grid;place-items:center;font-weight:800;font-size:.8rem;}
.m.si{background:var(--yes-s);color:var(--yes);} .m.no{background:var(--no-s);color:var(--no);}
.m.dubbio{background:var(--may-s);color:var(--may);} .m.nd{background:var(--sf2);color:var(--mut);border:1px dashed var(--line);}
a.fonte{font-size:.84rem;}
</style>""", unsafe_allow_html=True)


# ---------------------------------------------------------------- formati
def it(x, dec=2):
    return f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def eur(x, dec=2, segno=False):
    s = "+" if segno and x >= 0 else ("−" if x < 0 else "")
    return f"{s}€{it(abs(x), dec)}"


def pct(x, dec=1):
    if x is None:
        return "–"
    return ("+" if x >= 0 else "−") + it(abs(x), dec) + "%"


def cls(x, soglia=0.05):
    if x is None:
        return "flat"
    return "up" if x > soglia else ("down" if x < -soglia else "flat")


def prezzo(x, sym=""):
    if x is None:
        return "–"
    return f"{it(x, 2 if x >= 1 else 4)} {VALUTA.get(sym, '$')}"


def num_da_testo(s):
    """'22,11 $' -> 22.11"""
    try:
        return float(str(s).replace("$", "").replace("€", "").strip().replace(".", "").replace(",", "."))
    except ValueError:
        return None


def giorno(iso):
    d = dt.date.fromisoformat(iso[:10])
    return f"{GIORNI[d.weekday()]} {d:%d/%m}"


def e(s):
    return html.escape(str(s or ""))


def simbolo(tk):
    return SIMBOLO.get(tk, tk)


# ---------------------------------------------------------------- borsa
def borsa(ora_roma):
    ny = ora_roma.astimezone(NY)

    def seduta(d):
        return d.weekday() < 5 and d.isoformat() not in CHIUSO

    def orari(d):
        a = dt.datetime.combine(d, dt.time(9, 30), NY)
        c = dt.datetime.combine(d, dt.time(13 if d.isoformat() in CORTO else 16, 0), NY)
        return a, c

    oggi = ny.date()
    if seduta(oggi):
        a, c = orari(oggi)
        if a <= ny < c:
            extra = " (chiusura anticipata)" if oggi.isoformat() in CORTO else ""
            return True, f"Borsa USA aperta, chiude alle {c.astimezone(ROMA):%H:%M}{extra}"
        if ny < a:
            return False, f"Borsa USA chiusa, apre oggi alle {a.astimezone(ROMA):%H:%M}"
    d = oggi + dt.timedelta(days=1)
    while not seduta(d):
        d += dt.timedelta(days=1)
    a, _ = orari(d)
    return False, f"Borsa USA chiusa, riapre {giorno(d.isoformat())} alle {a.astimezone(ROMA):%H:%M}"


# ---------------------------------------------------------------- Yahoo Finance
# Yahoo blocca gli user agent "da browser" senza cookie (429): quello corto funziona.
AGENTI = ("Mozilla/5.0", "Mozilla/5.0 (compatible; CatalystLive/1.0)")
_S = requests.Session()


class ErroreDati(RuntimeError):
    def __init__(self, msg, codice=None):
        super().__init__(msg)
        self.codice = codice


def yget(path, params):
    errore, codice = "nessuna risposta", None
    for base in ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"):
        for ua in AGENTI:
            try:
                r = _S.get(base + path, params=params, timeout=10, headers={"User-Agent": ua})
                if r.status_code == 200:
                    return r.json()
                errore, codice = f"HTTP {r.status_code}", r.status_code
                if r.status_code == 404:
                    raise ErroreDati(errore, codice)
            except (requests.RequestException, ValueError) as ex:
                errore = type(ex).__name__
            time.sleep(0.3)
    raise ErroreDati(errore, codice)


def num_usa(t):
    """'$1,028.15' o '+1.43' -> numero"""
    try:
        return float(str(t).replace("$", "").replace(",", "").replace("+", "").strip())
    except ValueError:
        return None


def nasdaq(sym):
    """Riserva se Yahoo non risponde: solo prezzo e variazione del giorno, azioni USA."""
    h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/130.0 Safari/537.36", "Accept": "application/json, text/plain, */*",
         "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
    for classe in ("stocks", "etf"):
        try:
            r = _S.get(f"https://api.nasdaq.com/api/quote/{sym}/info", params={"assetclass": classe},
                       headers=h, timeout=8)
            pd = ((r.json() or {}).get("data") or {}).get("primaryData") or {}
            p = num_usa(pd.get("lastSalePrice"))
            ch = num_usa(pd.get("netChange"))
        except (requests.RequestException, ValueError, AttributeError, TypeError):
            continue
        if p:
            prev = p - ch if ch is not None else None
            return {"p": p, "prev": prev, "pct": (p / prev - 1) * 100 if prev else None, "serie": [], "ora": None}
    return None


def _leggi_spark(d, out):
    for s, v in (d or {}).items():
        if not isinstance(v, dict):
            continue
        serie = [c for c in (v.get("close") or []) if c is not None]
        p = v.get("fulldayPrice") or (serie[-1] if serie else None)
        ch = v.get("fulldayChange")
        prev = (p - ch) if (p is not None and ch is not None) else (v.get("previousClose") or v.get("chartPreviousClose"))
        ts = v.get("timestamp") or []
        if p:
            out[s] = {"p": p, "prev": prev, "pct": (p / prev - 1) * 100 if prev else None,
                      "serie": serie, "ora": ts[-1] if ts else None}


@st.cache_data(ttl=40, show_spinner=False)
def prezzi(simboli):
    out = {}
    for i in range(0, len(simboli), 20):
        parte = simboli[i:i + 20]
        try:
            _leggi_spark(yget("/v8/finance/spark", {"symbols": ",".join(parte), "range": "1d", "interval": "5m"}), out)
        except ErroreDati as ex:
            if ex.codice == 404:  # un simbolo sbagliato non deve bloccare gli altri
                for s in parte:
                    try:
                        _leggi_spark(yget("/v8/finance/spark", {"symbols": s, "range": "1d", "interval": "5m"}), out)
                    except ErroreDati:
                        pass
    mancano = [s for s in simboli if s not in out and "^" not in s and "." not in s]
    if len(mancano) > len(simboli) // 2:  # Yahoo fermo: uso la riserva Nasdaq
        for s in mancano:
            q = nasdaq(s)
            if q:
                out[s] = q
    if not out:
        raise ErroreDati("Yahoo non risponde")
    return out


@st.cache_data(ttl=900, show_spinner=False)
def storia(sym, rng="1y"):
    """Chiusure giornaliere definitive: [(data, chiusura)], senza la seduta in corso."""
    r = yget(f"/v8/finance/chart/{sym}", {"range": rng, "interval": "1d"})["chart"]["result"][0]
    ts = r.get("timestamp") or []
    cl = r["indicators"]["quote"][0]["close"]
    righe = []
    for t, c in zip(ts, cl):
        if c is None:
            continue
        d = dt.datetime.fromtimestamp(t, NY).date().isoformat()
        if righe and righe[-1][0] == d:
            righe[-1] = (d, c)
        else:
            righe.append((d, c))
    reg = (r.get("meta", {}).get("currentTradingPeriod") or {}).get("regular") or {}
    adesso = time.time()
    if righe and righe[-1][0] == dt.datetime.fromtimestamp(adesso, NY).date().isoformat() and adesso < reg.get("end", 0):
        righe = righe[:-1]
    return righe


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def prezzo_al(sym, t):
    """Prezzo del titolo al momento t (epoch): serve per la stima del capitale."""
    for intervallo, indietro in (("5m", 4), ("1h", 7), ("1d", 12)):
        try:
            r = yget(f"/v8/finance/chart/{sym}", {"period1": t - indietro * 86400, "period2": t + 300,
                                                  "interval": intervallo})["chart"]["result"][0]
        except (ErroreDati, KeyError, TypeError, IndexError):
            continue
        migliore = None
        for a, c in zip(r.get("timestamp") or [], r["indicators"]["quote"][0]["close"]):
            if c is not None and a <= t:
                migliore = c
        if migliore:
            return migliore
    return None


# ---------------------------------------------------------------- calcoli
def colore(x, m50, m200, v):
    if v >= 30 or (x < m200 and v >= 25):
        return "rosso"
    if v < 22 and x > m200 and x > m50:
        return "verde"
    return "giallo"


def semaforo(live, aperta):
    xr, vr = storia("XBI", "2y"), storia("^VIX", "2y")
    vmap = dict(vr)
    comuni = [(d, c) for d, c in xr if d in vmap]
    xs = [c for _, c in comuni]
    vs = [vmap[d] for d, _ in comuni]
    n, col = len(xs), None
    for i in range(max(200, n - 80), n):
        raw = colore(xs[i], fmean(xs[i - 49:i + 1]), fmean(xs[i - 199:i + 1]), vs[i])
        if col == "rosso" and raw != "rosso" and not (vs[i] < 25 and vs[i - 1] < 25):
            raw = "rosso"
        col = raw
    out = {"uff": col, "giorno": comuni[-1][0], "vix": vs[-1], "xbi": xs[-1],
           "m50": fmean(xs[-50:]), "m200": fmean(xs[-200:]), "vix_ieri": vs[-1]}
    xl = (live.get("XBI") or {}).get("p")
    vl = (live.get("^VIX") or {}).get("p")
    if aperta and xl and vl:
        m50, m200 = fmean(xs[-49:] + [xl]), fmean(xs[-199:] + [xl])
        raw = colore(xl, m50, m200, vl)
        ora = raw
        if col == "rosso" and raw != "rosso" and not (vl < 25 and vs[-1] < 25):
            ora = "rosso"
        out.update(ora=ora, raw=raw, xl=xl, vl=vl, m50l=m50, m200l=m200)
    return out


def testo_ora(s):
    """Cosa succede se la Borsa chiude ai prezzi di adesso."""
    if "ora" not in s:
        return ""
    vl, uff, raw = s["vl"], s["uff"], s["raw"]
    if raw == "rosso":
        perche = "la paura (VIX) è sopra 30" if vl >= 30 else "XBI è sotto la sua linea lunga e il VIX è sopra 25"
        return f"Se chiudesse adesso resterebbe <b>rosso</b>: {perche}."
    if uff == "rosso":
        if vl >= 25:
            return (f"Il VIX è a {it(vl, 1)}: per uscire dal rosso deve chiudere sotto 25 "
                    "per due giorni di fila.")
        if s["vix_ieri"] >= 25:
            return ("Se chiude così è la prima chiusura con il VIX sotto 25: "
                    "ne serve un'altra domani per passare al giallo.")
        return f"Se chiude così stasera passa a <b>{raw}</b>: seconda chiusura di fila con il VIX sotto 25."
    if raw != uff:
        return f"Se chiudesse adesso passerebbe a <b>{raw}</b>."
    return f"Se chiudesse adesso resterebbe <b>{raw}</b>."


def stima_capitale(dati, live):
    stato = dati.get("stato", {})
    base = stato.get("capitaleEtoro")
    quando = stato.get("aggiornato")
    if base is None or not quando:
        return None
    t = int(dt.datetime.fromisoformat(quando[:16]).replace(tzinfo=ROMA).timestamp())
    righe, mancano, tot = {}, [], 0.0
    for tk, pos in dati.get("posizioni", {}).items():
        sym = simbolo(tk)
        p = (live.get(sym) or {}).get("p")
        rif = prezzo_al(sym, t) if p else None
        if not (p and rif and pos.get("valore") is not None):
            mancano.append(tk)
            continue
        pl = pos.get("pl") or 0.0
        esposizione = (pos["valore"] - pl) * (pos.get("leva") or 2) + pl
        delta = esposizione * (p / rif - 1)
        righe[tk] = {"rif": rif, "delta": delta, "valore": pos["valore"] + delta, "pl": pl + delta}
        tot += delta
    return {"stima": base + tot, "base": base, "quando": quando, "righe": righe, "mancano": mancano}


def andamento(sym, live):
    """Variazione 10 sedute e salita 3 mesi (63 sedute), con il prezzo di adesso."""
    try:
        cl = [c for _, c in storia(sym, "6mo")]
    except (RuntimeError, KeyError, TypeError, IndexError):
        return {}
    if not cl:
        return {}
    ora = (live.get(sym) or {}).get("p") or cl[-1]
    out = {"ora": ora}
    if len(cl) >= 10:
        out["d10"] = (ora / cl[-10] - 1) * 100
    if len(cl) >= 63:
        out["m3"] = (ora / cl[-63] - 1) * 100
    return out


def debole(a, xbi):
    """Regola del piano: il titolo scende mentre il biotech tiene."""
    return a.get("d10") is not None and xbi.get("d10") is not None and a["d10"] <= -8 and xbi["d10"] >= -2


# ---------------------------------------------------------------- pezzi di pagina
def spark(serie, prev, w=96, h=30):
    if len(serie) < 2:
        return ""
    vals = serie + ([prev] if prev else [])
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:
        hi = lo + 1e-9

    def y(v):
        return h - 2 - (v - lo) / (hi - lo) * (h - 4)
    pts = " ".join(f"{i * (w - 2) / (len(serie) - 1) + 1:.1f},{y(v):.1f}" for i, v in enumerate(serie))
    col = "var(--yes)" if serie[-1] >= (prev or serie[0]) else "var(--no)"
    rif = (f'<line x1="0" x2="{w}" y1="{y(prev):.1f}" y2="{y(prev):.1f}" stroke="var(--line)" '
           f'stroke-dasharray="3 3"/>') if prev else ""
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-hidden="true">{rif}'
            f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.8" '
            f'stroke-linejoin="round" stroke-linecap="round"/></svg>')


def riga(k, v, extra=""):
    return f'<div class="row"><span class="k">{k}</span><span class="v {extra}">{v}</span></div>'


def testa_titolo(tk, nome, q, sym):
    p, pc = q.get("p"), q.get("pct")
    return (f'<div class="tk"><div><span class="n">{e(tk)}</span><div class="nm">{e(nome)}</div></div>'
            f'{spark(q.get("serie") or [], q.get("prev"))}'
            f'<div class="p"><b>{prezzo(p, sym)}</b><div class="{cls(pc)}">{pct(pc)} oggi</div></div></div>')


def md(s):
    st.markdown(s, unsafe_allow_html=True)


def carta(contenuto):
    md(f'<div class="card">{contenuto}</div>')


def avviso(testo, tipo="may"):
    md(f'<div class="alert {tipo}">{testo}</div>')


# ---------------------------------------------------------------- dati del piano
def segreto(nome):
    try:
        v = st.secrets.get(nome)
    except Exception:  # sul PC non c'e' secrets.toml
        return None
    return str(v).strip() if v else None


def file_dati():
    if DATI.exists():
        return DATI
    if CIFRATI.exists() and segreto("chiave"):
        return CIFRATI
    return None


def apri_cifrati(blob, chiave_b64):
    """dati.enc: X25519 + HKDF-SHA256 + AES-GCM. Si cifra con la chiave pubblica (cifra_dati.py)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    import zlib
    d = json.loads(blob)
    priv = X25519PrivateKey.from_private_bytes(base64.b64decode(chiave_b64))
    comune = priv.exchange(X25519PublicKey.from_public_bytes(base64.b64decode(d["epk"])))
    k = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"catalyst-live v1").derive(comune)
    chiaro = AESGCM(k).decrypt(base64.b64decode(d["n"]), base64.b64decode(d["c"]), None)
    return json.loads(zlib.decompress(chiaro))


@st.cache_data(ttl=120, show_spinner=False)
def carica_dati(percorso, _mtime):
    f = Path(percorso)
    if f.suffix == ".enc":
        return apri_cifrati(f.read_bytes(), segreto("chiave"))
    return json.loads(f.read_text(encoding="utf-8"))


def accesso():
    """Online la pagina e' pubblica: senza il codice giusto non mostra niente."""
    codice = segreto("codice")
    if not codice:
        return True
    k = st.query_params.get("k") or ""
    if st.session_state.get("dentro") or hmac.compare_digest(k.encode(), codice.encode()):
        st.session_state["dentro"] = True
        return True
    md('<div class="cb-top"><h1>Catalyst Live</h1><div class="ora">Pagina privata</div></div>')
    x = st.text_input("Codice d'accesso", type="password", placeholder="Scrivi il codice e premi Invio")
    if x:
        if hmac.compare_digest(x.strip().encode(), codice.encode()):
            st.session_state["dentro"] = True
            st.query_params["k"] = codice
            st.rerun()
        st.error("Codice sbagliato.")
    return False


def ordini_aperti(dati, oggi):
    return [c for c in dati.get("calendario", []) if c.get("tipo") == "ordine" and not c.get("fatto")
            and c.get("data", "") >= oggi]


def decisioni(dati, oggi, giorni=150):
    fine = (dt.date.fromisoformat(oggi) + dt.timedelta(days=giorni)).isoformat()
    return [c for c in dati.get("calendario", []) if c.get("tipo") == "decisione"
            and oggi <= c.get("data", "") <= fine]


# ---------------------------------------------------------------- viste
def vista_oggi(dati, live, s, cap, aperta, oggi, xbi_a):
    stato = dati.get("stato", {})
    limite = stato.get("limite", LIMITE_DEFAULT)

    # avvisi automatici
    avvisi = []
    if cap:
        if cap["stima"] < limite:
            avvisi.append(("no", f"<b>Stima sotto il limite di {eur(limite, 0)}</b>: niente acquisti nuovi. "
                                 "Controlla il saldo vero su eToro."))
        elif cap["stima"] < limite + 20:
            avvisi.append(("may", f"<b>Sei a {eur(cap['stima'] - limite)} dal limite di {eur(limite, 0)}</b> (stima)."))
    for tk, pos in dati.get("posizioni", {}).items():
        sym = simbolo(tk)
        p = (live.get(sym) or {}).get("p")
        stop = num_da_testo(pos.get("stop"))
        if p and stop:
            if p <= stop:
                avvisi.append(("no", f"<b>{tk} è allo stop</b> ({prezzo(p)} contro {prezzo(stop)}): "
                                     "eToro dovrebbe averla chiusa, controlla."))
            elif p <= stop * 1.05:
                avvisi.append(("may", f"<b>{tk} è vicino allo stop</b>: {prezzo(p)}, stop {prezzo(stop)} "
                                      f"({pct((stop / p - 1) * 100)})."))
            if p >= stop / 0.8 * 1.3:
                avvisi.append(("yes", f"<b>{tk} è salita più del 30%</b> dall'ingresso stimato: "
                                      "la regola del piano dice di vendere metà."))
    for c in decisioni(dati, oggi, 30):
        tk = c.get("ticker")
        if tk in dati.get("posizioni", {}):
            a = andamento(simbolo(tk), live)
            if debole(a, xbi_a):
                avvisi.append(("no", f"<b>{tk} si indebolisce prima del verdetto</b>: {pct(a['d10'])} in 10 sedute "
                                     f"mentre il biotech fa {pct(xbi_a['d10'])}. La regola dice di uscire tutto prima "
                                     "della decisione: scrivimi prima di agire."))
            gg = (dt.date.fromisoformat(c["data"]) - dt.date.fromisoformat(oggi)).days
            if gg <= 3:
                avvisi.append(("acc", f"<b>{tk}: decisione FDA {'oggi' if gg == 0 else f'tra {gg} giorni'}</b> "
                                      f"({giorno(c['data'])}). La parte prima del verdetto va già venduta."))

    # prossimi passi: in cima, perché è la prima cosa da vedere dal telefono
    testo = (stato.get("avviso") or "").strip()
    if testo:
        parti = re.split(r"(?:(?<=[:;.])\s*|^)\d\)\s+", testo)
        intro, passi = parti[0].rstrip(" :;"), [x.strip().rstrip(";.") for x in parti[1:] if x.strip()]
        intro = re.sub(r"\s*Prossimi passi$", "", intro).rstrip(" .:")
        corpo = f'<div class="sub" style="color:var(--ink);font-size:.95rem">{e(intro)}.</div>' if intro else ""
        if passi:
            corpo += ('<ol class="passi">' + "".join(f"<li>{e(x[:1].upper() + x[1:])}.</li>" for x in passi) + "</ol>")
        carta(f'<div class="eyebrow" style="margin-top:0">Prossimi passi</div>{corpo}'
              f'<div class="sub" style="margin-top:6px">Dal piano aggiornato il {giorno(stato.get("aggiornato") or oggi)}.</div>')

    # semaforo
    if s:
        col = s["uff"]
        luci = "".join(f'<i class="{"on " + k if k == col else ""} {k}"></i>' for k in ("rosso", "giallo", "verde"))
        dettagli = (riga("Paura (VIX)", f'{it(s.get("vl", s["vix"]), 1)}', "") +
                    riga("Biotech (XBI)", f'{it(s.get("xl", s["xbi"]), 2)}') +
                    riga("Linea corta 50 giorni", it(s.get("m50l", s["m50"]), 2)) +
                    riga("Linea lunga 200 giorni", it(s.get("m200l", s["m200"]), 2)))
        ora = testo_ora(s)
        carta(f'<div class="sema"><div class="lamp">{luci}</div><div><div class="eyebrow" style="margin:0">'
              f'Semaforo · chiusura di {giorno(s["giorno"])}</div><div class="big">{COLORE_TXT[col]}</div>'
              f'<div class="sub">{COLORE_COSA[col]}</div></div></div>'
              f'{f"<div class=sub style=margin-top:10px>{ora}</div>" if ora else ""}'
              f'<div style="margin-top:8px">{dettagli}</div>')
    else:
        avviso("Il semaforo non si calcola: Yahoo non ha dato i dati storici. Riprovo al prossimo minuto.")

    for tipo, testo in avvisi:
        avviso(testo, tipo)

    # capitale
    if cap:
        stima = cap["stima"]
        margine = stima - limite
        obiettivo = stato.get("obiettivo") or limite + 1
        quota = max(0, min(1, (stima - limite) / max(1, obiettivo - limite)))
        colb = "var(--no)" if margine < 0 else ("var(--may)" if margine < 50 else "var(--yes)")
        if dati.get("posizioni"):
            nota = (f"Partendo dai {eur(cap['base'])} di eToro delle {cap['quando'][11:16]} del "
                    f"{giorno(cap['quando'])}, con le posizioni di allora mosse ai prezzi di adesso.")
            if cap["mancano"]:
                nota += f" Senza prezzo: {', '.join(cap['mancano'])}."
        else:
            nota = "Nessuna posizione aperta: sei tutto in liquidità e il valore non si muove con la Borsa."
            if stato.get("notaStima"):
                nota += " " + e(stato["notaStima"])
        carta(f'<div class="eyebrow" style="margin-top:0">Capitale stimato adesso</div>'
              f'<div class="big">{eur(stima)}</div>'
              f'<div class="sub"><b class="{cls(margine)}">{eur(margine, segno=True)}</b> rispetto al limite di '
              f'{eur(limite, 0)} · obiettivo {eur(obiettivo, 0)}</div>'
              f'<div class="bar"><span style="width:{quota * 100:.1f}%;background:{colb}"></span></div>'
              f'<div class="sub">{nota} Il numero vero è sempre quello di eToro.</div>')

    # prossimi ordini
    aperti = ordini_aperti(dati, oggi)
    md('<div class="eyebrow">Prossimi ordini</div>')
    if not aperti:
        carta('<div class="sub">Nessun ordine aperto in calendario.</div>')
    else:
        date = sorted({c["data"] for c in aperti})[:2]
        righe = []
        for c in aperti:
            if c["data"] not in date:
                continue
            tk = c.get("ticker")
            q = live.get(simbolo(tk), {}) if tk else {}
            px = (f' <span class="mono">{prezzo(q.get("p"), simbolo(tk))}</span> '
                  f'<span class="{cls(q.get("pct"))} mono">{pct(q.get("pct"))}</span>') if q.get("p") else ""
            az = {"compra": "acc", "vendi": "may", "stop": "no"}.get(c.get("azione"), "")
            righe.append(f'<div class="row" style="display:block"><span class="when">{giorno(c["data"])} '
                         f'{e(c.get("ora", ""))}</span><b>{e(c.get("titolo"))}</b>'
                         f'{f"<span class=tag {az}>{e(c.get("azione"))}</span>" if az else ""}{px}'
                         f'<div class="sub">{e(c.get("perche"))}</div></div>')
        carta("".join(righe) + '<div class="sub" style="margin-top:6px">Quando hai fatto un ordine scrivimelo '
              'in chat: lo segno io e lo trovi nello Storico.</div>')

    news = dati.get("news", [])[:3]
    if news:
        md('<div class="eyebrow">Ultime notizie</div>')
        carta("".join(f'<div class="row" style="display:block"><span class="when">{giorno(n["data"])}</span>'
                      f'<b>{e(n.get("titolo"))}</b></div>' for n in news))


def vista_posizioni(dati, live, cap):
    pos = dati.get("posizioni", {})
    if not pos:
        carta('<div class="sub">Nessuna posizione aperta nel piano.</div>')
        return
    titoli = dati.get("titoli", {})
    for tk, p in sorted(pos.items(), key=lambda kv: kv[1].get("ordine", 99)):
        sym = simbolo(tk)
        q = live.get(sym, {})
        prz = q.get("p")
        stop = num_da_testo(p.get("stop"))
        r = (cap or {}).get("righe", {}).get(tk)
        corpo = testa_titolo(tk, titoli.get(tk, {}).get("nome", ""), q, sym)
        righe = ""
        if r:
            righe += riga("Valore stimato adesso", eur(r["valore"]))
            righe += riga("Guadagno o perdita stimato", eur(r["pl"], segno=True), cls(r["pl"]))
        righe += riga(f"eToro alle {(dati.get('stato', {}).get('aggiornato') or '')[11:16]}",
                      f'{eur(p.get("valore", 0))} ({eur(p.get("pl", 0), segno=True)})')
        if stop:
            ingresso = stop / 0.8
            righe += riga("Stop", prezzo(stop, sym))
            if prz:
                dist = (stop / prz - 1) * 100
                righe += riga("Distanza dallo stop", pct(dist), "down" if dist > -5 else "")
                mov = (prz / ingresso - 1) * 100
                righe += riga("Dall'ingresso stimato (stop ÷ 0,8)", f"{pct(mov)} · con x{p.get('leva', 2)} "
                              f"{pct(mov * (p.get('leva') or 2))}", cls(mov))
        if p.get("azione"):
            righe += f'<div class="sub" style="margin-top:6px"><b>Cosa fai:</b> {e(p["azione"])}</div>'
        carta(corpo + f'<div style="margin-top:8px">{righe}</div>')
    md('<div class="foot">Le stime partono dall\'ultimo saldo eToro che mi hai mandato e non contano il cambio '
       'euro/dollaro e i costi notturni: il numero vero è sempre quello di eToro. '
       'L\'ingresso è ricavato dallo stop (che è il prezzo d\'acquisto meno 20%).</div>')


def vista_decisioni(dati, live, oggi, xbi_a):
    lista = decisioni(dati, oggi)
    titoli = dati.get("titoli", {})
    nomi = {r.get("ticker"): r.get("nome") for r in dati.get("ribasso", [])}
    pos = dati.get("posizioni", {})
    if not lista:
        carta('<div class="sub">Nessuna decisione FDA nei prossimi 5 mesi.</div>')
    for c in lista:
        tk = c.get("ticker") or ""
        sym = simbolo(tk)
        q = live.get(sym, {})
        t = titoli.get(tk, {})
        gg = (dt.date.fromisoformat(c["data"]) - dt.date.fromisoformat(oggi)).days
        tags = f'<span class="tag acc">tra {gg} g</span>' if gg else '<span class="tag no">oggi</span>'
        if tk in pos:
            tags += '<span class="tag yes">in portafoglio</span>'
        if c.get("osserva") == "ribasso":
            tags += '<span class="tag may">solo osservo</span>'
        righe = riga("Data", f'{giorno(c["data"])}{" " + e(c.get("ora")) if c.get("ora") else ""}')
        if t.get("spike") in SPIKE:
            righe += riga("Nel piano", SPIKE[t["spike"]], "")
        if gg <= 45:
            a = andamento(sym, live)
            if a.get("d10") is not None:
                righe += riga("Ultime 10 sedute", f'{pct(a["d10"])} · biotech {pct(xbi_a.get("d10"))}', cls(a["d10"]))
            if a.get("m3") is not None:
                righe += riga("Salita in 3 mesi (controllo: sotto 50%)", pct(a["m3"]),
                              "down" if a["m3"] >= 50 else "")
            if debole(a, xbi_a):
                righe += ('<div class="alert no" style="margin:8px 0 0">Segnale di debolezza: scende mentre il '
                          'biotech tiene. La regola dice di non tenerla nel verdetto.</div>')
        carta(f'{testa_titolo(tk, t.get("nome") or nomi.get(tk, ""), q, sym)}'
              f'<div class="sub" style="margin-top:6px">{e(c.get("titolo"))}{tags}</div>'
              f'<div style="margin-top:6px">{righe}</div>{scheda_titolo(t)}')

    altri = dati.get("altri", [])
    if altri:
        md('<div class="eyebrow">Altri settori (servono date ufficiali)</div>')
        righe = []
        for a in altri:
            q = live.get(simbolo(a.get("ticker", "")), {})
            righe.append(f'<div class="row"><span><b>{e(a.get("ticker"))}</b> <span class="k">{e(a.get("settore"))} · '
                         f'{e(a.get("stato"))}</span></span><span class="v">{prezzo(q.get("p"))} '
                         f'<span class="{cls(q.get("pct"))}">{pct(q.get("pct"))}</span></span></div>')
        carta("".join(righe))


def vista_ribasso(dati, live, xbi_a):
    stato = dati.get("stato", {})
    avviso("<b>Solo informazione.</b> Su eToro si guadagna dal ribasso solo con un CFD allo scoperto: "
           "la perdita non ha un tetto e un rialzo improvviso, come GameStop, può bruciare il conto in un giorno. "
           f"Sei vicino al limite di {eur(stato.get('limite', LIMITE_DEFAULT), 0)}: "
           "nessun ordine al ribasso senza una tua decisione esplicita.", "no")
    lista = dati.get("ribasso", [])
    ordine = {"alto": 0, "medio": 1, "basso": 2}
    attivi = sorted([r for r in lista if r.get("stato") != "successo"],
                    key=lambda r: (ordine.get(r.get("livello"), 3), r.get("data") or "9999"))
    passati = [r for r in lista if r.get("stato") == "successo"]
    for r in attivi:
        tk = r.get("ticker", "")
        sym = simbolo(tk)
        q = live.get(sym, {})
        liv = r.get("livello")
        tag = {"alto": "no", "medio": "may", "basso": ""}.get(liv, "")
        quando = giorno(r["data"]) if r.get("data") else (r.get("quando") or "senza data")
        righe = riga("Decisione", e(quando))
        a = andamento(sym, live)
        if a.get("d10") is not None:
            righe += riga("Ultime 10 sedute", f'{pct(a["d10"])} · biotech {pct(xbi_a.get("d10"))}', cls(a["d10"]))
        segn = "".join(f"<li>{e(x.get('testo'))}</li>" for x in (r.get("segnali") or [])[:4])
        carta(f'{testa_titolo(tk, r.get("nome", ""), q, sym)}'
              f'<div class="sub" style="margin-top:6px">{e(r.get("farmaco"))} · {e(r.get("evento"))}'
              f'<span class="tag {tag}">{LIVELLO.get(liv, e(liv))}</span></div>'
              f'<div style="margin-top:6px">{righe}</div>'
              f'{f"<ul class=sub style=margin:6px 0 0;padding-left:18px>{segn}</ul>" if segn else ""}'
              f'{f"<div class=sub style=margin-top:6px><b>{e(r.get("nelPiano"))}</b></div>" if r.get("nelPiano") else ""}')
    if passati:
        md('<div class="eyebrow">Casi già successi</div>')
        carta("".join(f'<div class="row" style="display:block"><b>{e(r.get("ticker"))}</b> '
                      f'<span class="k">{e(r.get("esito"))}</span>'
                      f'<div class="sub">{e(r.get("lezione"))}</div></div>' for r in passati))


# ---------------------------------------------------------------- scheda, storico, calendario, news
CONTROLLI = [("fase3", "Fase 3 centrata"), ("fda", "Nessun no dall'FDA"), ("prior", "Revisione prioritaria"),
             ("cassa", "Cassa per 2 anni"), ("salita", "Salita sotto il 50%")]
SEGNO = {"si": "✓", "no": "✗", "dubbio": "?", "nd": "–"}
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
        "ottobre", "novembre", "dicembre"]


def link_https(u, testo):
    u = str(u or "")
    if not re.fullmatch(r"https://[^\s\"'<>]+", u):
        return ""
    return f'<a class="fonte" href="{e(u)}" target="_blank" rel="noopener">{e(testo or "Fonte")}</a>'


def scheda_titolo(t):
    if not t:
        return ""
    parti = []
    if t.get("cosaFai"):
        parti.append(f'<p><b>Cosa fai:</b> {e(t["cosaFai"])}</p>')
    ctl = {c.get("k"): c for c in t.get("controlli") or []}
    if ctl:
        righe = ""
        for k, nome in CONTROLLI:
            c = ctl.get(k) or {}
            es = c.get("esito") if c.get("esito") in SEGNO else "nd"
            righe += (f'<div class="ctl"><span class="m {es}">{SEGNO[es]}</span><span><b>{e(nome)}</b>'
                      f'{" · " + e(c.get("nota")) if c.get("nota") else ""}</span></div>')
        parti.append(righe)
    for titolo, k in (("Cosa succede", "evento"), ("Perché lo seguiamo", "perche"), ("Cosa dicono i dati", "dati"),
                      ("Cosa può andare storto", "rischi"), ("Quanti soldi ha", "cassa")):
        if t.get(k):
            parti.append(f'<p><b>{titolo}:</b> {e(t[k])}</p>')
    fonti = " · ".join(x for x in (link_https(f.get("u"), f.get("t")) for f in t.get("fonti") or []) if x)
    if fonti:
        parti.append(f'<p>{fonti}</p>')
    if not parti:
        return ""
    return f'<details class="sk"><summary>Scheda: cosa fai e i 5 controlli</summary>{"".join(parti)}</details>'


def calcolo_op(o):
    """Come nell'Excel: RENDITA/PERDITA = uscita / entrata x importo - importo; R/P DEF = leva x RENDITA/PERDITA."""
    num = lambda v: v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    imp, pe, pu, lv, reale = (num(o.get(k)) for k in ("importo", "prezzoEntrata", "prezzoUscita", "leva", "risultatoEtoro"))
    rp = (pu / pe) * imp - imp if imp is not None and pe and pu else None
    rpdef = rp * lv if rp is not None and lv is not None else None
    ris = reale if reale is not None else rpdef
    return ris, (ris / imp if ris is not None and imp else None), reale is not None


def data_breve(iso):
    try:
        return dt.date.fromisoformat(str(iso)[:10]).strftime("%d/%m/%y")
    except ValueError:
        return "…"


def vista_storico(dati):
    ops = []
    for o in dati.get("operazioni", []):
        ris, quota, vero = calcolo_op(o)
        ops.append(dict(o, ris=ris, quota=quota, vero=vero))
    if not ops:
        carta('<div class="sub">Ancora nessuna operazione. Mandami lo screenshot di eToro o scrivimele in chat.</div>')
        return
    chiuse = [o for o in ops if o["ris"] is not None]
    todo = [o for o in ops if o["ris"] is None]
    vinte = [o for o in chiuse if o["ris"] > 0]
    perse = [o for o in chiuse if o["ris"] < 0]
    if chiuse:
        tot = sum(o["ris"] for o in chiuse)
        wp, lp = len(vinte) / len(chiuse) * 100, len(perse) / len(chiuse) * 100
        carta(f'<div class="eyebrow" style="margin-top:0">Risultato delle {len(chiuse)} operazioni chiuse</div>'
              f'<div class="res {cls(tot)}">{eur(tot, segno=True)}</div>'
              f'<div class="wl"><i style="width:{wp:.1f}%;background:var(--yes)"></i><i style="flex:1"></i>'
              f'<i style="width:{lp:.1f}%;background:var(--no)"></i></div>'
              f'<div class="sub"><b class="up">{len(vinte)}</b> in guadagno · <b class="down">{len(perse)}</b> in perdita. '
              f'Somma delle colonne R/P DEF (con la leva); dove c\'è il risultato vero di eToro conta quello.'
              f'{f" Le {len(todo)} da completare non sono nel totale." if todo else ""}</div>')
        media = lambda a: sum(o["ris"] for o in a) / len(a) if a else None
        best = max(chiuse, key=lambda o: o["ris"])
        worst = min(chiuse, key=lambda o: o["ris"])
        box = lambda v, testo: (f'<div class="card"><b class="{cls(v or 0)}">{eur(v, segno=True) if v is not None else "–"}</b>'
                                f'<span class="sub">{testo}</span></div>')
        md('<div class="grid2">' + box(media(vinte), "guadagno medio quando va bene") +
           box(media(perse), "perdita media quando va male") +
           box(best["ris"], f'la migliore: {e(best.get("titolo"))}, {data_breve(best.get("dataUscita"))}') +
           box(worst["ris"], f'la peggiore: {e(worst.get("titolo"))}, {data_breve(worst.get("dataUscita"))}') + '</div>')
    if todo:
        avviso(f'<b>{len(todo)} da completare:</b> manca il prezzo di uscita o il risultato. '
               'Mandami lo screenshot dello storico di eToro e le completo io.')
    # mese per mese
    mesi = {}
    for o in chiuse:
        k = str(o.get("dataUscita") or o.get("dataEntrata") or "")[:7]
        if k:
            mesi.setdefault(k, []).append(o)
    if mesi:
        md('<div class="eyebrow">Mese per mese (per data di uscita)</div>')
        righe = ""
        for k in sorted(mesi, reverse=True):
            v = sum(o["ris"] for o in mesi[k])
            a, m = k.split("-")
            righe += riga(f'<b style="color:var(--ink)">{MESI[int(m) - 1].capitalize()} {a}</b> · {len(mesi[k])} operazioni',
                          eur(v, segno=True), cls(v))
        carta(righe)
    # titolo per titolo
    per_tk = {}
    for o in chiuse:
        per_tk.setdefault(o.get("titolo"), []).append(o["ris"])
    if per_tk:
        righe = "".join(riga(f'<b class="mono" style="color:var(--ink)">{e(tk)}</b> · {len(v)}', eur(sum(v), segno=True),
                             cls(sum(v))) for tk, v in sorted(per_tk.items(), key=lambda kv: sum(kv[1])))
        md(f'<div class="card"><details class="sk" style="border:0;margin:0;padding:0"><summary>Titolo per titolo</summary>'
           f'<div style="margin-top:6px">{righe}</div></details></div>')
    # elenco
    md('<div class="eyebrow">Tutte le operazioni, dalla più recente</div>')
    filtro = st.segmented_control("Filtro storico", [f"Tutte {len(ops)}", f"Da completare {len(todo)}",
                                                     f"In guadagno {len(vinte)}", f"In perdita {len(perse)}"],
                                  key="filtro_storico", label_visibility="collapsed") or "Tutte"
    lista = (todo if filtro.startswith("Da completare") else vinte if filtro.startswith("In guadagno")
             else perse if filtro.startswith("In perdita") else ops)
    lista = sorted(lista, key=lambda o: (str(o.get("dataEntrata") or ""), o.get("nr") or 0), reverse=True)
    righe = ""
    for o in lista:
        lv = o.get("leva")
        pe, pu = o.get("prezzoEntrata"), o.get("prezzoUscita")
        det = (f'{eur(o["importo"]) if isinstance(o.get("importo"), (int, float)) else "?"}'
               f'{f" · x{lv:g}" if isinstance(lv, (int, float)) else ""} · '
               f'{prezzo(pe) if isinstance(pe, (int, float)) else "?"} → {prezzo(pu) if isinstance(pu, (int, float)) else "?"}')
        if o["ris"] is not None:
            dx = (f'<span class="{cls(o["ris"])}">{eur(o["ris"], segno=True)}</span>'
                  f'<small>{pct(o["quota"] * 100) if o["quota"] is not None else ""}{" · eToro" if o["vero"] else ""}</small>')
        else:
            dx = 'da completare'
        flag = '<div class="d" style="color:var(--may)">dati da controllare</div>' if o.get("controllare") else ""
        righe += (f'<div class="op{"" if o["ris"] is not None else " todo"}"><div class="l"><span class="t">{e(o.get("titolo"))}</span> '
                  f'<span class="d">{data_breve(o.get("dataEntrata"))} → {data_breve(o.get("dataUscita")) if o.get("dataUscita") else "…"}</span>'
                  f'<div class="d">{det}</div>{flag}</div><div class="r">{dx}</div></div>')
    carta(righe or '<div class="sub">Nessuna operazione in questo filtro.</div>')


def vista_calendario(dati, oggi):
    passati = st.toggle("Mostra anche i giorni passati", key="cal_passati")
    tipi = {"ordine": ("Ordine", "acc", "ord"), "decisione": ("Decisione FDA", "", ""), "mercato": ("Borsa", "", "mer"),
            "analisi": ("Analisi", "", "mer"), "promemoria": ("Promemoria", "", "")}
    evs = [c for c in dati.get("calendario", []) if c.get("data") and (passati or c["data"] >= oggi)]
    if not evs:
        carta('<div class="sub">Niente in calendario.</div>')
        return
    mese = None
    giorni = {}
    for c in evs:
        giorni.setdefault(c["data"], []).append(c)
    for d in sorted(giorni):
        if d[:7] != mese:
            mese = d[:7]
            a, m = mese.split("-")
            md(f'<div class="mese">{MESI[int(m) - 1]} {a}</div>')
        dd = dt.date.fromisoformat(d)
        corpo = ""
        for c in sorted(giorni[d], key=lambda x: x.get("seq", 99)):
            nome, tag, kl = tipi.get(c.get("tipo"), (c.get("tipo") or "", "", ""))
            if c.get("osserva") == "ribasso":
                nome, tag = "Osservo al ribasso", "no"
            fatto = c.get("tipo") == "ordine" and c.get("fatto")
            corpo += (f'<div class="ev {kl}{" fatto" if fatto else ""}"><span class="tag {tag}" style="margin-left:0">{e(nome)}</span>'
                      f'{f" <span class=mono>{e(c.get('ora'))}</span>" if c.get("ora") else ""}'
                      f'{" <span class=tag yes>fatto</span>" if fatto else ""}<div><b>{e(c.get("titolo"))}</b></div>'
                      f'{f"<div class=sub>{e(c.get('perche'))}</div>" if c.get("perche") else ""}</div>')
        md(f'<div class="day"><div class="dbox{" oggi" if d == oggi else ""}"><div class="w">{GIORNI[dd.weekday()]}</div>'
           f'<div class="n">{dd.day:02d}</div><div class="w">{MESI[dd.month - 1][:3]}</div></div><div>{corpo}</div></div>')


def vista_news(dati):
    news = sorted(dati.get("news", []), key=lambda n: n.get("data", ""), reverse=True)
    if not news:
        carta('<div class="sub">Nessuna notizia per ora.</div>')
        return
    tono = {"negativo": "var(--no)", "positivo": "var(--yes)"}
    tema = {"titoli": "Titoli", "fda": "Regole FDA", "altri": "Altri settori"}
    for n in news:
        f = n.get("fonte") or {}
        fonte = link_https(f.get("u"), f.get("t")) if isinstance(f, dict) else ""
        tks = " ".join(f'<span class="tag" style="margin-left:0">{e(t)}</span>' for t in n.get("tickers") or [])
        carta(f'<div class="sub" style="margin:0"><span class="dot" style="background:{tono.get(n.get("tono"), "var(--mut)")}"></span>'
              f'<span class="mono">{e(n.get("quando") or giorno(n.get("data", "")))}</span> · {e(tema.get(n.get("tema"), ""))}</div>'
              f'<h3 style="margin-top:6px">{e(n.get("titolo"))}</h3><div style="font-size:.92rem;line-height:1.45">{e(n.get("testo"))}</div>'
              f'{f"<div style=margin-top:6px>{tks}</div>" if tks else ""}{f"<div style=margin-top:4px>{fonte}</div>" if fonte else ""}')


def lista_consigliati(dati):
    c = dati.get("consigliati") or {}
    return (c.get("lista") if isinstance(c, dict) else c) or []


STATO_CONS = {"consigliato": ("yes", "consigliato"), "da valutare": ("may", "da valutare"),
              "solo osservo": ("", "solo da osservare"), "scartato": ("no", "scartato")}


def sedute_usa(a, b):
    """Sedute di Borsa USA dopo a e fino a b compreso (stesse feste di punteggio.py)."""
    feste = {"2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26",
             "2027-05-31", "2027-06-18", "2027-07-05"}
    n, d = 0, a
    while d < b:
        d += dt.timedelta(days=1)
        if d.weekday() < 5 and d.isoformat() not in feste:
            n += 1
    return n


def finestra_ora(c, oggi):
    """Stato della finestra d'ingresso, ricalcolato ogni giorno dalle date salvate."""
    en = c.get("entrata") or {}
    try:
        da, entro = dt.date.fromisoformat(en["da"]), dt.date.fromisoformat(en["entro"])
        o = dt.date.fromisoformat(oggi)
    except (KeyError, TypeError, ValueError):
        return None, ""
    if o < da:
        n = sedute_usa(o, da)
        return "presto", f"si apre {giorno(en['da'])}, tra {n} sedute"
    if o <= entro:
        return "aperta", f"aperta fino a {giorno(en['entro'])}"
    return "passata", f"passata il {giorno(en['entro'])}"


def carta_consigliato(c, live, oggi, xbi_a, rosso):
    tk = c.get("ticker") or ""
    sym = simbolo(tk)
    q = live.get(sym, {})
    pt = c.get("punteggio") or 0
    kl, lab = STATO_CONS.get(c.get("stato"), ("", e(c.get("stato"))))
    tags = f'<span class="tag {kl}">{pt} · {lab}</span>' if c.get("stato") != "scartato" else f'<span class="tag no">{lab}</span>'
    tags += '<span class="tag acc">nel piano</span>' if c.get("nelCalendario") else '<span class="tag">nuovo</span>'
    col = "var(--yes)" if pt >= 70 else ("var(--may)" if pt >= 50 else "var(--mut)")
    barra = (f'<div class="bar" aria-label="punteggio {pt} su 100"><span style="width:{max(0, min(pt, 100))}%;'
             f'background:{col}"></span></div>') if c.get("stato") != "scartato" else ""
    righe = ""
    if c.get("data") and c.get("stato") != "scartato":
        try:
            gg = (dt.date.fromisoformat(c["data"][:10]) - dt.date.fromisoformat(oggi)).days
            righe += riga("Decisione FDA", f'{giorno(c["data"])} · tra {gg} giorni' if gg > 0 else giorno(c["data"]))
        except ValueError:
            pass
        stato_f, txt_f = finestra_ora(c, oggi) if not c.get("dalPiano") else (None, "")
        if stato_f:
            cl_f = {"aperta": "up", "presto": "", "passata": "down"}[stato_f]
            righe += riga("Finestra per comprare", e(txt_f), cl_f)
        if c.get("uscita") and not c.get("dalPiano"):
            righe += riga("Vendi tutto entro", giorno(c["uscita"]))
    elif c.get("quando"):
        righe += riga("Quando", e(c["quando"]))
    a = andamento(sym, live) if c.get("stato") != "scartato" else {}
    m3 = a.get("m3") if a.get("m3") is not None else c.get("salita3m")
    if m3 is not None and c.get("stato") != "scartato":
        righe += riga("Salita in 3 mesi (sotto 50%)", pct(m3), "down" if m3 >= 50 else "")
    allarme = ""
    if c.get("stato") != "scartato" and (debole(a, xbi_a or {}) if a else c.get("debole")):
        allarme = ('<div class="alert no" style="margin:8px 0 0">Segnale di debolezza: scende mentre il biotech tiene. '
                   'Se è così quando si apre la finestra, non si compra.</div>')
    come = c.get("cosaFai") or c.get("ingresso")
    testo = f'<div class="sub" style="margin-top:6px"><b>Cosa fai:</b> {e(come)}</div>' if come else ""
    if rosso and c.get("stato") in ("consigliato", "da valutare"):
        testo += '<div class="sub" style="margin-top:4px;color:var(--no)">Oggi il semaforo è rosso: si aspetta.</div>'
    det = ""
    voti = c.get("voti") or []
    if voti:
        det += "".join(f'<div class="row" style="display:block"><span class="k"><b>{e(v.get("nome"))}</b> · '
                       f'{e(str(v.get("punti", "")))}/{e(str(v.get("max", "")))}</span><div class="sub" style="margin:2px 0 0">'
                       f'{e(v.get("nota"))}</div></div>' for v in voti)
    for titolo, k in (("Perché", "perche"), ("Cosa può andare storto", "rischi")):
        if c.get(k) and c.get(k) != "—":
            det += f'<p><b>{titolo}:</b> {e(c[k])}</p>'
    fonti = " · ".join(x for x in (link_https(f.get("u"), f.get("t")) for f in c.get("fonti") or []) if x)
    if fonti:
        det += f"<p>{fonti}</p>"
    if det:
        det = (f'<details class="sk"><summary>'
               f'{"Come è fatto il punteggio" if voti else "Dettagli e fonti"}</summary>{det}</details>')
    carta(f'{testa_titolo(tk, c.get("nome", ""), q, sym)}'
          f'<div class="sub" style="margin-top:6px">{e(c.get("evento"))}{tags}</div>{barra}'
          f'<div style="margin-top:6px">{righe}</div>{allarme}{testo}{det}')


def vista_consigliati(dati, live, oggi, xbi_a=None, s=None, cap=None):
    """Lista dei catalyst consigliati con punteggio (thread "Consigliare catalyst con punteggio").
    Dati: dati["consigliati"] = {"meta": meta/consigliati, "lista": [consigliati/<TICKER>]};
    li calcola /mnt/project-files/app-catalyst/consigliati/punteggio.py e li scrive nel db dell'app."""
    blocco = dati.get("consigliati") or {}
    meta = blocco.get("meta", {}) if isinstance(blocco, dict) else {}
    lista = sorted(lista_consigliati(dati), key=lambda c: -(c.get("punteggio") or 0))
    md('<div class="sub" style="margin:0 2px 10px">Idee per avere più titoli in portafoglio, con un punteggio '
       'da 0 a 100. Non sono ordini: quelli nuovi li confermiamo insieme la domenica.</div>')
    if not lista:
        carta('<div class="sub">La lista dei consigliati è in preparazione: arriva qui appena è pronta.</div>')
        return

    stato = dati.get("stato", {})
    capitale = (cap or {}).get("stima") or stato.get("capitaleEtoro")
    limite = stato.get("limite") or meta.get("limite") or 743
    bud = meta.get("budget") or {}
    marg, leva, stop = bud.get("margine", 90), bud.get("leva", 2), bud.get("stop", 0.2)
    perdita = marg * leva * stop
    aperte = len(dati.get("posizioni") or {})
    if capitale and perdita:
        regge = max(0, int((capitale - limite) // perdita))
        liberi = max(0, regge - aperte)
        piu = regge + 2
        marg_piu = int(((capitale - limite) / (piu * leva * stop)) // 5 * 5) if capitale > limite else 0
        testo = (f'Con circa {eur(capitale, 0)} e il limite di {eur(limite, 0)} reggi <b>{regge} stop</b> da '
                 f'{eur(perdita, 0)}: fino a {regge} titoli da {eur(marg, 0)} a x{leva}. '
                 f'Ne hai {aperte} aperti, quindi <b>{liberi} posti liberi</b>.')
        if marg_piu >= 20:
            testo += f' Per averne {piu} insieme servono {eur(marg_piu, 0)} a titolo.'
        nota = f'<div class="sub" style="margin-top:6px">{e(bud["nota"])}</div>' if bud.get("nota") else ""
        carta(f'<div class="eyebrow" style="margin:0 0 4px">Quanti titoli puoi tenere</div>'
              f'<div style="font-size:.95rem;line-height:1.45">{testo}</div>{nota}')
    colore = (s or {}).get("ora") or (s or {}).get("uff") or meta.get("semaforo")
    rosso = colore == "rosso"
    if rosso:
        avviso("<b>Semaforo rosso:</b> oggi non si compra niente, nemmeno da questa lista. "
               "I punteggi tolgono 5 punti a tutti finché resta rosso.", "no")
    for n in meta.get("novita") or []:
        avviso(e(n), "may")

    attivi = [c for c in lista if c.get("stato") in ("consigliato", "da valutare")]
    osserva = [c for c in lista if c.get("stato") == "solo osservo"]
    scartati = [c for c in lista if c.get("stato") == "scartato"]
    for c in attivi:
        carta_consigliato(c, live, oggi, xbi_a, rosso)
    if osserva:
        md('<div class="eyebrow">Solo da osservare (sotto 50)</div>')
        for c in osserva:
            carta_consigliato(c, live, oggi, xbi_a, rosso)
    if scartati:
        md('<div class="eyebrow">Tolti dalla lista</div>')
        for c in scartati:
            carta_consigliato(c, live, oggi, xbi_a, rosso)

    regole = "".join(f"<li>{e(r)}</li>" for r in meta.get("regole") or [])
    spieg = meta.get("spiegazione")
    if spieg or regole:
        carta(f'<details class="sk" style="margin:0;border:0;padding:0"><summary>Come leggere il punteggio</summary>'
              f'{f"<p>{e(spieg)}</p>" if spieg else ""}{f"<ul class=passi>{regole}</ul>" if regole else ""}</details>')
    agg = meta.get("aggiornato") or max((c.get("aggiornato") or "" for c in lista), default="")
    if agg:
        md(f'<div class="foot">Punteggi calcolati il {giorno(agg)} alle {agg[11:16]}: si aggiornano la domenica '
           f'e ogni 3 giorni. Prezzi e salita qui sopra sono in tempo reale.</div>')


# ---------------------------------------------------------------- pagina
if not accesso():
    st.stop()
if not file_dati():
    st.error("Mancano i dati del piano (dati.json, o dati.enc con la chiave in Secrets): chiedi a Claude.")
    st.stop()

VISTE = ["Oggi", "Storico", "Calendario", "Decisioni", "Consigliati", "Posizioni", "Ribasso", "News"]
if st.session_state.get("vista") not in VISTE:
    st.session_state["vista"] = "Oggi"
st.segmented_control("Sezione", VISTE, key="vista", label_visibility="collapsed")


@st.fragment(run_every=60)
def pagina():
    f = file_dati()
    dati = carica_dati(str(f), f.stat().st_mtime)
    ora = dt.datetime.now(ROMA)
    oggi = ora.date().isoformat()
    aperta, txt_borsa = borsa(ora)

    tickers = set(dati.get("posizioni", {})) | set(dati.get("titoli", {}))
    tickers |= {r.get("ticker") for r in dati.get("ribasso", []) if r.get("stato") != "successo"}
    tickers |= {a.get("ticker") for a in dati.get("altri", [])}
    tickers |= {c.get("ticker") for c in lista_consigliati(dati)}
    tickers |= {c.get("ticker") for c in ordini_aperti(dati, oggi) + decisioni(dati, oggi)}
    simboli = tuple(sorted({simbolo(t) for t in tickers if t} | {"XBI", "^VIX"}))

    errore = None
    try:
        live = prezzi(simboli)
        st.session_state["ultimi"] = (live, ora)
    except RuntimeError as ex:
        errore = str(ex)
        live, quando = st.session_state.get("ultimi", ({}, None))
    try:
        s = semaforo(live, aperta)
    except (RuntimeError, KeyError, TypeError, IndexError, ValueError):
        s = None
    xbi_a = andamento("XBI", live)
    cap = stima_capitale(dati, live)

    pallino = "var(--l-verde)" if aperta else "var(--mut)"
    md(f'<div class="cb-top"><h1>Catalyst Live</h1><div class="ora">'
       f'<span class="cb-dot" style="background:{pallino}"></span>{e(txt_borsa)}<br>'
       f'Prezzi delle {ora:%H:%M:%S}, si aggiornano ogni minuto</div></div>')
    if errore:
        avviso(f"Yahoo Finance non risponde ({e(errore)}): mostro gli ultimi prezzi ricevuti. Riprovo tra un minuto.")

    vista = st.session_state.get("vista") or "Oggi"
    if vista == "Oggi":
        vista_oggi(dati, live, s, cap, aperta, oggi, xbi_a)
    elif vista == "Posizioni":
        vista_posizioni(dati, live, cap)
    elif vista == "Decisioni":
        vista_decisioni(dati, live, oggi, xbi_a)
    elif vista == "Storico":
        vista_storico(dati)
    elif vista == "Calendario":
        vista_calendario(dati, oggi)
    elif vista == "News":
        vista_news(dati)
    elif vista == "Consigliati":
        vista_consigliati(dati, live, oggi, xbi_a, s, cap)
    else:
        vista_ribasso(dati, live, xbi_a)

    md(f'<div class="foot">Piano aggiornato il {giorno(dati.get("generato", oggi))} alle '
       f'{(dati.get("generato") or "")[11:16]}. Prezzi da Yahoo Finance, ritardo di pochi secondi '
       f'per le azioni USA. Le stime servono a orientarti: per comprare e vendere fa fede eToro. '
       f'Ordini fatti e operazioni nuove: scrivimeli in chat, li inserisco io.</div>')


pagina()
