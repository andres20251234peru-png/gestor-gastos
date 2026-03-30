# ============================================================
# GESTOR DE GASTOS v4.0
# Frontend: HTML/CSS/JS puro via st.components
# Backend:  Python + Google Sheets
# ============================================================

import streamlit as st
import streamlit.components.v1 as components
import datetime as dt
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import json
import pathlib
import uuid
import io
import traceback
from dotenv import load_dotenv

# ============================================================
# 1) CONFIG
# ============================================================
st.set_page_config(
    page_title="Gastos · Andrés",
    page_icon="💸",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# Ocultar UI de Streamlit completamente
st.markdown("""
<style>
#MainMenu,header,footer,
div[data-testid="stToolbar"],
div[data-testid="stDecoration"],
div[data-testid="stStatusWidget"],
div[data-testid="stAppViewBlockContainer"] > div:first-child {
  display:none!important;
}
.block-container {
  padding:0!important; max-width:100%!important;
}
.stApp { background:#040404!important; }
</style>
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Gastos">
<meta name="theme-color" content="#040404">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
""", unsafe_allow_html=True)

env_path = pathlib.Path(".") / ".env"
if not env_path.exists():
    env_path = pathlib.Path(".") / ".env.local"
load_dotenv(dotenv_path=env_path)

SHEET_NAME   = "Gastos_Diarios"
BUDGET_SHEET = "Presupuesto"

MESES_ORD = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
             "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
DIAS_ORD  = ["LUNES","MARTES","MIÉRCOLES","JUEVES","VIERNES","SÁBADO","DOMINGO"]
TZ_OFFSET = dt.timezone(dt.timedelta(hours=-5))

CATEGORIES = {
    "Alimentación":      ("🍽️", "#00E054"),
    "Transporte":        ("🚗", "#00CFFF"),
    "Salud":             ("💊", "#FFB800"),
    "Trabajo":           ("💼", "#FF5555"),
    "Ocio":              ("🎵", "#D0D0D0"),
    "Casa":              ("🏠", "#A259FF"),
    "Inversión":         ("📈", "#4A90E2"),
    "Pareja":            ("❤️", "#FF69B4"),
    "Estudios":          ("📚", "#F5A623"),
    "Viaje":             ("✈️", "#50E3C2"),
    "Frutas":            ("🍎", "#7ED321"),
    "Golosinas":         ("🍬", "#FF8AD8"),
    "Compras Generales": ("🛒", "#B8E986"),
    "Otros":             ("📦", "#888888"),
}
VALID_CATS = list(CATEGORIES.keys())
CAT_ALIASES = {"Comida": "Alimentación"}

# ============================================================
# 2) SESSION STATE
# ============================================================
_now = dt.datetime.now(TZ_OFFSET)
_DEFAULTS = {
    "view":         "main",
    "sel_year":     _now.year,
    "sel_month":    MESES_ORD[_now.month - 1],
    "sort_by":      "fecha",
    "sort_asc":     False,
    "action":       None,   # pending action from JS
    "action_data":  None,
    "toast_msg":    None,
    "show_success": False,
    "last_saved":   None,
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ============================================================
# 3) GOOGLE SHEETS — BACKEND
# ============================================================
@st.cache_resource
def get_client():
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets",
                 "https://www.googleapis.com/auth/drive"]
        info  = json.loads(st.secrets["GCP_SERVICE_ACCOUNT"])
        creds = Credentials.from_service_account_info(info, scopes=scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"❌ Error conectando con Google Sheets: {e}")
        return None

def normalize_mes(m):
    if not isinstance(m, str): return None
    return {k.lower(): k for k in MESES_ORD}.get(m.strip().lower(), m.strip().capitalize())

def normalize_cat(c):
    c = str(c).strip()
    return CAT_ALIASES.get(c, c if c in VALID_CATS else "Otros")

@st.cache_data(ttl=180, show_spinner=False)
def load_data() -> pd.DataFrame:
    client = get_client()
    if not client: return pd.DataFrame()
    try:
        sheet = client.open(SHEET_NAME).sheet1
        df    = pd.DataFrame(sheet.get_all_records())
        if df.empty: return df
        cu = {c.strip().upper(): c for c in df.columns}
        fcol = cu.get("FECHA")
        df["FECHA"] = pd.to_datetime(df[fcol], errors="coerce", dayfirst=True) if fcol else pd.NaT
        df["MES"]   = (df[cu["MES"]].apply(normalize_mes) if "MES" in cu
                       else df["FECHA"].dt.month.map(lambda x: MESES_ORD[x-1] if pd.notna(x) else None))
        df["AÑO"]   = (pd.to_numeric(df[cu["AÑO"]], errors="coerce").fillna(0).astype(int) if "AÑO" in cu
                       else df["FECHA"].dt.year.fillna(0).astype(int))
        ccat = cu.get("CATEGORÍA") or cu.get("CATEGORIA")
        df["CATEGORÍA"]   = df[ccat].apply(normalize_cat) if ccat else "Otros"
        cdesc = cu.get("DESCRIPCION") or cu.get("DESCRIPCIÓN")
        df["DESCRIPCION"] = df[cdesc].astype(str).str.strip() if cdesc else ""
        if "MONTO" in cu:
            df["MONTO"] = pd.to_numeric(
                df[cu["MONTO"]].astype(str).str.replace(",","",regex=False),
                errors="coerce").fillna(0.0)
        else:
            df["MONTO"] = 0.0
        df["ID"] = (df[cu["ID"]].astype(str).str.strip() if "ID" in cu
                    else [f"legacy_{i}" for i in range(len(df))])
        df = df[(df["AÑO"] > 0) & (df["MES"].notna()) & (df["MONTO"] > 0)]
        return df.reset_index(drop=True)
    except Exception:
        return pd.DataFrame()

def save_to_sheet(data: dict):
    client = get_client()
    if not client: return False, "Sin credenciales."
    try:
        sheet    = client.open(SHEET_NAME).sheet1
        mes_name = MESES_ORD[data["date"].month - 1]
        gasto_id = str(uuid.uuid4())[:8]
        headers  = sheet.row_values(1)
        if "ID" not in headers:
            sheet.update_cell(1, len(headers)+1, "ID")
        sheet.append_row([
            data["date"].strftime("%d/%m/%Y"), mes_name,
            int(data["date"].year), data["category"],
            data["description"], float(data["amount"]), gasto_id,
        ])
        load_data.clear()
        return True, gasto_id
    except Exception as e:
        return False, str(e)

def delete_from_sheet(gasto_id: str):
    client = get_client()
    if not client: return False, "Sin credenciales."
    try:
        sheet   = client.open(SHEET_NAME).sheet1
        values  = sheet.get_all_values()
        headers = [h.strip().upper() for h in values[0]]
        id_col  = next((i for i,h in enumerate(headers) if h=="ID"), None)
        if id_col is None: return False, "Columna ID no encontrada."
        row_to_delete = next(
            (i+2 for i,row in enumerate(values[1:])
             if len(row)>id_col and str(row[id_col]).strip()==gasto_id), None)
        if row_to_delete is None: return False, f"ID '{gasto_id}' no encontrado."
        sheet.delete_rows(row_to_delete)
        load_data.clear()
        return True, "OK"
    except Exception as e:
        return False, str(e)

@st.cache_data(ttl=300, show_spinner=False)
def load_budgets() -> dict:
    client = get_client()
    if not client: return {}
    try:
        ss = client.open(SHEET_NAME)
        try: ws = ss.worksheet(BUDGET_SHEET)
        except Exception:
            ws = ss.add_worksheet(title=BUDGET_SHEET, rows=50, cols=4)
            ws.update("A1:D1", [["AÑO","MES","PRESUPUESTO","UPDATED"]])
            return {}
        out = {}
        for r in ws.get_all_records():
            try:
                anio = int(r.get("AÑO",0)); mes = str(r.get("MES","")).strip()
                val  = float(r.get("PRESUPUESTO",0))
                if anio > 0 and mes and val > 0: out[(anio,mes)] = val
            except: pass
        return out
    except: return {}

def save_budget(anio, mes, valor):
    client = get_client()
    if not client: return False
    try:
        ss = client.open(SHEET_NAME)
        try: ws = ss.worksheet(BUDGET_SHEET)
        except Exception:
            ws = ss.add_worksheet(title=BUDGET_SHEET, rows=50, cols=4)
            ws.update("A1:D1", [["AÑO","MES","PRESUPUESTO","UPDATED"]])
        rows = ws.get_all_values()
        for i, row in enumerate(rows[1:], start=2):
            if len(row)>=3:
                try:
                    if int(row[0])==anio and row[1].strip()==mes:
                        ws.update(f"C{i}:D{i}", [[valor, dt.datetime.now().strftime("%Y-%m-%d %H:%M")]])
                        load_budgets.clear(); return True
                except: pass
        ws.append_row([anio, mes, valor, dt.datetime.now().strftime("%Y-%m-%d %H:%M")])
        load_budgets.clear(); return True
    except: return False

# ============================================================
# 4) DATA HELPERS
# ============================================================
def now_peru(): return dt.datetime.now(TZ_OFFSET)

def filter_data(df, mes, anio):
    if df.empty: return df
    mask = df["AÑO"] == int(anio)
    if mes: mask &= df["MES"] == mes
    return df[mask].copy()

def days_streak(df):
    if df.empty: return 0
    today = now_peru().date()
    dates = set(df["FECHA"].dropna().dt.date.unique())
    streak, d = 0, today
    while d in dates:
        streak += 1; d -= dt.timedelta(days=1)
    return streak

def build_payload(df, mes, anio, budgets):
    """Construye el JSON que el frontend necesita para renderizar."""
    dfm   = filter_data(df, mes, anio)
    total = float(dfm["MONTO"].sum()) if not dfm.empty else 0.0
    presup = budgets.get((anio, mes), 0.0)

    # Stats
    now_p = now_peru()
    avg_day = total / max(now_p.day, 1) if total > 0 else 0
    streak  = days_streak(df)

    # Categorías agrupadas
    cats = []
    if not dfm.empty:
        grp = (dfm.groupby("CATEGORÍA")["MONTO"].sum()
                  .reset_index().sort_values("MONTO", ascending=False))
        grp["PCT"] = grp["MONTO"] / total * 100 if total > 0 else 0
        for _, r in grp.iterrows():
            cat  = r["CATEGORÍA"]
            icon, color = CATEGORIES.get(cat, ("📦","#888"))
            cats.append({
                "cat": cat, "icon": icon, "color": color,
                "amt": round(float(r["MONTO"]),2),
                "pct": round(float(r["PCT"]),1),
            })

    # Movimientos del mes (ordenados)
    movs = []
    if not dfm.empty:
        col = "FECHA" if st.session_state.sort_by == "fecha" else "MONTO"
        for _, d in dfm.sort_values(col, ascending=st.session_state.sort_asc).iterrows():
            cat  = d["CATEGORÍA"]
            icon, color = CATEGORIES.get(cat, ("📦","#888"))
            fecha_str = d["FECHA"].strftime("%d/%m") if pd.notna(d["FECHA"]) else ""
            movs.append({
                "id":    str(d.get("ID","")),
                "desc":  str(d.get("DESCRIPCION","")).strip() or cat,
                "cat":   cat, "icon": icon, "color": color,
                "amt":   round(float(d.get("MONTO",0)),2),
                "fecha": fecha_str,
                "legacy": str(d.get("ID","")).startswith("legacy_"),
            })

    # Histórico mensual del año
    hist = []
    df_year = filter_data(df, None, anio)
    if not df_year.empty:
        for m_idx, m_name in enumerate(MESES_ORD):
            dfm2 = df_year[df_year["MES"] == m_name]
            hist.append({"mes": m_name[:3].upper(), "total": round(float(dfm2["MONTO"].sum()),2)})

    return {
        "mes":    mes,
        "anio":   anio,
        "total":  round(total, 2),
        "presup": round(presup, 2),
        "avg_day": round(avg_day, 2),
        "proj":   round(avg_day * 30, 2),
        "n_tx":   len(dfm),
        "streak": streak,
        "cats":   cats,
        "movs":   movs,
        "hist":   hist,
        "meses":  MESES_ORD,
        "categories": [
            {"key": k, "icon": v[0], "color": v[1], "short": k.split()[0][:8]}
            for k, v in CATEGORIES.items()
        ],
        "now_day":  now_p.day,
        "now_dow":  DIAS_ORD[now_p.weekday()],
        "now_mes":  MESES_ORD[now_p.month-1].upper(),
        "sort_by":  st.session_state.sort_by,
        "sort_asc": st.session_state.sort_asc,
        "view":     st.session_state.view,
        "show_success": st.session_state.show_success,
        "last_saved":   st.session_state.last_saved,
        "toast":    st.session_state.toast_msg,
    }

# ============================================================
# 5) HANDLE ACTIONS (JS → Python via query_params)
# ============================================================
def handle_actions():
    params = st.query_params
    action = params.get("action", "")
    if not action:
        return

    # Clear params immediately
    st.query_params.clear()

    if action == "prev_month":
        idx = MESES_ORD.index(st.session_state.sel_month)
        if idx == 0:
            st.session_state.sel_month = MESES_ORD[11]; st.session_state.sel_year -= 1
        else:
            st.session_state.sel_month = MESES_ORD[idx-1]

    elif action == "next_month":
        idx = MESES_ORD.index(st.session_state.sel_month)
        if idx == 11:
            st.session_state.sel_month = MESES_ORD[0]; st.session_state.sel_year += 1
        else:
            st.session_state.sel_month = MESES_ORD[idx+1]

    elif action == "set_month":
        m = params.get("m",""); y = params.get("y","")
        if m in MESES_ORD: st.session_state.sel_month = m
        try: st.session_state.sel_year = int(y)
        except: pass

    elif action == "goto_add":
        st.session_state.view = "add"
        st.session_state.show_success = False

    elif action == "goto_main":
        st.session_state.view = "main"

    elif action == "sort":
        by = params.get("by","fecha")
        if st.session_state.sort_by == by:
            st.session_state.sort_asc = not st.session_state.sort_asc
        else:
            st.session_state.sort_by = by; st.session_state.sort_asc = False

    elif action == "save_expense":
        try:
            amt   = float(params.get("amt","0"))
            cat   = params.get("cat","Otros")
            desc  = params.get("desc","") or cat
            fecha_str = params.get("fecha","")
            if fecha_str:
                fecha = dt.datetime.strptime(fecha_str, "%Y-%m-%d")
            else:
                fecha = now_peru().replace(tzinfo=None)
            ok, msg = save_to_sheet({"date": fecha, "amount": amt, "category": cat, "description": desc})
            if ok:
                st.session_state.show_success = True
                st.session_state.last_saved   = {"cat": cat, "amt": amt, "desc": desc,
                                                   "icon": CATEGORIES.get(cat,("📦","#888"))[0]}
                st.session_state.view = "main"
                st.session_state.toast_msg = f"Guardado ✓"
            else:
                st.session_state.toast_msg = f"Error: {msg}"
        except Exception as e:
            st.session_state.toast_msg = f"Error: {e}"

    elif action == "delete":
        gid = params.get("id","")
        ok, msg = delete_from_sheet(gid)
        st.session_state.toast_msg = "Eliminado 🗑️" if ok else f"Error: {msg}"

    elif action == "save_budget":
        try:
            mes = params.get("mes", st.session_state.sel_month)
            anio = int(params.get("anio", st.session_state.sel_year))
            val  = float(params.get("val","0"))
            ok   = save_budget(anio, mes, val)
            st.session_state.toast_msg = f"Presupuesto S/ {val:,.0f} guardado 🎯" if ok else "Error guardando"
        except Exception as e:
            st.session_state.toast_msg = f"Error: {e}"

    elif action == "clear_toast":
        st.session_state.toast_msg = None

    elif action == "clear_success":
        st.session_state.show_success = False
        st.session_state.last_saved   = None

    st.rerun()

# ============================================================
# 6) HTML FRONTEND
# ============================================================
def render_app(payload: dict):
    data_json = json.dumps(payload, ensure_ascii=False, default=str)
    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Mono:wght@400;500&display=swap">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent;}}
:root{{
  --bg:       #040404;
  --s1:       #0c0c0c;
  --s2:       #141414;
  --s3:       #1c1c1c;
  --border:   #1e1e1e;
  --border2:  #282828;
  --green:    #00E054;
  --green-dim:#00a83f;
  --text:     #e8e8e8;
  --muted:    #555;
  --muted2:   #333;
  --danger:   #e84040;
  --warn:     #c99500;
  --font:     'Syne', sans-serif;
  --mono:     'DM Mono', monospace;
  --r-sm:     10px;
  --r-md:     16px;
  --r-lg:     22px;
  --r-xl:     28px;
}}
html,body{{background:var(--bg);color:var(--text);font-family:var(--font);
  min-height:100vh;overflow-x:hidden;-webkit-font-smoothing:antialiased;}}
#app{{max-width:480px;margin:0 auto;padding:0 16px;
  padding-top:env(safe-area-inset-top);
  padding-bottom:calc(env(safe-area-inset-bottom) + 90px);
  min-height:100vh;}}

