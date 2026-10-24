import datetime as dt
import hmac
import json
import re
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Gündəlik Maliyyə Portalı", page_icon="💼", layout="centered")

# ───────────── Tənzimləmələr ─────────────
FIRST_ROW = 3          # məlumat 3-cü sətirdən başlayır (1-2 başlıqdır)
LAST_COL = 23          # W sütunu
try:
    TZ = ZoneInfo("Asia/Baku")
except Exception:
    TZ = dt.timezone(dt.timedelta(hours=4))

# Apps Script "Web app" ünvanı (Yerləşdir/Deploy-dan sonra aldığınız link)
SCRIPT_URL = "https://script.google.com/macros/s/AKfycbzDUgbEzTPvaSl8rER7NZZtPMGJePOXZCIevBic7jtQcJuj5BP9a1XdYKDHfCQY6JXUQA/exec"
SCRIPT_TOKEN = "9c63849298a70dfe"   # Code.gs-dəki TOKEN ilə eyni
# "equivalent" → USD\AZN sütununa AZN qarşılığı avtomatik yazılır (məbləğ × məzənnə)
#                (məzənnənin özü həmin xananın qeydində (note) saxlanır)
# "rate"       → USD\AZN sütununa yalnız məzənnənin özü yazılır
AZN_MODE = "equivalent"

SECTIONS = [  # (başlıq, rəng, [(etiket, sütun nömrəsi)])
    ("Kapital", "#2E75B6", [("1101", 2), ("9580", 3), ("3854", 4), ("1815", 5)]),
    ("m10", "#548235", [("balans", 6)]),
    ("Yelo bank", "#BF8F00", [("Kart", 7), ("Depozit", 8)]),
    ("Leobank", "#7030A0", [("Kart", 9), ("Depozit", 10)]),
    ("Ubank", "#C55A11", [("Kart", 11)]),
    ("Gündəlik", "#2F5597", [("Nağd vəsaitim", 12)]),
    ("Kassada olan", "#00796B", [("Nağd vəsaitim", 13)]),
]
CURRENCIES = [  # (kod, simvol, rəng, məbləğ sütunu)  — növbəti sütun \AZN-dir
    ("USD", "$", "#2E7D32", 14),
    ("EUR", "€", "#1565C0", 16),
    ("RUB", "₽", "#C62828", 18),
    ("AED", "AED", "#EF6C00", 20),
    ("TRY", "₺", "#6A1B9A", 22),
]

st.markdown("""
<style>
.block-container{padding-top:1.4rem;padding-bottom:3rem;max-width:760px}
.hero{background:linear-gradient(135deg,#1e3a8a,#2563eb 60%,#0ea5e9);color:#fff;padding:22px 18px;
      border-radius:20px;text-align:center;margin-bottom:14px;box-shadow:0 8px 24px rgba(30,58,138,.25)}
.hero h1{margin:0;font-size:1.55rem;color:#fff}
.hero p{margin:6px 0 0;opacity:.85;font-size:.9rem}
.chip{display:inline-block;color:#fff;font-weight:700;font-size:.82rem;padding:4px 12px;
      border-radius:999px;margin-bottom:6px;letter-spacing:.3px}
.rate-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(104px,1fr));gap:8px;margin:6px 0 4px}
.rate{border-radius:14px;padding:10px 8px;color:#fff;text-align:center;box-shadow:0 3px 10px rgba(0,0,0,.12)}
.rate b{display:block;font-size:.8rem;opacity:.9}
.rate span{font-size:1.15rem;font-weight:700}
.stNumberInput input{text-align:right}
</style>
""", unsafe_allow_html=True)


# ───────────── Giriş (şifrə) ─────────────
def gate():
    pw = secret("APP_PASSWORD", "7F2M5ZN")  # Secrets-də APP_PASSWORD yazsanız o keçərli olur
    if st.session_state.get("auth"):
        return
    st.markdown('<div class="hero"><h1>💼 Gündəlik Maliyyə Portalı</h1><p>Davam etmək üçün şifrəni daxil edin</p></div>',
                unsafe_allow_html=True)
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
    return rows, data["next_row"]


