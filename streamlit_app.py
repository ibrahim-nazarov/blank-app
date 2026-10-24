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


def fmt_rate(x):
    return f"{x:.4f}" if x >= 0.1 else f"{x:.6f}"


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


# ═════════════ Səhifə ═════════════
gate()
st.markdown('<div class="hero"><h1>💼 Gündəlik Maliyyə Portalı</h1>'
            '<p>Günün sonunda məlumatları daxil edin, təsdiqləyin — cədvələ yazılsın</p></div>',
            unsafe_allow_html=True)

if st.session_state.get("flash"):
    st.success(st.session_state.pop("flash"))
    st.balloons()

try:
    rows, next_row = load_rows()
except Exception as e:
    st.error("⚠️ Cədvələ qoşulmaq olmadı.")
    st.caption("Yoxlayın: ① SCRIPT_URL düzgün yapışdırılıb, ② Apps Script-də Who has access = Anyone, "
               "③ Code.gs-dəki TOKEN ilə eynidir, ④ fayl Google Sheets formatındadır.")
    st.code(str(e))
    st.stop()

today = dt.datetime.now(TZ).date()
d = st.date_input("📅 Yazılacaq tarix", value=today, format="DD.MM.YYYY")
iso = d.isoformat()

existing = rows.get(d)
ex_row, ex_vals, ex_rates = existing if existing else (None, None, None)

# Yeni gün üçün: hansı günün məlumatları xanalarda göstərilsin (susmaya görə — ondan əvvəlki ən son gün)
base_date, base_vals = None, None
if not existing and rows:
    all_dates = sorted(rows, reverse=True)
    earlier = [x for x in all_dates if x < d]
    options = all_dates + [None]
    base_date = st.selectbox(
        "📋 Hansı günün məlumatları göstərilsin?", options,
        index=options.index(earlier[0]) if earlier else len(options) - 1,
        format_func=lambda x: "Boş (sıfırdan)" if x is None else f"{x:%d.%m.%Y}",
        key=f"base_{iso}")
    base_vals = rows[base_date][1] if base_date else None

# cədvəldəki məlumat dəyişəndə xanalar cədvəldən yenidən doldurulsun
sig = hashlib.md5(repr((ex_vals, ex_rates, base_date, None if ex_vals else base_vals)).encode()).hexdigest()[:6]

if existing:
    st.info(f"✏️ {d:%d.%m.%Y} cədvəldə var (sətir {ex_row}). Təsdiqləsəniz yalnız bu sətir yenilənəcək, "
            f"digər günlərə toxunulmayacaq.")
else:
    msg = f"🆕 {d:%d.%m.%Y} üçün cədvəlin ən altına (sətir {next_row}) yeni sətir yazılacaq."
    if base_date:
        msg += f" Aşağıda {base_date:%d.%m.%Y} məlumatları göstərilir — həmin gün olduğu kimi qalacaq."
    st.success(msg)
    if any(x > d for x in rows):
        st.caption("Qeyd: cədvəldə bu tarixdən sonrakı günlər də var; yeni sətir yenə də ən sona əlavə olunacaq.")

with st.expander(f"📋 Cədvəldə {len(rows)} tarix tapıldı"):
    if rows:
        st.dataframe(pd.DataFrame([{"Tarix": f"{k:%d.%m.%Y}", "Sətir": v[0]} for k, v in sorted(rows.items())]),
                     hide_index=True)
        st.caption(f"Axtarılan tarix: {d:%d.%m.%Y} → " + (f"tapıldı (sətir {ex_row})" if existing else "cədvəldə yoxdur"))
    else:
        st.write("Heç bir tarix oxunmadı — A sütununda (3-cü sətirdən) tarixlərin olduğunu yoxlayın.")
    if st.button("🔄 Cədvəli yenidən oxu"):
        load_rows.clear()
        st.rerun()

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
    if base is None and fetched["rates"]:
        base = fetched["rates"][code]
    rates[code] = base or 0.0

with st.expander("✏️ Məzənnəni əl ilə düzəlt"):
    for code, sym, color, col in CURRENCIES:
        rates[code] = st.number_input(f"{code} → AZN", value=rates[code], min_value=0.0,
                                      step=0.0001, format="%.6f", key=f"rate_{code}_{iso}_{sig}_{rates[code]:.6f}")
if from_sheet:
    st.caption("Mənbə: bu gün üçün cədvəldə saxlanmış məzənnə.")
elif fetched["rates"]:
    extra = "" if fetched["day"] == d else " (seçilən gün üçün elan olunmayıb, ən yaxın tarix göstərilir)"
    st.caption(f"Mənbə: {fetched['source']} · {fetched['day']:%d.%m.%Y}{extra}")
else:
    st.warning("Məzənnə avtomatik alınmadı — yuxarıdakı xanadan əl ilə yazın.")
    with st.expander("🔧 Texniki detallar"):
        st.code("\n".join(fetched["errors"]))
    if st.button("🔄 Yenidən yoxla"):
        fetch_cached.clear()
        st.rerun()

cards.markdown(
    '<div class="rate-grid">' + "".join(
        f'<div class="rate" style="background:{color}"><b>{code}</b><span>{fmt_rate(rates[code])} ₼</span></div>'
        for code, sym, color, col in CURRENCIES) + '</div>', unsafe_allow_html=True)


def default(col):
    src = ex_vals or base_vals
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
                label, value=default(col), step=1.0, format="%.2f", key=f"f{col}_{iso}_{sig}")

st.markdown("#### 🌍 Xarici vəsait")
st.caption("Məbləği yazın — AZN qarşılığı həmin günün məzənnəsi ilə hesablanıb cədvəlin \\AZN sütununa avtomatik yazılacaq.")
total_azn = 0.0
for code, sym, color, col in CURRENCIES:
    with st.container(border=True):
        st.markdown(f'<span class="chip" style="background:{color}">{code} · {fmt_rate(rates[code])} ₼</span>',
                    unsafe_allow_html=True)
        c1, c2 = st.columns([3, 2])
        amt = c1.number_input(f"{code} məbləği", value=default(col), step=1.0, format="%.2f",
                              key=f"f{col}_{iso}_{sig}")
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
cur_rates = [rates[c[0]] for c in CURRENCIES]
if pend and pend["date"] == d and pend["values"] == values and pend["rates"] == cur_rates:
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
    ok = True
    if existing and d < today:
        st.warning(f"⚠️ {d:%d.%m.%Y} köhnə gündür və cədvəldə artıq var. Təsdiqləsəniz həmin günün sətri dəyişəcək.")
        ok = st.checkbox("Köhnə günün məlumatını dəyişdirməyə razıyam", key=f"allow_{iso}")
    b1, b2 = st.columns(2)
    saved = False
    if b1.button("✅ Təsdiqlə və Sheet-ə yaz", type="primary", use_container_width=True, disabled=not ok):
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
    if b2.button("✖ Ləğv et", use_container_width=True):
        st.session_state.pop("pending", None)
        st.rerun()