/* ── BUTTONS ── */
.btn{{display:flex;align-items:center;justify-content:center;gap:8px;
  border:none;border-radius:var(--r-md);font-family:var(--font);
  font-weight:700;cursor:pointer;transition:all .13s ease;
  -webkit-appearance:none;outline:none;}}
.btn-primary{{background:var(--green);color:#000;font-size:.95rem;
  height:52px;width:100%;letter-spacing:-.1px;}}
.btn-primary:active{{transform:scale(.97);filter:brightness(.92);}}
.btn-secondary{{background:var(--s1);border:1px solid var(--border);
  color:var(--muted);font-size:.82rem;height:40px;}}
.btn-secondary:active{{background:var(--s2);color:var(--text);}}
.btn-icon{{background:var(--s1);border:1px solid var(--border);
  color:var(--muted);width:40px;height:40px;border-radius:var(--r-sm);
  flex-shrink:0;font-size:1rem;}}
.btn-icon:active{{background:var(--s2);}}
.btn-danger{{background:rgba(232,64,64,.1);border:1px solid rgba(232,64,64,.25);
  color:var(--danger);width:36px;height:36px;border-radius:var(--r-sm);
  flex-shrink:0;font-size:.85rem;}}

/* ── BADGES / CHIPS ── */
.badge{{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;
  border-radius:999px;background:var(--s1);border:1px solid var(--border);
  color:var(--muted2);font-size:.65rem;font-weight:600;letter-spacing:1.5px;text-transform:uppercase;}}