def save_day(d, values, rate_list):
    line = [values.get(c, 0.0) for c in range(2, LAST_COL + 1)]
    res = api({"action": "write", "date": d.isoformat(), "values": line, "rates": rate_list})
    load_rows.clear()
    return res


# ───────────── Məzənnə (AMB rəsmi XML) ─────────────
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_rates(d: dt.date):
    """Seçilən gün üçün AMB məzənnəsi; elan olunmayıbsa ən yaxın əvvəlki gün."""
    codes = {c[0] for c in CURRENCIES}
    for back in range(0, 7):
        day = d - dt.timedelta(days=back)
        try:
            r = requests.get(f"https://www.cbar.az/currencies/{day:%d.%m.%Y}.xml", timeout=10)
            if r.status_code != 200:
                continue
            out = {}
            for v in ET.fromstring(r.content).iter("Valute"):
                code = v.get("Code")
                if code in codes:
                    nominal = float(re.sub(r"[^\d]", "", v.findtext("Nominal") or "1") or 1)
                    out[code] = float(v.findtext("Value").replace(",", ".")) / nominal
            if codes <= set(out):
                return out, day
        except Exception:
            continue
    return None


# ═════════════ Səhifə ═════════════
gate()
st.markdown('<div class="hero"><h1>💼 Gündəlik Maliyyə Portalı</h1>'
            '<p>Günün sonunda məlumatları daxil edin, təsdiqləyin — cədvələ yazılsın</p></div>',
            unsafe_allow_html=True)

try:
    rows, next_row = load_rows()
except Exception as e:
    st.error("⚠️ Cədvələ qoşulmaq olmadı.")
    st.caption("Yoxlayın: ① SCRIPT_URL düzgün yapışdırılıb, ② Apps Script-də Who has access = Anyone, "
               "③ Code.gs-dəki TOKEN ilə eynidir, ④ fayl Google Sheets formatındadır.")
    st.code(str(e))
    st.stop()

today = dt.datetime.now(TZ).date()
d = st.date_input("📅 Tarix", value=today, format="DD.MM.YYYY")
iso = d.isoformat()

existing = rows.get(d)
ex_row, ex_vals, ex_rates = existing if existing else (None, None, None)
prev_dates = [x for x in rows if x < d]
prev_vals = rows[max(prev_dates)][1] if prev_dates else None

if existing:
    st.info(f"✏️ Bu tarix cədvəldə var (sətir {ex_row}). Dəyişib təsdiqləsəniz yalnız bu sətir yenilənəcək.")
elif prev_vals:
    st.success(f"🆕 Yeni gün — məbləğlər {max(prev_dates):%d.%m.%Y} tarixindən köçürülüb, dəyişənləri düzəldin.")
else:
    st.success("🆕 Yeni gün — məlumatları daxil edin.")

# ── Məzənnələr
st.markdown("#### 💱 Günün məzənnəsi")
cards = st.container()
fetched = fetch_rates(d)
rates, from_sheet = {}, False
for i, (code, sym, color, col) in enumerate(CURRENCIES):
    base = None
    if ex_rates and i < len(ex_rates) and isinstance(ex_rates[i], (int, float)) and ex_rates[i] > 0:
        base, from_sheet = float(ex_rates[i]), True          # həmin gün saxlanmış məzənnə
    elif ex_vals and AZN_MODE == "rate":
        v = ex_vals[col]  # \AZN sütununun indeksi (0-əsaslı)
        if isinstance(v, (int, float)) and v > 0:
            base, from_sheet = float(v), True
    if base is None and fetched:
        base = fetched[0][code]
    rates[code] = base or 0.0

with st.expander("✏️ Məzənnəni əl ilə düzəlt"):
    for code, sym, color, col in CURRENCIES:
        rates[code] = st.number_input(f"{code} → AZN", value=rates[code], min_value=0.0,
                                      step=0.0001, format="%.4f", key=f"rate_{code}_{iso}")
if from_sheet:
    st.caption("Mənbə: bu gün üçün cədvəldə saxlanmış məzənnə.")
elif fetched:
    extra = "" if fetched[1] == d else " (seçilən gün üçün hələ elan olunmayıb, ən yaxın tarix göstərilir)"
    st.caption(f"Mənbə: Azərbaycan Mərkəzi Bankı (cbar.az) · {fetched[1]:%d.%m.%Y}{extra}")
