# -*- coding: utf-8 -*-
"""Gündəlik Maliyyə Portalı — Google Sheets ilə işləyir (oxu + yaz)."""
import datetime as dt
import hashlib
import hmac
import html as htmllib
import json
import re
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Maliyyə portalı", page_icon="💼", layout="centered")

# ───────────── Tənzimləmələr ─────────────
FIRST_ROW = 3          # məlumat 3-cü sətirdən başlayır (1-2 başlıqdır)
LAST_COL = 23          # W sütunu
try:
    TZ = ZoneInfo("Asia/Baku")
except Exception:
    TZ = dt.timezone(dt.timedelta(hours=4))

# Apps Script "Web app" ünvanı (Yerləşdir/Deploy-dan sonra aldığınız link)
SCRIPT_URL = "https://script.google.com/macros/s/AKfycbzDUgbEzTPvaSl8rER7NZZtPMGJePOXZCIevBic7jtQcJuj5BP9a1XdYKDHfCQY6JXUQA/exec"
EXPECTED_VERSION = 6   # Code.gs-dəki VERSION ilə uyğun olmalıdır
SCRIPT_TOKEN = "9c63849298a70dfe"   # Code.gs-dəki TOKEN ilə eyni
# "equivalent" → USD\AZN sütununa AZN qarşılığı avtomatik yazılır (məbləğ × məzənnə)
#                (məzənnənin özü həmin xananın qeydində (note) saxlanır)
# "rate"       → USD\AZN sütununa yalnız məzənnənin özü yazılır
AZN_MODE = "equivalent"


# (sütun, etiket, qrup)  — hamısı AZN
LOCAL_FIELDS = [
    (2, "🟦 Kapital · 1101", "Kapital bank"),
    (3, "🟦 Kapital · 9580", "Kapital bank"),
    (4, "🟦 Kapital · 3854\\Taksit", "Kapital bank"),
    (5, "🟦 Kapital · 1815", "Kapital bank"),
    (6, "🟩 m10 · balans", "m10"),
    (7, "🟨 Yelo · Kart", "Yelo bank"),
    (8, "🟨 Yelo · Depozit", "Yelo bank"),
    (9, "🟪 Leobank · Kart", "Leobank"),
    (10, "🟪 Leobank · Depozit", "Leobank"),
    (11, "🟧 Ubank · Kart", "Ubank"),
    (12, "🔵 Gündəlik · Nağd", "Gündəlik nağd"),
    (13, "🟢 Kassada · Nağd", "Kassada nağd"),
]
FX_NAME = "Xarici vəsait"
GROUP_COLORS = {
    "Kapital bank": "#2E75B6", "m10": "#548235", "Yelo bank": "#BF8F00", "Leobank": "#7030A0",
    "Ubank": "#C55A11", "Gündəlik nağd": "#2F5597", "Kassada nağd": "#00796B", FX_NAME: "#C00000",
}
CURRENCIES = [  # (kod, simvol, rəng, məbləğ sütunu)  — növbəti sütun \AZN-dir
    ("USD", "$", "#2E7D32", 14),
    ("EUR", "€", "#1565C0", 16),
    ("RUB", "₽", "#C62828", 18),
    ("AED", "Dh", "#EF6C00", 20),
    ("TRY", "₺", "#6A1B9A", 22),
]
PAGES = ["✏️ Gündəlik giriş", "📈 Dinamika"]

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, .stApp { font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif; }
.block-container { max-width: 760px; padding: 1.1rem 1rem 4rem; }
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
.topbar { display:flex; align-items:center; justify-content:space-between; margin-bottom:.35rem; }
.logo { font-weight:800; font-size:1.2rem; letter-spacing:-.4px; }
/* səhifə seçimi — həb düymələr */
div[role="radiogroup"] { gap:.4rem; }
div[role="radiogroup"] > label { background:rgba(128,128,128,.14); padding:.3rem .95rem; border-radius:999px;
    border:1px solid rgba(128,128,128,.2); cursor:pointer; }