.dot{{width:5px;height:5px;border-radius:50%;background:var(--green);
  box-shadow:0 0 6px var(--green);flex-shrink:0;}}
.section-label{{color:var(--muted2);font-size:.6rem;font-weight:600;
  letter-spacing:3px;text-transform:uppercase;margin:20px 0 8px;}}

/* ── CARD HERO ── */
.card-hero{{background:linear-gradient(160deg,#0f0f0f 0%,#0a0a0a 100%);
  border:1px solid var(--border);
  border-radius:var(--r-xl);padding:30px 22px 24px;
  position:relative;overflow:hidden;margin:8px 0;
  display:flex;flex-direction:column;align-items:center;
  box-shadow:0 20px 40px rgba(0,0,0,.5);}}
.card-hero::before{{content:'';position:absolute;top:0;left:50%;
  transform:translateX(-50%);width:40%;height:1px;
  background:linear-gradient(90deg,transparent,rgba(0,224,84,.2),transparent);}}
.card-title{{color:var(--muted2);font-size:.62rem;font-weight:600;
  letter-spacing:3px;text-transform:uppercase;margin-bottom:10px;}}
.card-amount{{display:flex;align-items:baseline;gap:6px;}}
.card-currency{{font-size:1.1rem;font-weight:600;color:var(--muted2);font-family:var(--mono);}}
.card-num{{font-size:clamp(3rem,11vw,4.5rem);font-weight:800;color:#fff;
  font-family:var(--mono);letter-spacing:-3px;line-height:1;text-shadow:0 0 40px rgba(255,255,255,.08);}}
.card-sub{{color:var(--muted2);font-size:.72rem;font-weight:500;margin-top:8px;}}
.card-sub b{{color:#2d7a50;font-weight:700;}}

/* ── BUDGET BAR ── */
.budget-wrap{{margin-top:10px;width:100%;}}
.budget-bar-bg{{width:100%;height:3px;background:var(--s3);border-radius:99px;overflow:hidden;}}
.budget-bar-fill{{height:100%;border-radius:99px;transition:width .8s cubic-bezier(.4,0,.2,1);}}
.budget-meta{{display:flex;justify-content:space-between;margin-top:5px;}}
.budget-meta span{{font-size:.68rem;font-weight:500;color:var(--muted2);}}
.budget-meta b{{font-weight:600;}}

/* ── STAT PILLS ── */
.stat-grid{{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px;}}
.stat-pill{{background:var(--s1);border:1px solid var(--border);
  border-radius:var(--r-lg);padding:13px 14px 11px;display:flex;flex-direction:column;gap:5px;}}
.stat-lbl{{color:var(--muted2);font-size:.6rem;font-weight:600;letter-spacing:2px;text-transform:uppercase;}}
.stat-val{{color:#c8c8c8;font-size:1rem;font-weight:700;font-family:var(--mono);letter-spacing:-.4px;}}
.stat-val.green{{color:var(--green);font-size:1.1rem;}}

/* ── BUDGET ALERT ── */
.budget-alert{{border-radius:var(--r-sm);padding:10px 13px;margin-top:9px;
  font-weight:600;font-size:.8rem;display:flex;align-items:center;gap:8px;
  animation:fadeUp .25s ease;}}
.budget-alert.warn{{background:rgba(200,140,0,.06);border:1px solid rgba(200,140,0,.15);color:var(--warn);}}
.budget-alert.danger{{background:rgba(200,50,50,.06);border:1px solid rgba(200,50,50,.18);color:var(--danger);}}

/* ── MONTH NAV ── */
.month-nav{{display:flex;align-items:center;gap:8px;margin:8px 0 6px;}}
.month-nav-label{{flex:1;text-align:center;font-size:.95rem;font-weight:700;color:var(--text);}}
.month-nav .btn-icon{{font-size:1.1rem;}}

/* ── SEARCH ── */
.search-wrap{{position:relative;margin:4px 0 8px;}}
.search-input{{width:100%;background:var(--s1);border:1px solid var(--border);
  border-radius:var(--r-md);padding:11px 16px 11px 38px;
  color:var(--text);font-size:.88rem;font-family:var(--font);outline:none;
  transition:border-color .15s;}}
.search-input:focus{{border-color:rgba(0,224,84,.3);}}
.search-input::placeholder{{color:var(--muted2);}}
.search-icon{{position:absolute;left:13px;top:50%;transform:translateY(-50%);
  color:var(--muted2);font-size:.9rem;pointer-events:none;}}

/* ── TABS ── */
.tabs{{display:flex;gap:6px;margin:4px 0 12px;}}
.tab{{flex:1;height:38px;border-radius:var(--r-sm);font-size:.82rem;font-weight:700;
  cursor:pointer;border:1px solid var(--border);background:var(--s1);color:var(--muted);
  display:flex;align-items:center;justify-content:center;transition:all .12s;}}
.tab.active{{background:var(--green);color:#000;border-color:var(--green);}}
.tab:active{{transform:scale(.97);}}

/* ── SORT BAR ── */
.sort-bar{{display:flex;align-items:center;gap:8px;margin-bottom:8px;}}
.sort-lbl{{color:var(--muted2);font-size:.6rem;font-weight:600;letter-spacing:2px;text-transform:uppercase;}}
.sort-btn{{height:32px;padding:0 12px;border-radius:8px;font-size:.75rem;font-weight:700;
  cursor:pointer;border:1px solid var(--border);background:var(--s1);color:var(--muted);
  display:flex;align-items:center;gap:4px;transition:all .12s;}}
.sort-btn.active{{background:rgba(0,224,84,.1);border-color:rgba(0,224,84,.3);color:var(--green);}}
.sort-btn:active{{transform:scale(.96);}}

/* ── MOVIMIENTOS ── */
.mov-list{{display:flex;flex-direction:column;gap:5px;}}
.mov-item{{background:var(--s1);border:1px solid var(--border);border-radius:var(--r-md);
  padding:13px 14px;display:flex;align-items:center;gap:12px;
  transition:border-color .12s;}}
.mov-item:active{{border-color:var(--border2);background:var(--s2);}}
.mov-icon-wrap{{width:36px;height:36px;border-radius:10px;background:var(--s2);
  display:flex;align-items:center;justify-content:center;font-size:1.1rem;flex-shrink:0;}}
.mov-info{{flex:1;min-width:0;}}
.mov-name{{font-size:.88rem;font-weight:700;color:#ccc;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
.mov-sub{{font-size:.72rem;color:var(--muted2);margin-top:2px;}}
.mov-right{{display:flex;flex-direction:column;align-items:flex-end;gap:3px;}}
.mov-amt{{font-size:.9rem;font-weight:700;font-family:var(--mono);letter-spacing:-.3px;}}
.mov-date{{font-size:.65rem;color:var(--muted2);}}

/* ── DONUT ── */
.donut-wrap{{display:flex;align-items:center;gap:16px;margin:8px 0 16px;}}
.donut-legend{{flex:1;display:flex;flex-direction:column;gap:0;}}
.legend-row{{display:flex;align-items:center;justify-content:space-between;
  padding:8px 0;border-bottom:1px solid var(--border);}}
.legend-row:last-child{{border-bottom:none;}}
.legend-left{{display:flex;align-items:center;gap:8px;}}
.legend-dot{{width:6px;height:6px;border-radius:50%;flex-shrink:0;}}
.legend-name{{font-size:.82rem;font-weight:600;color:#888;}}
.legend-pct{{font-size:.78rem;font-weight:600;color:var(--muted2);font-family:var(--mono);}}

/* ── EXPANDER (categoría detalle) ── */
.cat-expander{{background:var(--s1);border:1px solid var(--border);
  border-radius:var(--r-lg);overflow:hidden;margin-bottom:5px;}}
.cat-header{{display:flex;align-items:center;gap:12px;padding:14px 16px;cursor:pointer;
  transition:background .12s;}}
.cat-header:active{{background:var(--s2);}}
.cat-icon{{width:34px;height:34px;border-radius:9px;background:var(--s2);
  display:flex;align-items:center;justify-content:center;font-size:1rem;flex-shrink:0;}}
.cat-info{{flex:1;}}
.cat-name{{font-size:.88rem;font-weight:700;color:#bbb;}}
.cat-sub{{font-size:.68rem;color:var(--muted2);margin-top:1px;}}
.cat-right{{display:flex;flex-direction:column;align-items:flex-end;gap:2px;}}
.cat-amt{{font-size:.95rem;font-weight:700;font-family:var(--mono);color:#ddd;letter-spacing:-.5px;}}
.cat-pct{{font-size:.7rem;font-weight:700;}}
.cat-chevron{{color:var(--muted2);font-size:.75rem;transition:transform .2s;margin-left:4px;}}
.cat-chevron.open{{transform:rotate(90deg);}}
.cat-bar-bg{{height:2px;background:var(--s3);margin:0 16px;border-radius:99px;overflow:hidden;}}
.cat-bar-fill{{height:100%;border-radius:99px;}}
.cat-body{{padding:0 14px 12px;display:flex;flex-direction:column;gap:5px;}}
.cat-body.hidden{{display:none;}}

/* ── HIST CHART ── */
.hist-wrap{{background:var(--s1);border:1px solid var(--border);border-radius:var(--r-lg);padding:16px 14px 12px;margin:4px 0 12px;}}
.hist-bars{{display:flex;align-items:flex-end;gap:5px;height:100px;margin-bottom:6px;}}
.hist-bar-wrap{{flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;}}
.hist-bar{{width:100%;border-radius:5px 5px 0 0;transition:height .5s cubic-bezier(.4,0,.2,1);min-height:3px;}}
.hist-bar.current{{background:var(--green);box-shadow:0 0 10px rgba(0,224,84,.3);}}
.hist-bar.has-val{{background:var(--s3);}}
.hist-bar.empty{{background:transparent;min-height:0!important;}}
.hist-label{{font-size:.52rem;color:var(--muted2);font-weight:600;letter-spacing:.3px;text-transform:uppercase;}}
.hist-label.current{{color:var(--green);}}

/* ── FORM NUEVO GASTO ── */
.form-header{{display:flex;align-items:center;gap:12px;padding:12px 0 16px;}}
.form-title{{flex:1;text-align:center;font-size:.9rem;font-weight:700;color:var(--muted);}}
.amount-display{{background:var(--s1);border:1px solid var(--border);
  border-radius:var(--r-xl);padding:24px 20px 16px;text-align:center;
  margin-bottom:6px;position:relative;overflow:hidden;cursor:text;}}
.amount-display::before{{content:'';position:absolute;bottom:0;left:50%;transform:translateX(-50%);
  width:30%;height:1px;background:linear-gradient(90deg,transparent,rgba(0,224,84,.15),transparent);}}
.amount-field-lbl{{font-size:.6rem;font-weight:600;color:var(--muted2);
  letter-spacing:3px;text-transform:uppercase;margin-bottom:4px;}}
.amount-value{{font-size:clamp(2.8rem,11vw,4.5rem);font-weight:800;
  font-family:var(--mono);letter-spacing:-3px;color:#fff;line-height:1;
  min-height:1.2em;}}
.amount-value.zero{{color:var(--muted2);}}
.amount-unit{{font-size:.65rem;font-weight:600;color:var(--muted2);
  letter-spacing:2px;text-transform:uppercase;margin-top:6px;}}
.amount-input-hidden{{position:absolute;opacity:0;pointer-events:none;
  width:1px;height:1px;}}
.cat-grid{{display:grid;grid-template-columns:1fr 1fr;gap:7px;}}
.cat-chip{{background:var(--s1);border:1px solid var(--border2);
  border-radius:var(--r-md);padding:12px 10px;
  display:flex;align-items:center;justify-content:center;gap:7px;
  cursor:pointer;transition:all .12s;min-height:48px;}}
.cat-chip:active{{transform:scale(.96);}}
.cat-chip.selected{{background:rgba(0,224,84,.1);border-color:rgba(0,224,84,.3);}}
.cat-chip span.lbl{{font-size:.82rem;font-weight:700;color:var(--muted);transition:color .12s;}}
.cat-chip.selected span.lbl{{color:var(--green);}}
.cat-chip span.ico{{font-size:1.1rem;}}
.form-field{{margin-top:16px;}}
.form-field-lbl{{font-size:.6rem;font-weight:600;color:var(--muted2);
  letter-spacing:3px;text-transform:uppercase;text-align:center;margin-bottom:8px;}}
.form-input{{width:100%;background:var(--s1);border:1px solid var(--border);
  border-radius:var(--r-md);padding:13px 16px;color:var(--text);
  font-size:.9rem;font-family:var(--font);outline:none;
  transition:border-color .15s;}}
.form-input:focus{{border-color:rgba(0,224,84,.3);}}
.form-input::placeholder{{color:var(--muted2);}}
.form-actions{{display:flex;gap:8px;margin-top:20px;}}
.form-actions .btn-primary{{flex:2;}}
.form-actions .btn-secondary{{flex:1;}}

/* ── PREVIEW ── */
.preview-card{{background:var(--s1);border:1px solid var(--border);
  border-radius:var(--r-xl);padding:20px;margin:14px 0;}}
.preview-amount{{text-align:center;font-size:clamp(2.2rem,7vw,3rem);
  font-weight:800;font-family:var(--mono);letter-spacing:-2px;margin-bottom:18px;}}
.preview-row{{display:flex;justify-content:space-between;align-items:center;
  padding:9px 0;border-bottom:1px solid var(--border);}}
.preview-row:last-child{{border-bottom:none;}}
.preview-lbl{{font-size:.62rem;font-weight:600;color:var(--muted2);
  text-transform:uppercase;letter-spacing:1.5px;}}
.preview-val{{font-size:.86rem;font-weight:600;color:#888;}}

/* ── SUCCESS BANNER ── */
.success-banner{{background:#090e0b;border:1px solid #162018;
  border-radius:var(--r-lg);padding:14px 16px;
  display:flex;align-items:center;gap:12px;margin-bottom:12px;
  animation:fadeUp .35s ease;}}
.success-icon{{font-size:1.6rem;}}
.success-text .t{{font-weight:700;color:var(--green);font-size:.88rem;margin-bottom:2px;}}
.success-text .s{{font-size:.75rem;color:#1e4a2e;font-weight:500;}}

/* ── MONTH PICKER ── */
.month-picker{{background:var(--s1);border:1px solid var(--border);
  border-radius:var(--r-lg);padding:14px;margin-bottom:8px;
  animation:fadeUp .2s ease;}}
.year-nav{{display:flex;align-items:center;gap:8px;margin-bottom:10px;}}
.year-label{{flex:1;text-align:center;font-size:.9rem;font-weight:700;color:var(--text);}}
.month-grid-picker{{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;}}
.month-chip-picker{{height:36px;border-radius:8px;background:var(--s2);border:1px solid var(--border);
  color:var(--muted);font-size:.78rem;font-weight:700;cursor:pointer;
  display:flex;align-items:center;justify-content:center;transition:all .12s;}}
.month-chip-picker.active{{background:var(--green);color:#000;border-color:var(--green);}}
.month-chip-picker:active{{transform:scale(.95);}}

/* ── PRESUPUESTO FORM ── */
.budget-form{{background:var(--s1);border:1px solid var(--border);
  border-radius:var(--r-lg);padding:16px;margin-bottom:8px;
  animation:fadeUp .2s ease;}}
.budget-form-title{{font-size:.75rem;font-weight:700;color:#888;margin-bottom:10px;text-align:center;}}
.budget-input-row{{display:flex;gap:8px;align-items:center;}}
.budget-input{{flex:1;background:var(--s2);border:1px solid var(--border);
  border-radius:var(--r-sm);padding:10px 14px;color:#fff;font-size:1rem;
  font-family:var(--mono);font-weight:700;outline:none;text-align:center;
  transition:border-color .15s;}}
.budget-input:focus{{border-color:rgba(0,224,84,.3);}}
.budget-save-btn{{background:var(--green);color:#000;font-weight:700;
  height:42px;padding:0 16px;border:none;border-radius:var(--r-sm);
  font-size:.85rem;cursor:pointer;white-space:nowrap;transition:all .13s;}}
.budget-save-btn:active{{transform:scale(.97);}}

/* ── TOAST ── */
.toast{{position:fixed;bottom:calc(env(safe-area-inset-bottom)+16px);left:50%;
  transform:translateX(-50%);background:#111;border:1px solid var(--border2);
  border-radius:var(--r-md);padding:10px 18px;font-size:.82rem;font-weight:600;
  color:#ccc;box-shadow:0 8px 28px rgba(0,0,0,.6);z-index:999;
  animation:toastIn .3s ease;white-space:nowrap;}}
@keyframes toastIn{{from{{opacity:0;transform:translateX(-50%) translateY(12px);}}to{{opacity:1;transform:translateX(-50%) translateY(0);}}}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(6px);}}to{{opacity:1;transform:translateY(0);}}}}

/* ── EMPTY ── */
.empty{{text-align:center;padding:56px 24px;}}
.empty-icon{{font-size:2.8rem;opacity:.3;margin-bottom:12px;}}
.empty-title{{font-size:.95rem;font-weight:700;color:var(--muted2);margin-bottom:5px;}}
.empty-sub{{font-size:.8rem;color:var(--muted2);opacity:.5;}}
</style>
</head>
<body>
<div id="app"></div>
<script>
const D = {data_json};
let state = {{
  view:        D.view,
  chartMode:   'cats',
  showPicker:  false,
  showBudget:  false,
  expandedCat: null,
  search:      '',
  pickerYear:  D.anio,
  previewData: null,
  formData:    {{ amt:'0', cat:'Alimentación', desc:'', fecha: todayStr() }},
}};

function todayStr(){{
  const n = new Date(); const y = n.getFullYear();
  const m = String(n.getMonth()+1).padStart(2,'0');
  const d = String(n.getDate()).padStart(2,'0');
  return y+'-'+m+'-'+d;
}}

function nav(action, extra=''){{
  // Use hidden form with target="_top" to navigate the TOP page (Streamlit), not the iframe
  const f=document.createElement('form');
  f.method='GET';
  f.action='';
  f.target='_top';  // targets the Streamlit page, not this iframe
  const params={{'action':action}};
  if(extra){{
    extra.split('&').forEach(pair=>{{
      const [k,v]=pair.split('=');
      if(k)params[k]=decodeURIComponent(v||'');
    }});
  }}
  Object.entries(params).forEach(([k,v])=>{{
    const inp=document.createElement('input');
    inp.type='hidden'; inp.name=k; inp.value=v;
    f.appendChild(inp);
  }});
  document.body.appendChild(f);
  f.submit();
}}

function donut(cats, size=160){{
  if(!cats.length) return '';
  const r=52, cx=size/2, cy=size/2, circ=2*Math.PI*r;
  let circles='', offset=circ*0.25;
  cats.forEach(c=>{{
    const dash=c.pct/100*circ, gap=circ-dash;
    circles+=`<circle cx="${{cx}}" cy="${{cy}}" r="${{r}}" fill="none"
      stroke="${{c.color}}" stroke-width="22" stroke-opacity=".9"
      stroke-dasharray="${{dash.toFixed(2)}} ${{gap.toFixed(2)}}"
      stroke-dashoffset="${{-offset.toFixed(2)}}"
      transform="rotate(-90 ${{cx}} ${{cy}})"/>`;
    offset+=dash;
  }});
  const top=cats[0];
  return `<svg viewBox="0 0 ${{size}} ${{size}}" style="width:100%;display:block;">
    <circle cx="${{cx}}" cy="${{cy}}" r="${{r+13}}" fill="#080808"/>
    ${{circles}}
    <circle cx="${{cx}}" cy="${{cy}}" r="${{r-12}}" fill="#060606"/>
    <text x="${{cx}}" y="${{cy-8}}" text-anchor="middle" font-size="7.5"
      font-weight="700" fill="#555" font-family="Syne,sans-serif" letter-spacing="2">
      ${{top.cat.toUpperCase().slice(0,9)}}</text>
    <text x="${{cx}}" y="${{cy+16}}" text-anchor="middle" font-size="30"
      font-weight="800" fill="#f0f0f0" font-family="DM Mono,monospace">${{Math.round(top.pct)}}<tspan
      font-size="13" fill="${{top.color}}" font-weight="700">%</tspan></text>
  </svg>`;
}}

function histChart(hist){{
  const vals=hist.map(h=>h.total);
  const max=Math.max(...vals,1);
  const curMes=D.mes.slice(0,3).toUpperCase();
  const bars=hist.map((h,i)=>{{
    // Only bars with real data get height; empty months get 0
    const pct=h.total>0?Math.max(h.total/max*100,8):0;
    const isCur=h.mes===curMes;
    const cls=isCur?'current':h.total>0?'has-val':'empty';
    return `<div class="hist-bar-wrap">
      <div class="hist-bar ${{cls}}" style="height:${{pct}}%;"></div>
      <div class="hist-label ${{isCur?'current':''}}">${{h.mes}}</div>
    </div>`;
  }});
  return `<div class="hist-wrap"><div class="hist-bars">${{bars.join('')}}</div></div>`;
}}

function fmtAmt(n){{return 'S/ '+n.toLocaleString('es-PE',{{minimumFractionDigits:2,maximumFractionDigits:2}});}}

function renderMain(){{
  const movs=D.movs.filter(m=>{{
    if(!state.search) return true;
    const q=state.search.toLowerCase();
    return m.desc.toLowerCase().includes(q)||m.cat.toLowerCase().includes(q);
  }});
  const presupPct=D.presup>0?Math.min(D.total/D.presup*100,100):0;
  const presupColor=presupPct>=100?'var(--danger)':presupPct>=80?'var(--warn)':'var(--green)';

  // Success banner
  let successHtml='';
  if(D.show_success&&D.last_saved){{
    successHtml=`<div class="success-banner">
      <div class="success-icon">${{D.last_saved.icon}}</div>
      <div class="success-text">
        <div class="t">¡Gasto guardado!</div>
        <div class="s">${{D.last_saved.cat}} · ${{fmtAmt(D.last_saved.amt)}}</div>
      </div>
      <button class="btn-icon" onclick="nav('clear_success')" style="margin-left:auto;">✕</button>
    </div>`;
  }}

  // Month picker
  let pickerHtml='';
  if(state.showPicker){{
    const abbrs=['ENE','FEB','MAR','ABR','MAY','JUN','JUL','AGO','SEP','OCT','NOV','DIC'];
    const chips=abbrs.map((a,i)=>{{
      const full=D.meses[i];
      const isActive=full===D.mes&&state.pickerYear===D.anio;
      return `<div class="month-chip-picker ${{isActive?'active':''}}"
        onclick="nav('set_month','m=${{encodeURIComponent(full)}}&y=${{state.pickerYear}}')">
        ${{a}}</div>`;
    }}).join('');
    pickerHtml=`<div class="month-picker">
      <div class="year-nav">
        <button class="btn-icon" onclick="state.pickerYear--;render()">‹</button>
        <div class="year-label">${{state.pickerYear}}</div>
        <button class="btn-icon" onclick="state.pickerYear++;render()">›</button>
      </div>
      <div class="month-grid-picker">${{chips}}</div>
    </div>`;
  }}

  // Budget form
  let budgetHtml='';
  if(state.showBudget){{
    budgetHtml=`<div class="budget-form">
      <div class="budget-form-title">Presupuesto para ${{D.mes}} ${{D.anio}}</div>
      <div class="budget-input-row">
        <input id="budget-val" class="budget-input" type="number" inputmode="decimal"
          placeholder="${{D.presup||'0'}}" value="${{D.presup||''}}"
          onkeydown="if(event.key==='Enter')saveBudget()">
        <button class="budget-save-btn" onclick="saveBudget()">Guardar</button>
      </div>
    </div>`;
  }}

  // Budget bar
  let budgetBarHtml='';
  if(D.presup>0){{
    budgetBarHtml=`<div class="budget-wrap">
      <div class="budget-bar-bg">
        <div class="budget-bar-fill" style="width:${{presupPct.toFixed(1)}}%;background:${{presupColor}};"></div>
      </div>
      <div class="budget-meta">
        <span>${{fmtAmt(D.total)}} gastado</span>
        <span><b style="color:${{presupColor}};">${{fmtAmt(Math.max(D.presup-D.total,0))}}</b> restante</span>
      </div>
    </div>`;
    if(presupPct>=100){{
      budgetBarHtml+=`<div class="budget-alert danger">🚨 Superaste el presupuesto de ${{fmtAmt(D.presup)}}</div>`;
    }}else if(presupPct>=80){{
      budgetBarHtml+=`<div class="budget-alert warn">⚠️ Usaste el ${{Math.round(presupPct)}}% — quedan ${{fmtAmt(D.presup-D.total)}}</div>`;
    }}
  }}

  // Chart section
  let chartHtml='';
  if(movs.length>0){{
    if(state.chartMode==='cats'){{
      const donutSvg=donut(D.cats);
      const legend=D.cats.map(c=>`
        <div class="legend-row">
          <div class="legend-left">
            <div class="legend-dot" style="background:${{c.color}};"></div>
            <div class="legend-name">${{c.cat}}</div>
          </div>
          <div class="legend-pct">${{c.pct.toFixed(0)}}%</div>
        </div>`).join('');
      chartHtml=`<div class="donut-wrap">
        <div style="width:160px;flex-shrink:0;">${{donutSvg}}</div>
        <div class="donut-legend">${{legend}}</div>
      </div>`;

      // Expanders por categoría
      const catExpanders=D.cats.map(c=>{{
        const isOpen=state.expandedCat===c.cat;
        const catMovs=D.movs.filter(m=>m.cat===c.cat);
        const movItems=catMovs.map(m=>{{
          const delBtn=m.legacy?'':
            `<button class="btn-danger" onclick="event.stopPropagation();confirmDel('${{m.id}}')">🗑</button>`;
          return `<div class="mov-item">
            <div class="mov-icon-wrap" style="background:${{m.color}}18;">${{m.icon}}</div>
            <div class="mov-info">
              <div class="mov-name">${{m.desc}}</div>
              <div class="mov-sub">${{m.fecha}}</div>
            </div>
            <div class="mov-right">
              <div class="mov-amt" style="color:${{m.color}};">${{fmtAmt(m.amt)}}</div>
            </div>
            ${{delBtn}}
          </div>`;
        }}).join('');
        return `<div class="cat-expander">
          <div class="cat-header" onclick="state.expandedCat=${{isOpen?'null':"'"+c.cat+"'"}};render()">
            <div class="cat-icon" style="background:${{c.color}}18;">${{c.icon}}</div>
            <div class="cat-info">
              <div class="cat-name">${{c.cat}}</div>
              <div class="cat-sub">${{catMovs.length}} movimiento${{catMovs.length!==1?'s':''}}</div>
            </div>
            <div class="cat-right">
              <div class="cat-amt">${{fmtAmt(c.amt)}}</div>
              <div class="cat-pct" style="color:${{c.color}};">${{c.pct.toFixed(0)}}%</div>
            </div>
            <div class="cat-chevron ${{isOpen?'open':''}}">›</div>
          </div>
          <div class="cat-bar-bg">
            <div class="cat-bar-fill" style="width:${{c.pct}}%;background:${{c.color}};"></div>
          </div>
          <div class="cat-body ${{isOpen?'':'hidden'}}">${{movItems}}</div>
        </div>`;
      }}).join('');

      chartHtml+=`<div class="section-label" style="margin-top:16px;">DETALLE POR CATEGORÍA</div>
        <div class="sort-bar">
          <span class="sort-lbl">Ordenar:</span>
          <button class="sort-btn ${{D.sort_by==='fecha'?'active':''}}" onclick="nav('sort','by=fecha')">
            ${{D.sort_by==='fecha'?(D.sort_asc?'↑':'↓'):'↕'}} Fecha</button>
          <button class="sort-btn ${{D.sort_by==='monto'?'active':''}}" onclick="nav('sort','by=monto')">
            ${{D.sort_by==='monto'?(D.sort_asc?'↑':'↓'):'↕'}} Monto</button>
        </div>
        ${{catExpanders}}`;
    }}else{{
      chartHtml=`<div style="margin:8px 0;">${{histChart(D.hist)}}</div>`;
      const sortBar=`<div class="sort-bar">
        <span class="sort-lbl">Ordenar:</span>
        <button class="sort-btn ${{D.sort_by==='fecha'?'active':''}}" onclick="nav('sort','by=fecha')">
          ${{D.sort_by==='fecha'?(D.sort_asc?'↑':'↓'):'↕'}} Fecha</button>
        <button class="sort-btn ${{D.sort_by==='monto'?'active':''}}" onclick="nav('sort','by=monto')">
          ${{D.sort_by==='monto'?(D.sort_asc?'↑':'↓'):'↕'}} Monto</button>
      </div>`;
      const movItems=movs.map(m=>{{
        const delBtn=m.legacy?'':
          `<button class="btn-danger" onclick="event.stopPropagation();confirmDel('${{m.id}}')">🗑</button>`;
        return `<div class="mov-item">
          <div class="mov-icon-wrap" style="background:${{m.color}}18;">${{m.icon}}</div>
          <div class="mov-info">
            <div class="mov-name">${{m.desc}}</div>
            <div class="mov-sub">${{m.cat}} · ${{m.fecha}}</div>
          </div>
          <div class="mov-right">
            <div class="mov-amt" style="color:${{m.color}};">${{fmtAmt(m.amt)}}</div>
            <div class="mov-date">${{m.fecha}}</div>
          </div>
          ${{delBtn}}
        </div>`;
      }}).join('');
      chartHtml+=`<div class="section-label">MOVIMIENTOS</div>${{sortBar}}<div class="mov-list">${{movItems}}</div>`;
    }}
  }}else{{
    chartHtml=`<div class="empty">
      <div class="empty-icon">🌱</div>
      <div class="empty-title">Sin gastos este mes</div>
      <div class="empty-sub">Toca "+ Nuevo gasto" para empezar</div>
    </div>`;
  }}

  return `
    ${{successHtml}}
    <div class="badge" style="margin-bottom:2px;">
      <div class="dot"></div>${{D.now_dow}}, ${{D.now_day}} DE ${{D.now_mes}}
    </div>
    <div style="font-size:clamp(1.8rem,6vw,2.4rem);font-weight:800;
         color:#fff;margin:6px 0 16px;letter-spacing:-.8px;line-height:1.1;">Hola, Andrés 👋</div>
    <button class="btn btn-primary" onclick="nav('goto_add')">＋ Nuevo gasto</button>

    <div class="month-nav" style="margin-top:14px;">
      <button class="btn btn-icon" onclick="nav('prev_month')">‹</button>
      <div class="month-nav-label">${{D.mes}} ${{D.anio}}</div>
      <button class="btn btn-icon" onclick="nav('next_month')">›</button>
      <button class="btn btn-icon" onclick="state.showPicker=!state.showPicker;state.pickerYear=${{D.anio}};render()"
        style="${{state.showPicker?'border-color:var(--green);color:var(--green);':''}}">📅</button>
    </div>
    ${{pickerHtml}}

    <div class="card-hero">
      <div class="card-title">TOTAL GASTADO · ${{D.mes.toUpperCase()}}</div>
      <div class="card-amount">
        <span class="card-currency">S/</span>
        <span class="card-num">${{D.total.toLocaleString('es-PE',{{minimumFractionDigits:2,maximumFractionDigits:2}})}}</span>
      </div>
      ${{D.presup>0?`<div class="card-sub">de ${{fmtAmt(D.presup)}} presupuestado · <b>${{presupPct.toFixed(0)}}%</b></div>`:''}}
    </div>
    ${{budgetBarHtml}}

    <div class="stat-grid">
      <div class="stat-pill">
        <div class="stat-lbl">Prom / día</div>
        <div class="stat-val">${{fmtAmt(D.avg_day)}}</div>
      </div>
      <div class="stat-pill">
        <div class="stat-lbl">Proyección</div>
        <div class="stat-val">${{fmtAmt(D.proj)}}</div>
      </div>
      <div class="stat-pill">
        <div class="stat-lbl">Movimientos</div>
        <div class="stat-val">${{D.n_tx}}</div>
      </div>
      <div class="stat-pill">
        <div class="stat-lbl">🔥 Racha</div>
        <div class="stat-val ${{D.streak>0?'green':''}}">${{D.streak}}d</div>
      </div>
    </div>

    <div style="display:flex;gap:8px;margin-top:12px;align-items:center;">
      <button class="btn btn-secondary" style="flex:1;"
        onclick="state.showBudget=!state.showBudget;render()">
        🎯 Presupuesto</button>
      <a href="data:text/csv;charset=utf-8,${{encodeURIComponent(buildCSV())}}"
         download="gastos_${{D.mes}}_${{D.anio}}.csv"
         style="flex:1;display:flex;align-items:center;justify-content:center;
         height:40px;border-radius:var(--r-md);background:var(--s1);
         border:1px solid var(--border);color:var(--muted);font-size:.82rem;
         font-weight:700;text-decoration:none;font-family:var(--font);">
        ⬇️ CSV</a>
    </div>
    ${{budgetHtml}}

    <div class="search-wrap" style="margin-top:14px;">
      <span class="search-icon">🔍</span>
      <input class="search-input" placeholder="Buscar gasto o categoría…"
        value="${{state.search}}"
        oninput="state.search=this.value;render()">
    </div>

    <div class="tabs" style="margin-top:12px;">
      <div class="tab ${{state.chartMode==='cats'?'active':''}}"
        onclick="state.chartMode='cats';render()">Categorías</div>
      <div class="tab ${{state.chartMode==='hist'?'active':''}}"
        onclick="state.chartMode='hist';render()">Histórico</div>
    </div>
    ${{chartHtml}}
  `;
}}

function renderAdd(){{
  const pd=state.previewData;

  if(pd){{
    const cat=D.categories.find(c=>c.key===pd.cat)||D.categories[0];
    return `
      <div class="form-header">
        <button class="btn btn-icon" onclick="state.previewData=null;render()">←</button>
        <div class="form-title">Confirmar gasto</div>
      </div>
      <div class="preview-card">
        <div class="preview-amount" style="color:${{cat.color}};">${{fmtAmt(pd.amt)}}</div>
        <div class="preview-row">
          <span class="preview-lbl">Categoría</span>
          <span class="preview-val">${{cat.icon}} ${{pd.cat}}</span>
        </div>
        <div class="preview-row">
          <span class="preview-lbl">Descripción</span>
          <span class="preview-val">${{pd.desc||pd.cat}}</span>
        </div>
        <div class="preview-row">
          <span class="preview-lbl">Fecha</span>
          <span class="preview-val">${{pd.fecha}}</span>
        </div>
      </div>
      <div class="form-actions">
        <button class="btn btn-secondary" onclick="state.previewData=null;render()">✏️ Editar</button>
        <button class="btn btn-primary" onclick="confirmSave()">✅ Confirmar</button>
      </div>`;
  }}

  const fd=state.formData;
  const isZero=!fd.amt||parseFloat(fd.amt)===0;
  const chips=D.categories.map(c=>`
    <div class="cat-chip ${{fd.cat===c.key?'selected':''}}"
      onclick="state.formData.cat='${{c.key}}';render()">
      <span class="ico">${{c.icon}}</span>
      <span class="lbl">${{c.short}}</span>
    </div>`).join('');

  return `
    <div class="form-header">
      <button class="btn btn-icon" onclick="nav('goto_main')">←</button>
      <div class="form-title">Nuevo Gasto</div>
    </div>

    <div class="amount-display" onclick="document.getElementById('amt-input').focus()">
      <div class="amount-field-lbl">MONTO</div>
      <div class="amount-value ${{isZero?'zero':''}}">${{isZero?'0.00':fd.amt}}</div>
      <div class="amount-unit">SOLES</div>
      <input id="amt-input" class="amount-input-hidden" type="number"
        inputmode="decimal" step="0.01" min="0"
        value="${{fd.amt}}"
        oninput="state.formData.amt=this.value;renderAmtDisplay()"
        onchange="state.formData.amt=this.value;render()">
    </div>

    <div class="section-label" style="text-align:center;margin-top:18px;">CATEGORÍA</div>
    <div class="cat-grid">${{chips}}</div>

    <div class="form-field">
      <div class="form-field-lbl">FECHA</div>
      <input class="form-input" type="date" value="${{fd.fecha}}"
        onchange="state.formData.fecha=this.value;render()">
    </div>

    <div class="form-field">
      <div class="form-field-lbl">NOTA (opcional)</div>
      <input class="form-input" type="text" placeholder="Ej: almuerzo, taxi, farmacia…"
        value="${{fd.desc}}"
        oninput="state.formData.desc=this.value">
    </div>

    <div class="form-actions" style="margin-top:20px;">
      <button class="btn btn-secondary" onclick="nav('goto_main')">Cancelar</button>
      <button class="btn btn-primary" ${{isZero?'disabled style="opacity:.4;"':''}}
        onclick="reviewExpense()">Revisar →</button>
    </div>`;
}}

function renderAmtDisplay(){{
  const el=document.querySelector('.amount-value');
  if(!el) return;
  const v=state.formData.amt;
  const isZero=!v||parseFloat(v)===0;
  el.textContent=isZero?'0.00':v;
  el.className='amount-value'+(isZero?' zero':'');
}}

function render(){{
  document.getElementById('app').innerHTML=
    state.view==='add'?renderAdd():renderMain();
  // Auto-focus amount input in add view
  if(state.view==='add'&&!state.previewData){{
    setTimeout(()=>{{
      const inp=document.getElementById('amt-input');
      if(inp)inp.focus();
    }},100);
  }}
}}

function reviewExpense(){{
  const fd=state.formData;
  const amt=parseFloat(fd.amt||'0');
  if(amt<=0) return;
  state.previewData={{amt,cat:fd.cat,desc:fd.desc,fecha:fd.fecha}};
  render();
}}

function confirmSave(){{
  const pd=state.previewData;
  if(!pd) return;
  nav('save_expense',
    'amt='+pd.amt+
    '&cat='+encodeURIComponent(pd.cat)+
    '&desc='+encodeURIComponent(pd.desc||pd.cat)+
    '&fecha='+pd.fecha);
}}

function saveBudget(){{
  const inp=document.getElementById('budget-val');
  const val=inp?parseFloat(inp.value||'0'):0;
  nav('save_budget','mes='+encodeURIComponent(D.mes)+'&anio='+D.anio+'&val='+val);
}}

function confirmDel(id){{
  if(confirm('¿Eliminar este gasto? No se puede deshacer.')){{
    nav('delete','id='+id);
  }}
}}

function buildCSV(){{
  const hdr='FECHA,MES,CATEGORIA,DESCRIPCION,MONTO,ID\\n';
  const rows=D.movs.map(m=>
    `${{m.fecha}},${{D.mes}},${{m.cat}},"${{m.desc}}",${{m.amt}},${{m.id}}`
  ).join('\\n');
  return hdr+rows;
}}

// Auto-resize iframe to content height
function resizeIframe(){{
  const h = document.body.scrollHeight;
  window.parent.postMessage({{type:'streamlit:setFrameHeight', height:h}}, '*');
}}
const resizeObserver = new ResizeObserver(resizeIframe);
resizeObserver.observe(document.body);

// Toast auto-dismiss
if(D.toast){{
  setTimeout(()=>nav('clear_toast'),2500);
}}

// Init
if(D.view==='add'){{
  state.view='add';
  state.formData.fecha=todayStr();
}}
render();
// Initial resize after render
setTimeout(resizeIframe, 200);
</script>
{f'<div class="toast">{payload["toast"]}</div>' if payload.get("toast") else ""}
</body>
</html>"""
    components.html(html, height=3000, scrolling=True)

# ============================================================
# 7) MAIN
# ============================================================
try:
    handle_actions()
    df      = load_data()
    budgets = load_budgets()
    payload = build_payload(
        df,
        st.session_state.sel_month,
        st.session_state.sel_year,
        budgets,
    )
    render_app(payload)
except Exception:
    st.error("Error en la app")
    st.code(traceback.format_exc())