else:
    st.warning("Məzənnə avtomatik alınmadı — yuxarıdakı xanadan əl ilə yazın.")

cards.markdown(
    '<div class="rate-grid">' + "".join(
        f'<div class="rate" style="background:{color}"><b>{code}</b><span>{rates[code]:.4f} ₼</span></div>'
        for code, sym, color, col in CURRENCIES) + '</div>', unsafe_allow_html=True)


def default(col):
    src = ex_vals or prev_vals
    v = src[col - 1] if src else None
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


values = {}
st.markdown("#### 🏦 Hesablar")
for title, color, fields in SECTIONS:
    with st.container(border=True):
        st.markdown(f'<span class="chip" style="background:{color}">{title}</span>', unsafe_allow_html=True)
        cols = st.columns(2 if len(fields) > 1 else 1)
        for i, (label, col) in enumerate(fields):
            values[col] = cols[i % len(cols)].number_input(
                label, value=default(col), step=0.01, format="%.2f", key=f"f{col}_{iso}")

st.markdown("#### 🌍 Xarici vəsait")
st.caption("Məbləği yazın — AZN qarşılığı həmin günün məzənnəsi ilə hesablanıb cədvəlin \\AZN sütununa avtomatik yazılacaq.")
total_azn = 0.0
for code, sym, color, col in CURRENCIES:
    with st.container(border=True):
        st.markdown(f'<span class="chip" style="background:{color}">{code} · {rates[code]:.4f} ₼</span>',
                    unsafe_allow_html=True)
        c1, c2 = st.columns([3, 2])
        amt = c1.number_input(f"{code} məbləği", value=default(col), step=0.01, format="%.2f",
                              key=f"f{col}_{iso}")
        c2.metric("≈ AZN", f"{amt * rates[code]:,.2f} ₼")
        values[col] = amt
        values[col + 1] = rates[code] if AZN_MODE == "rate" else round(amt * rates[code], 2)
        total_azn += amt * rates[code]

st.markdown(f'<div class="hero" style="padding:12px;margin-top:8px"><p style="margin:0">Xarici vəsaitin cəmi</p>'
            f'<h1 style="font-size:1.4rem">≈ {total_azn:,.2f} ₼</h1></div>', unsafe_allow_html=True)

# ── Yoxla → Təsdiqlə
st.write("")
if st.button("🔍 Yoxla və təsdiqə göndər", type="primary", use_container_width=True):
    st.session_state["pending"] = {"date": d, "values": dict(values),
                                   "rates": [rates[c[0]] for c in CURRENCIES]}

pend = st.session_state.get("pending")
if pend and pend["date"] == d:
    st.markdown("#### ✅ Təsdiq")
    table = []
    for title, color, fields in SECTIONS:
        for label, col in fields:
            table.append((f"{title} · {label}", f"{pend['values'][col]:,.2f}"))
    for code, sym, color, col in CURRENCIES:
        table.append((f"{code}", f"{pend['values'][col]:,.2f}"))
        table.append((f"{code}\\AZN", f"{pend['values'][col + 1]:,.4f}" if AZN_MODE == "rate"
                      else f"{pend['values'][col + 1]:,.2f}"))
    st.dataframe(pd.DataFrame(table, columns=["Sahə", "Dəyər"]), hide_index=True)
    target = ex_row or next_row
    st.caption(f"{d:%d.%m.%Y} → cədvəlin {target}-ci sətrinə "
               f"{'yenilənəcək' if existing else 'yeni yazılacaq'}.")
    b1, b2 = st.columns(2)
    if b1.button("✅ Təsdiqlə və Sheet-ə yaz", type="primary", use_container_width=True):
        try:
            save_day(d, pend["values"], pend["rates"])
            st.session_state.pop("pending", None)
            st.toast("Cədvələ yazıldı ✅")
            st.success(f"Yazıldı! {d:%d.%m.%Y} · sətir {target}")
            st.balloons()
        except Exception as e:
            st.error("Yazmaq alınmadı.")
            st.code(str(e))
    if b2.button("✖ Ləğv et", use_container_width=True):
        st.session_state.pop("pending", None)
        st.rerun()
