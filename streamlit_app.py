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
.block-container{padding:0.6rem 1rem 3rem;max-width:720px;}
header[data-testid="stHeader"]{background:transparent;height:2rem;}
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
        carta("".join(righe) + '<div class="sub" style="margin-top:6px">Le spunte le metti nell\'app Catalyst: '
              f'qui arrivano al prossimo aggiornamento del piano.</div>')

    app_url = dati.get("app") or ""
    if app_url.startswith("https://"):
        md(f'<a class="btn" href="{e(app_url)}" target="_blank">Apri l\'app Catalyst (piano, spunte, news)</a>')

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
              f'<div style="margin-top:6px">{righe}</div>')

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


# ---------------------------------------------------------------- pagina
if not accesso():
    st.stop()
if not file_dati():
    st.error("Mancano i dati del piano (dati.json, o dati.enc con la chiave in Secrets): chiedi a Claude.")
    st.stop()

st.segmented_control("Sezione", ["Oggi", "Posizioni", "Decisioni", "Ribasso"], default="Oggi",
                     key="vista", label_visibility="collapsed")


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
    else:
        vista_ribasso(dati, live, xbi_a)

    md(f'<div class="foot">Piano aggiornato il {giorno(dati.get("generato", oggi))} alle '
       f'{(dati.get("generato") or "")[11:16]} dall\'app Catalyst. Prezzi da Yahoo Finance, ritardo di pochi secondi '
       f'per le azioni USA. Le stime servono a orientarti: per comprare e vendere fa fede eToro.</div>')


pagina()