div[role="radiogroup"] > label > div:first-child { display:none; }
div[role="radiogroup"] > label:has(input:checked) { background:linear-gradient(135deg,#2563eb,#7c3aed); border-color:transparent; }
div[role="radiogroup"] > label:has(input:checked) p { color:#fff !important; font-weight:600; }
/* cəmi kartı */
.hero2 { background:linear-gradient(135deg,#1e3a8a 0%,#2563eb 55%,#06b6d4 100%); color:#fff; border-radius:24px;
    padding:18px 18px 14px; box-shadow:0 14px 34px rgba(37,99,235,.32); position:relative; overflow:hidden; margin-top:.5rem; }
.hero2:after { content:""; position:absolute; right:-40px; top:-46px; width:170px; height:170px; border-radius:50%; background:rgba(255,255,255,.12); }
.hero2-label { font-size:.72rem; opacity:.85; letter-spacing:.5px; text-transform:uppercase; }
.hero2-total { font-size:2.3rem; font-weight:800; letter-spacing:-1px; line-height:1.15; margin:2px 0 12px; }
.hero2-total span { font-size:1.2rem; opacity:.85; font-weight:600; }
.hero2-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; position:relative; z-index:1; }
.hero2-grid div { background:rgba(255,255,255,.16); border-radius:14px; padding:8px 12px; }
.hero2-grid small { display:block; font-size:.66rem; opacity:.85; }
.hero2-grid b { font-size:1rem; }
.chips { display:flex; flex-wrap:wrap; gap:6px; margin:10px 0 6px; }
.gchip { display:inline-flex; align-items:center; gap:6px; font-size:.7rem; padding:4px 10px; border-radius:999px;
    background:rgba(128,128,128,.12); border:1px solid rgba(128,128,128,.16); }
.gchip i { width:8px; height:8px; border-radius:50%; background:var(--c); display:inline-block; }
.gchip b { font-weight:700; }
.pill { display:block; padding:9px 14px; border-radius:14px; font-size:.84rem; margin:4px 0 10px; border:1px solid; }
.pill.new { background:rgba(34,197,94,.12); border-color:rgba(34,197,94,.35); }
.pill.edit { background:rgba(59,130,246,.12); border-color:rgba(59,130,246,.35); }
.card-title { font-weight:700; font-size:.95rem; margin:0 0 2px; }
.rates { display:grid; grid-template-columns:repeat(5,1fr); gap:6px; margin:4px 0 6px; }
.rate { border-radius:12px; padding:7px 3px; color:#fff; text-align:center; }
.rate b { display:block; font-size:.64rem; opacity:.92; }
.rate span { font-size:.76rem; font-weight:700; }
.eq { margin-top:1.75rem; font-weight:700; font-size:.92rem; text-align:right; white-space:nowrap; }
.eq small { display:block; font-weight:400; opacity:.6; font-size:.66rem; }
.stNumberInput input { text-align:right; font-weight:600; }
.stNumberInput label p { font-size:.8rem; }
.stButton > button { width:100%; border-radius:14px; font-weight:600; padding:.55rem 1rem; }
.stButton > button[kind="primary"], .stButton > button[data-testid="stBaseButton-primary"] {
    background:linear-gradient(135deg,#2563eb,#7c3aed); border:0; color:#fff; }
div[data-testid="stVerticalBlockBorderWrapper"] { border-radius:18px; }
div[data-testid="stExpander"] { border-radius:16px; }
@media (max-width: 640px) {
  div[data-testid="stHorizontalBlock"] { flex-wrap:nowrap !important; gap:.6rem !important; }
  div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
  div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] { min-width:0 !important; flex:1 1 0 !important; width:auto !important; }
  .hero2-total { font-size:2rem; }
}
</style>
""", unsafe_allow_html=True)


def fmt_rate(x):
    return f"{x:.4f}" if x >= 0.1 else f"{x:.6f}"


def money(x):
    return f"{x:,.2f}"


# ───────────── Giriş (şifrə) ─────────────
def gate():
    pw = secret("APP_PASSWORD", "7F2M5ZN")  # Secrets-də APP_PASSWORD yazsanız o keçərli olur
    if st.session_state.get("auth"):
        return
    st.markdown('<div class="hero2" style="text-align:center;margin-top:3rem"><div class="hero2-label">Xoş gəlmisiniz</div>'
                '<div class="hero2-total" style="font-size:1.8rem">💼 Maliyyə portalı</div>'
                '<div class="hero2-label">Davam etmək üçün şifrəni daxil edin</div></div>', unsafe_allow_html=True)
    typed = st.text_input("🔑 Şifrə", type="password")
    if typed:
        if hmac.compare_digest(typed.encode(), pw.encode()):
            st.session_state["auth"] = True
            st.rerun()
        else:
            st.error("Şifrə səhvdir.")
    st.stop()


# ───────────── Google Sheets (Apps Script vasitəsilə) ─────────────
def secret(name, default=""):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def api(payload):
    url = secret("SCRIPT_URL", SCRIPT_URL)
    token = secret("SCRIPT_TOKEN", SCRIPT_TOKEN)
    r = requests.post(url, data=json.dumps({**payload, "token": token}),
                      headers={"Content-Type": "text/plain"}, timeout=40)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data


def to_date(v):
    if isinstance(v, str):
        s = v.strip()
        for f in ("%Y-%m-%d", "%d %B %Y", "%d.%m.%Y"):
            try:
                return dt.datetime.strptime(s, f).date()
            except ValueError:
                pass
    return None


@st.cache_data(ttl=30, show_spinner=False)
def load_rows():
    data = api({"action": "read"})
    rows = {}
    for r in data["rows"]:
        d = to_date(r["date"])
        if d:
            rows[d] = (r["row"], ([None] + list(r["values"]) + [0] * LAST_COL)[:LAST_COL],
                       list(r.get("rates", [])))
    meta = {"version": data.get("version"), "sheet": data.get("sheet"), "debug": data.get("debug", [])}
    return rows, data["next_row"], meta


def save_day(d, values, rate_list):
    line = [values.get(c, 0.0) for c in range(2, LAST_COL + 1)]
    res = api({"action": "write", "date": d.isoformat(), "values": line, "rates": rate_list})
    load_rows.clear()
    return res


# ───────────── Məzənnə: AMB (rəsmi) → ehtiyat mənbə ─────────────
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "application/xml,text/xml,application/json,*/*"}
CODES = [c[0] for c in CURRENCIES]


AED_PER_USD = 3.6725   # dirhəm dollara sabit bağlıdır


def _from_azn_day(d, errs):
    """azn.day.az — bugünün AMB məzənnələri (USD, EUR, RUB, TRY). AED saytda yoxdur → USD-dən hesablanır."""
    if d != dt.datetime.now(TZ).date():
        return None            # saytda yalnız bugünün məzənnəsi var
    try:
        r = requests.get("https://azn.day.az/az/", headers=UA, timeout=12)
        r.raise_for_status()
        text = htmllib.unescape(re.sub(r"<[^>]+>", " ", r.text))
        text = re.sub(r"\s+", " ", text)
        words = {"avro": "EUR", "Rusiya rublu": "RUB", "Türk lirəsi": "TRY", "ABŞ dolları": "USD"}
        out = {}
        for m in re.finditer(r"([0-9]+[.,][0-9]+) manat (\d+) (avro|Rusiya rublu|Türk lirəsi|ABŞ dolları) üçün", text):
            code = words[m.group(3)]
            if code not in out:     # ilk rast gəlinən = AMB bloku
                out[code] = float(m.group(1).replace(",", ".")) / float(m.group(2))
        if not {"USD", "EUR", "RUB", "TRY"} <= set(out):
            errs.append("azn.day.az: səhifədən məzənnələr oxunmadı")
            return None
        out["AED"] = round(out["USD"] / AED_PER_USD, 4)
        return out, d, "azn.day.az (AMB məzənnəsi; AED dollardan hesablanıb)"
    except Exception as e:
        errs.append(f"azn.day.az: {type(e).__name__}")
        return None


def _from_cbar(d, errs):
    """Azərbaycan Mərkəzi Bankının rəsmi XML-i; elan olunmayıbsa ən yaxın əvvəlki gün."""
    for back in range(0, 7):
        day = d - dt.timedelta(days=back)
        try:
            r = requests.get(f"https://www.cbar.az/currencies/{day:%d.%m.%Y}.xml", headers=UA, timeout=12)
        except Exception as e:
            errs.append(f"cbar.az: {type(e).__name__}")
            return None
        if r.status_code == 404:
            continue
        if r.status_code != 200:
            errs.append(f"cbar.az: HTTP {r.status_code}")
            return None
        try:
            out = {}
            for v in ET.fromstring(r.content).iter("Valute"):
                code = v.get("Code")
                if code in CODES:
                    nominal = float(re.sub(r"[^\d]", "", v.findtext("Nominal") or "1") or 1)
                    out[code] = float(v.findtext("Value").replace(",", ".")) / nominal
            if set(CODES) <= set(out):
                return out, day, "Azərbaycan Mərkəzi Bankı (cbar.az)"
            errs.append(f"cbar.az: {day:%d.%m.%Y} faylında bütün valyutalar yoxdur")
        except Exception as e:
            errs.append(f"cbar.az: XML oxunmadı ({type(e).__name__})")
        return None
    return None


def _from_currency_api(d, errs):
    """Ehtiyat: açıq currency-api (1 AZN = X valyuta → tərsi alınır). 2024-03-02-dən tarixi də var."""
    today = dt.datetime.now(TZ).date()
    tags = [d.isoformat()] if dt.date(2024, 3, 2) <= d <= today else []
    tags.append("latest")
    for tag in tags:
        for url in (f"https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{tag}/v1/currencies/azn.json",
                    f"https://{tag}.currency-api.pages.dev/v1/currencies/azn.json"):
            try:
                r = requests.get(url, headers=UA, timeout=12)
                r.raise_for_status()
                js = r.json()
                out = {c: round(1.0 / float(js["azn"][c.lower()]), 6) for c in CODES}
                try:
                    day = dt.date.fromisoformat(js.get("date", ""))
                except ValueError:
                    day = today
                return out, day, "currency-api (bazar məzənnəsi, AMB-dən az fərqlənə bilər)"
            except Exception as e:
                errs.append(f"currency-api ({tag}): {type(e).__name__}")
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_cached(d: dt.date):
    errs = []
    for fn in (_from_azn_day, _from_cbar, _from_currency_api):
        res = fn(d, errs)
        if res:
            return {"rates": res[0], "day": res[1], "source": res[2], "errors": errs}
    raise RuntimeError(" | ".join(errs) or "naməlum xəta")   # uğursuz nəticə keşlənmir


def fetch_rates(d):
    try:
        return fetch_cached(d)
    except Exception as e:
        return {"rates": None, "errors": [str(e)]}



# ───────────── Dinamika səhifəsi ─────────────
def build_history(rows, fb_rates):
    """Hər gün üçün qrup cəmləri (AZN). Xarici vəsait AZN qarşılığı ilə."""
    recs, known = [], [0.0] * len(CURRENCIES)
    for d in sorted(rows):
        _, vals, rts = rows[d]
        for i in range(len(CURRENCIES)):
            if i < len(rts) and isinstance(rts[i], (int, float)) and rts[i] > 0:
                known[i] = float(rts[i])
        g = {name: 0.0 for name in GROUP_COLORS}
        for col, label, grp in LOCAL_FIELDS:
            g[grp] += float(vals[col - 1] or 0)
        fx = 0.0
        for i, (code, sym, color, col) in enumerate(CURRENCIES):
            amt, azn = float(vals[col - 1] or 0), float(vals[col] or 0)
            if AZN_MODE == "rate":
                fx += amt * azn if azn > 0 else amt * (known[i] or fb_rates.get(code, 0))
            elif azn > 0:
                fx += azn
            elif amt:
                fx += amt * (known[i] or fb_rates.get(code, 0))
        g[FX_NAME] = fx
        recs.append({"Tarix": pd.Timestamp(d), **g})
    return pd.DataFrame(recs)


def draw_chart(df, cols, mode):
    try:
        import altair as alt
        x = alt.X("Tarix:T", title=None, axis=alt.Axis(format="%d.%m", tickCount="day", labelOverlap=True))
        if mode == "Cəmi":
            base = alt.Chart(df).encode(
                x=x, y=alt.Y("Cəmi:Q", title=None, scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip("Tarix:T", title="Tarix", format="%d.%m.%Y"),
                         alt.Tooltip("Cəmi:Q", title="Cəmi ₼", format=",.2f")])
            chart = (base.mark_area(opacity=0.16, color="#2563eb") + base.mark_line(color="#2563eb", strokeWidth=3)
                     + base.mark_point(color="#2563eb", size=70, filled=True)).properties(height=320, width="container")
        else:
            long = df.melt(id_vars="Tarix", value_vars=cols, var_name="Qrup", value_name="Məbləğ")
            chart = alt.Chart(long).mark_line(point=True, strokeWidth=2.5).encode(
                x=x, y=alt.Y("Məbləğ:Q", title=None),
                color=alt.Color("Qrup:N", scale=alt.Scale(domain=cols, range=[GROUP_COLORS[c] for c in cols]),
                                legend=alt.Legend(orient="bottom", title=None)),
                tooltip=[alt.Tooltip("Tarix:T", title="Tarix", format="%d.%m.%Y"), alt.Tooltip("Qrup:N"),
                         alt.Tooltip("Məbləğ:Q", title="₼", format=",.2f")]
            ).properties(height=320, width="container")
        st.altair_chart(chart)
    except Exception:
        if mode == "Cəmi":
            st.line_chart(df.set_index("Tarix")[["Cəmi"]])
        else:
            st.line_chart(df.set_index("Tarix")[cols])


def render_dynamics(rows, today):
    st.markdown('<div class="card-title" style="font-size:1.3rem;margin:.6rem 0 .4rem">📈 Gündəlik dinamika</div>',
                unsafe_allow_html=True)
    if not rows:
        st.info("Cədvəldə hələ tarix yoxdur — əvvəlcə «Gündəlik giriş» səhifəsindən məlumat yazın.")
        return
    fetched = fetch_rates(today)
    hist = build_history(rows, fetched.get("rates") or {})
    local_groups = [g for g in GROUP_COLORS if g != FX_NAME]

    with st.container(border=True):
        use_fx = st.toggle("🌍 Xarici vəsaiti hesaba qat", value=True, key="dyn_fx")
        chosen = st.multiselect("Hansı bank / nağd qrupları hesablansın?", local_groups,
                                default=local_groups, key="dyn_groups")
        c1, c2 = st.columns(2)
        periods = {"Son 7 gün": 7, "Son 30 gün": 30, "Son 90 gün": 90, "Hamısı": 0}
        period = c1.selectbox("Dövr", list(periods), index=3, key="dyn_period")
        mode = c2.selectbox("Görünüş", ["Cəmi", "Qruplar üzrə"], key="dyn_mode")

    cols = chosen + ([FX_NAME] if use_fx else [])
    if not cols:
        st.warning("Heç bir qrup seçilməyib.")
        return
    if periods[period]:
        hist = hist[hist["Tarix"] >= hist["Tarix"].max() - pd.Timedelta(days=periods[period] - 1)]
    hist = hist.copy()
    hist["Cəmi"] = hist[cols].sum(axis=1)

    last = float(hist["Cəmi"].iloc[-1])
    delta = last - float(hist["Cəmi"].iloc[-2]) if len(hist) > 1 else None
    m1, m2, m3 = st.columns(3)
    m1.metric("Son cəmi", f"{money(last)} ₼", delta=(f"{delta:+,.2f} ₼" if delta is not None else None))
    m2.metric("Ən yüksək", f"{money(float(hist['Cəmi'].max()))} ₼")
    m3.metric("Orta", f"{money(float(hist['Cəmi'].mean()))} ₼")

    draw_chart(hist, cols, mode)
    if len(hist) < 2:
        st.caption("Xətt görünməsi üçün ən azı 2 günün məlumatı lazımdır.")
    if use_fx:
        st.caption("Xarici vəsait hər günün öz məzənnəsi ilə AZN-ə çevrilib. AZN qarşılığı və məzənnə qeydi olmayan "
                   "köhnə günlər üçün ən yaxın məlum (və ya bugünkü) məzənnə istifadə olunur.")
    with st.expander("📋 Gün-gün cədvəl"):
        show = hist[["Tarix"] + cols + ["Cəmi"]].copy()
        show["Tarix"] = show["Tarix"].dt.strftime("%d.%m.%Y")
        st.dataframe(show.iloc[::-1], hide_index=True)


# ═════════════ Səhifə ═════════════
gate()
st.markdown('<div class="topbar"><div class="logo">💼 Maliyyə portalı</div></div>', unsafe_allow_html=True)
page = st.radio("Səhifə", PAGES, horizontal=True, key="page", label_visibility="collapsed")

if st.session_state.get("flash"):
    st.success(st.session_state.pop("flash"))
    st.balloons()

try:
    rows, next_row, meta = load_rows()
except Exception as e:
    st.error("⚠️ Cədvələ qoşulmaq olmadı.")
    st.caption("Yoxlayın: ① SCRIPT_URL düzgündür, ② Apps Script-də Who has access = Anyone, "
               "③ Code.gs-dəki TOKEN ilə eynidir, ④ fayl Google Sheets formatındadır.")
    st.code(str(e))
    st.stop()

today = dt.datetime.now(TZ).date()
if page == PAGES[1]:
    render_dynamics(rows, today)
    st.stop()

# ═════════════ Gündəlik giriş ═════════════
hero_ph = st.container()

d = st.date_input("📅 Yazılacaq tarix", value=today, format="DD.MM.YYYY")
iso = d.isoformat()

existing = rows.get(d)
ex_row, ex_vals, ex_rates = existing if existing else (None, None, None)

# Eyni tarix varsa → o sətir düzəlir. Yoxdursa → ən yaxın əvvəlki günün məlumatı xanalara dolur,
# təsdiqləyəndə yeni tarix üçün ən alt sətrə yeni sətir yazılır.
base_date, base_vals = None, None
if not existing and rows:
    earlier = [x for x in rows if x < d]
    base_date = max(earlier) if earlier else min(rows)
    base_vals = rows[base_date][1]

# cədvəldəki məlumat dəyişəndə xanalar cədvəldən yenidən doldurulsun
sig = hashlib.md5(repr((ex_vals, ex_rates, base_date, None if ex_vals else base_vals)).encode()).hexdigest()[:6]

if meta.get("version") != EXPECTED_VERSION:
    st.error("⚠️ Apps Script köhnə versiyadır — tarixlər səhv oxuna bilər (məlumat dolmur, eyni gün təkrar yazılır). "
             "Apps Script-ə yeni Code.gs-i yapışdırın, Save edin və **Deploy (Dağıt) → Manage deployments "
             "(Dağıtımları yönet) → ✏️ → Version: New version (Yeni sürüm) → Deploy** edin. "
             "Yoxlamaq üçün Web app linkini brauzerdə açın: `\"version\": 6` görünməlidir.")

if existing:
    st.markdown(f'<div class="pill edit">✏️ <b>{d:%d.%m.%Y}</b> cədvəldə var (sətir {ex_row}) — təsdiqləsəniz həmin sətir düzələcək.</div>',
                unsafe_allow_html=True)
elif base_date:
    st.markdown(f'<div class="pill new">🆕 <b>{base_date:%d.%m.%Y}</b> məlumatları dolduruldu — təsdiqləyəndə '
                f'<b>{d:%d.%m.%Y}</b> üçün yeni sətir (sətir {next_row}) yazılacaq, {base_date:%d.%m.%Y} olduğu kimi qalacaq.</div>',
                unsafe_allow_html=True)
else:
    st.markdown(f'<div class="pill new">🆕 <b>{d:%d.%m.%Y}</b> üçün yeni sətir (sətir {next_row}) yazılacaq.</div>',
                unsafe_allow_html=True)


def default(col):
    src = ex_vals or base_vals
    v = src[col - 1] if src else None
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


# ── Məzənnə
fetched = fetch_rates(d)
rates, from_sheet = {}, False
for i, (code, sym, color, col) in enumerate(CURRENCIES):
    base = None
    if ex_rates and i < len(ex_rates) and isinstance(ex_rates[i], (int, float)) and ex_rates[i] > 0:
        base, from_sheet = float(ex_rates[i]), True          # həmin gün saxlanmış məzənnə
    elif ex_vals and AZN_MODE == "rate":
        v = ex_vals[col]
        if isinstance(v, (int, float)) and v > 0:
            base, from_sheet = float(v), True
    if base is None and fetched["rates"]:
        base = fetched["rates"][code]
    rates[code] = base or 0.0

st.markdown('<div class="card-title">💱 Günün məzənnəsi</div>', unsafe_allow_html=True)
strip_ph = st.container()
with st.expander("✏️ Məzənnəni əl ilə düzəlt"):
    for code, sym, color, col in CURRENCIES:
        rates[code] = st.number_input(f"{code} → AZN", value=rates[code], min_value=0.0, step=0.0001,
                                      format="%.6f", key=f"rate_{code}_{iso}_{sig}_{rates[code]:.6f}")
if from_sheet:
    st.caption("Mənbə: bu gün üçün cədvəldə saxlanmış məzənnə.")
elif fetched["rates"]:
    extra = "" if fetched["day"] == d else " (seçilən gün üçün hələ elan olunmayıb, ən yaxın tarix göstərilir)"
    st.caption(f"Mənbə: {fetched['source']} · {fetched['day']:%d.%m.%Y}{extra}")
else:
    st.warning("Məzənnə avtomatik alınmadı — yuxarıdakı xanadan əl ilə yazın.")
    with st.expander("🔧 Texniki detallar"):
        st.code("\n".join(fetched["errors"]))
    if st.button("🔄 Yenidən yoxla"):
        fetch_cached.clear()
        st.rerun()
strip_ph.markdown(
    '<div class="rates">' + "".join(
        f'<div class="rate" style="background:{color}"><b>{code}</b><span>{rates[code]:.4f}</span></div>'
        for code, sym, color, col in CURRENCIES) + '</div>', unsafe_allow_html=True)

# ── Hesablar
values = {}
by_col = {c: (lbl, g) for c, lbl, g in LOCAL_FIELDS}


def grid(cols_list, container):
    for i in range(0, len(cols_list), 2):
        cc = container.columns(2)
        for j, col in enumerate(cols_list[i:i + 2]):
            values[col] = cc[j].number_input(by_col[col][0], value=default(col), step=1.0, format="%.2f",
                                             key=f"f{col}_{iso}_{sig}")


with st.container(border=True):
    st.markdown('<div class="card-title">🏦 Bank hesabları (AZN)</div>', unsafe_allow_html=True)
    grid(list(range(2, 12)), st)
with st.container(border=True):
    st.markdown('<div class="card-title">💵 Nağd vəsait (AZN)</div>', unsafe_allow_html=True)
    grid([12, 13], st)

# ── Xarici vəsait (basanda açılır)
total_azn = 0.0
with st.expander("🌍 Xarici vəsait — USD · EUR · RUB · AED · TRY", expanded=False):
    st.caption("Məbləği yazın — AZN qarşılığı həmin günün məzənnəsi ilə hesablanıb cədvəlin \\AZN sütununa avtomatik yazılacaq.")
    for code, sym, color, col in CURRENCIES:
        c1, c2 = st.columns([3, 2])
        amt = c1.number_input(f"{sym} {code}", value=default(col), step=1.0, format="%.2f", key=f"f{col}_{iso}_{sig}")
        c2.markdown(f'<div class="eq">≈ {money(amt * rates[code])} ₼<small>1 {code} = {fmt_rate(rates[code])}</small></div>',
                    unsafe_allow_html=True)
        values[col] = amt
        values[col + 1] = rates[code] if AZN_MODE == "rate" else round(amt * rates[code], 2)
        total_azn += amt * rates[code]

# ── Cəmi kartı (yuxarıda)
group_sums = {g: 0.0 for g in GROUP_COLORS}
for col, lbl, g in LOCAL_FIELDS:
    group_sums[g] += values[col]
group_sums[FX_NAME] = total_azn
local_total = sum(v for g, v in group_sums.items() if g != FX_NAME)
grand = local_total + total_azn
chips = "".join(f'<span class="gchip" style="--c:{GROUP_COLORS[g]}"><i></i>{g} <b>{money(v)}</b></span>'
                for g, v in group_sums.items() if v)
with hero_ph:
    st.markdown(
        f'<div class="hero2"><div class="hero2-label">Cəmi vəsait · {d:%d.%m.%Y}</div>'
        f'<div class="hero2-total">{money(grand)} <span>₼</span></div>'
        f'<div class="hero2-grid"><div><small>Xarici olmadan</small><b>{money(local_total)} ₼</b></div>'
        f'<div><small>Xarici vəsait (≈)</small><b>{money(total_azn)} ₼</b></div></div></div>'
        f'<div class="chips">{chips}</div>', unsafe_allow_html=True)
    st.button("📈 Gündəlik dinamikaya bax", key="go_dyn", on_click=lambda: st.session_state.update(page=PAGES[1]))

# ── Yoxla → Təsdiqlə
st.write("")
cur_rates = [rates[c[0]] for c in CURRENCIES]
if st.button("🔍 Yoxla və təsdiqə göndər", type="primary"):
    st.session_state["pending"] = {"date": d, "values": dict(values), "rates": cur_rates}

pend = st.session_state.get("pending")
if pend and pend["date"] == d and pend["values"] == values and pend["rates"] == cur_rates:
    target = ex_row or next_row
    st.markdown(f'<div class="pill {"edit" if existing else "new"}">✅ <b>{d:%d.%m.%Y}</b> → cədvəlin <b>{target}-ci sətri</b> '
                f'({"yenilənəcək" if existing else "yeni yazılacaq"}) · Cəmi <b>{money(grand)} ₼</b> · '
                f'xarici olmadan <b>{money(local_total)} ₼</b></div>', unsafe_allow_html=True)
    with st.expander("Bütün xanalara bax"):
        table = [(lbl, money(pend["values"][c])) for c, lbl, g in LOCAL_FIELDS]
        for code, sym, color, col in CURRENCIES:
            table.append((f"{code}", money(pend["values"][col])))
            table.append((f"{code}\\AZN", money(pend["values"][col + 1]) if AZN_MODE != "rate"
                          else f"{pend['values'][col + 1]:.4f}"))
        st.dataframe(pd.DataFrame(table, columns=["Sahə", "Dəyər"]), hide_index=True)
    b1, b2 = st.columns(2)
    saved = False
    if b1.button("✅ Təsdiqlə və Sheet-ə yaz", type="primary"):
        try:
            save_day(d, pend["values"], pend["rates"])
            saved = True
        except Exception as e:
            st.error("Yazmaq alınmadı.")
            st.code(str(e))
    if saved:
        st.session_state.pop("pending", None)
        st.session_state["flash"] = f"✅ {d:%d.%m.%Y} cədvələ yazıldı (sətir {target})."
        st.rerun()
    if b2.button("✖ Ləğv et"):
        st.session_state.pop("pending", None)
        st.rerun()

# ── Texniki
with st.expander(f"🔧 Texniki məlumat · cədvəldə {len(rows)} tarix"):
    if rows:
        st.dataframe(pd.DataFrame([{"Tarix": f"{k:%d.%m.%Y}", "Sətir": v[0]} for k, v in sorted(rows.items())]),
                     hide_index=True)
        st.caption(f"Axtarılan tarix: {d:%d.%m.%Y} → " + (f"tapıldı (sətir {ex_row})" if existing else "cədvəldə yoxdur"))
    else:
        st.write("Heç bir tarix oxunmadı — A sütununda (3-cü sətirdən) tarixlərin olduğunu yoxlayın.")
    st.caption(f"Vərəq: {meta.get('sheet')} · skript versiyası: {meta.get('version')}")
    if meta.get("debug"):
        st.dataframe(pd.DataFrame(meta["debug"]).rename(columns={"row": "Sətir", "raw": "Xanada", "kind": "Növ",
                                                                  "parsed": "Tarix kimi"}), hide_index=True)
    if st.button("🔄 Cədvəli yenidən oxu"):
        load_rows.clear()
        st.rerun()
