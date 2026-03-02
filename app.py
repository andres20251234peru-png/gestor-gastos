# ============================================================
# GESTOR DE GASTOS v3.0
# ============================================================
# Mejoras v3:
#   - Sin IA (eliminado completamente)
#   - ID único por gasto (eliminar seguro)
#   - Navegación ‹ › mes directo en header
#   - Skeleton loader en primera carga
#   - Confirmar gasto con pantalla de preview
#   - Ordenar movimientos por monto o fecha
#   - Animación visual al guardar (flash verde)
#   - Botón eliminar compacto (mobile-friendly)
#   - Fix zona horaria Perú (UTC-5)
# ============================================================

import streamlit as st
import datetime as dt
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import os
import json
import pathlib
import uuid
import io
from dotenv import load_dotenv
import traceback
import matplotlib.pyplot as plt

# ============================================================
# 1) CONFIG
# ============================================================
st.set_page_config(
    page_title="Gastos · Andrés",
    page_icon="💸",
    layout="centered",
    initial_sidebar_state="collapsed",
)

env_path = pathlib.Path(".") / ".env"
if not env_path.exists():
    env_path = pathlib.Path(".") / ".env.local"
load_dotenv(dotenv_path=env_path)

SHEET_NAME = "Gastos_Diarios"

# ============================================================
# 2) CONSTANTES
# ============================================================
MESES_ORD = [
    "Enero","Febrero","Marzo","Abril","Mayo","Junio",
    "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre",
]
DIAS_ORD = ["LUNES","MARTES","MIÉRCOLES","JUEVES","VIERNES","SÁBADO","DOMINGO"]

TZ_OFFSET = dt.timezone(dt.timedelta(hours=-5))  # Perú UTC-5

THEME = {
    "bg":      "#000000",
    "surface": "#0F0F10",
    "card":    "#121212",
    "primary": "#00E054",
    "text":    "#FFFFFF",
    "muted":   "#A6A6A6",
    "stroke":  "#242424",
    "input":   "#1E1E1E",
    "danger":  "#FF4B4B",
    "warning": "#FFC700",
}

CATEGORIES = {
    "Alimentación":      ("🍽️", "#00E054"),
    "Transporte":        ("🚗", "#00F0FF"),
    "Salud":             ("💊", "#FFC700"),
    "Trabajo":           ("💼", "#FF4B4B"),
    "Ocio":              ("🎵", "#FFFFFF"),
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

VALID_CATS  = list(CATEGORIES.keys())
ICON_MAP    = {k: v[0] for k, v in CATEGORIES.items()}
COLORS_MAP  = {k: v[1] for k, v in CATEGORIES.items()}
CAT_ALIASES = {"Comida": "Alimentación", "comida": "Alimentación"}

# ============================================================
# 3) SESSION STATE
# ============================================================
_now = dt.datetime.now(TZ_OFFSET)
_DEFAULTS = {
    "view":           "main",
    "expanded_cat":   None,
    "chart_mode":     "Categorías",
    "hist_mode":      "Diario",
    "sel_year":       _now.year,
    "sel_month":      MESES_ORD[_now.month - 1],
    "search_query":   "",
    "confirm_delete": None,   # ID del gasto a borrar
    "budget_mode":    False,
    "presupuesto":    {},
    "sort_by":        "fecha",
    "sort_asc":       False,
    "show_success":   False,
    "preview_data":   None,
    "data_loaded":    False,
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ============================================================
# 4) CSS
# ============================================================
def inject_css():
    p = THEME["primary"]
    st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,400;0,700;0,900;1,400&family=JetBrains+Mono:wght@700&display=swap');

html, body, [class*="css"] {{
  font-family: 'DM Sans', sans-serif !important;
  color: {THEME['text']} !important;
}}
.stApp {{ background: {THEME['bg']} !important; }}
.block-container {{
  max-width: 860px !important;
  padding-top: 20px !important;
  padding-bottom: 60px !important;
}}
header, footer {{ visibility: hidden; }}

/* ── Inputs ── */
div[data-baseweb="select"] > div {{
  background: {THEME['input']} !important;
  border: 1px solid {THEME['stroke']} !important;
  border-radius: 999px !important;
}}
div[data-baseweb="menu"], div[data-baseweb="popover"],
ul[data-testid="stSelectboxVirtualDropdown"] {{
  background-color: #121212 !important;
  border: 1px solid {THEME['stroke']} !important;
}}
li[role="option"] {{ color: white !important; }}
li[role="option"][aria-selected="true"] {{
  background: #2a2a2a !important; color: {p} !important;
}}
div[data-testid="stNumberInput"] input {{
  background: #0f1713 !important;
  border: 1px solid #1f2a23 !important;
  border-radius: 22px !important;
  color: {p} !important;
  font-size: 3.2rem !important;
  font-weight: 900 !important;
  font-family: 'JetBrains Mono', monospace !important;
  text-align: center !important;
  padding: 22px 0 !important;
  caret-color: {p} !important;
}}
input[type="text"], div[data-testid="stTextInput"] input {{
  background: {THEME['input']} !important;
  border: 1px solid {THEME['stroke']} !important;
  border-radius: 14px !important;
  color: {THEME['text']} !important;
  padding: 10px 16px !important;
}}
input[type="text"]:focus, div[data-testid="stTextInput"] input:focus {{
  border-color: {p} !important;
  box-shadow: 0 0 0 2px rgba(0,224,84,0.15) !important;
  outline: none !important;
}}

/* ── Botones ── */
button {{ border-radius: 18px !important; }}
button[kind="primary"] {{
  background: {p} !important; color: #000 !important;
  border: none !important; font-weight: 900 !important;
  font-family: 'DM Sans', sans-serif !important;
  height: 46px !important;
  transition: transform .12s ease, box-shadow .12s ease !important;
}}
button[kind="primary"]:hover {{
  transform: translateY(-1px) !important;
  box-shadow: 0 6px 20px rgba(0,224,84,0.3) !important;
}}
button[kind="secondary"] {{
  background: #121212 !important;
  border: 1px solid #2a2a2a !important;
  color: {THEME['text']} !important;
  font-family: 'DM Sans', sans-serif !important;
  height: 46px !important;
  transition: border-color .15s ease !important;
}}
button[kind="secondary"]:hover {{ border-color: {p} !important; }}

/* ── Chips radio ── */
div[role="radiogroup"] {{
  display: flex; flex-wrap: wrap; gap: 10px; justify-content: center;
}}
div[role="radiogroup"] label {{
  background: {THEME['input']} !important;
  border: 1px solid {THEME['stroke']} !important;
  border-radius: 999px !important; padding: 10px 16px !important;
  cursor: pointer; transition: all .15s ease;
}}
div[role="radiogroup"] label p {{
  color: #cfcfcf !important; font-weight: 800 !important;
  font-size: .9rem !important; margin: 0 !important;
}}
div[role="radiogroup"] label:has(input:checked) {{
  background: {p} !important; border-color: {p} !important;
  box-shadow: 0 8px 18px rgba(0,224,84,0.25) !important;
}}
div[role="radiogroup"] label:has(input:checked) p {{
  color: #000 !important; font-weight: 900 !important;
}}
div[role="radiogroup"] label > div:first-child {{ display: none; }}

/* ── Card total ── */
.card {{
  background: linear-gradient(180deg,#192b23 0%,#0f1613 100%) !important;
  border: 1px solid #1f332a !important; border-radius: 28px !important;
  padding: 28px 22px !important;
  box-shadow: 0 18px 36px rgba(0,0,0,0.55) !important;
  position: relative; overflow: hidden; margin-top: 10px;
  display: flex !important; flex-direction: column !important;
  align-items: center !important; justify-content: center !important;
}}
.card-title {{
  color: #8fa397 !important; font-size: .78rem !important;
  letter-spacing: 2.4px !important; text-transform: uppercase !important;
  margin-bottom: 10px !important; text-align: center !important; font-weight: 800 !important;
}}
.card-amount {{
  font-size: 3.2rem !important; font-weight: 900 !important; margin: 0 !important;
  text-align: center !important; color: #FFFFFF !important; line-height: 1 !important;
  font-family: 'JetBrains Mono', monospace !important;
}}
.card-sub {{
  color: #8fa397 !important; font-size: .82rem !important;
  font-weight: 700 !important; margin-top: 6px !important; text-align: center !important;
}}
.card-watermark {{
  position: absolute; right: -22px; bottom: -42px; opacity: .05;
  font-size: 9.6rem; color: white; transform: rotate(-15deg); pointer-events: none;
}}

/* ── Flash de éxito ── */
@keyframes successFlash {{
  0%   {{ opacity: 0; transform: scale(0.97); }}
  15%  {{ opacity: 1; transform: scale(1.01); }}
  80%  {{ opacity: 1; transform: scale(1); }}
  100% {{ opacity: 0; }}
}}
.success-flash {{
  position: fixed; inset: 0;
  background: rgba(0,224,84,0.07);
  border: 2px solid rgba(0,224,84,0.25);
  border-radius: 16px; z-index: 9999; pointer-events: none;
  animation: successFlash 1.4s ease forwards;
}}
.success-banner {{
  background: linear-gradient(90deg,#0a2018,#0f2a1c);
  border: 1px solid #1f4a30; border-radius: 18px;
  padding: 16px 20px; display: flex; align-items: center; gap: 14px;
  margin-bottom: 16px;
  animation: successFlash 2.5s ease forwards;
}}
.success-icon  {{ font-size: 1.8rem; }}
.success-title {{ font-weight: 900; color: {p}; font-size: 1rem; }}
.success-sub   {{ font-size: .82rem; color: #8fa397; font-weight: 700; }}

/* ── Stat pills ── */
.stat-row  {{ display: flex; gap: 10px; margin-top: 12px; }}
.stat-pill {{
  flex: 1; background: #111; border: 1px solid #1f1f1f;
  border-radius: 18px; padding: 12px 14px;
  display: flex; flex-direction: column; gap: 3px;
}}
.stat-label {{ color: #555; font-size: .72rem; font-weight: 800; letter-spacing: 1px; text-transform: uppercase; }}
.stat-value {{ color: #fff; font-size: 1.05rem; font-weight: 900; font-family: 'JetBrains Mono', monospace; }}
.stat-value.green {{ color: {p} !important; }}

/* ── Badge ── */
.badge {{
  display: inline-flex; align-items: center; gap: 8px; padding: 6px 10px;
  border-radius: 999px; border: 1px solid #1f332a; background: #0b1410;
  color: #9fc4b0 !important; font-weight: 800; font-size: .78rem; letter-spacing: .6px;
}}

/* ── Nav mes ── */
.month-label {{
  font-size: 1.05rem; font-weight: 900; color: #fff;
  text-align: center; padding-top: 8px;
}}

/* ── Section title ── */
.section-title {{
  color: #555 !important; font-weight: 900; font-size: .82rem;
  letter-spacing: 1.8px; margin-top: 20px; margin-bottom: 10px;
}}

/* ── Expander ── */
div[data-testid="stExpander"] {{
  border: 1px solid #1f1f1f !important; border-radius: 18px !important;
  background: #111211 !important; overflow: hidden;
}}
div[data-testid="stExpander"] details {{ background: #111211 !important; }}
div[data-testid="stExpander"] summary {{
  padding: 14px 16px !important; background-color: #111211 !important;
}}
div[data-testid="stExpander"] summary:hover {{ background-color: #181918 !important; }}
div[data-testid="stExpander"] summary p {{ font-weight: 900 !important; }}

/* ── Movimientos ── */
.mov-item {{
  background: #111; border: 1px solid #1f1f1f; border-radius: 18px;
  padding: 14px 16px; margin-bottom: 8px;
  display: flex; justify-content: space-between; align-items: center;
  transition: border-color .15s ease;
}}
.mov-item:hover {{ border-color: #2a2a2a; }}
.mov-left {{ display: flex; flex-direction: column; gap: 4px; min-width: 0; flex: 1; }}
.mov-cat  {{ font-weight: 900; }}
.mov-desc {{
  color: #8a8a8a; font-size: .86rem;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 480px;
}}
.mov-amt  {{ font-weight: 900; color: {p}; white-space: nowrap; font-family: 'JetBrains Mono', monospace; }}

/* ── Legend ── */
.legend-row {{
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 0; border-bottom: 1px solid #1f1f1f;
}}
.legend-row:last-child {{ border-bottom: none; }}
.legend-left {{ display: flex; align-items: center; gap: 10px; }}
.legend-dot  {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
.legend-name {{ color: #e0e0e0; font-weight: 700; font-size: .9rem; }}
.legend-pct  {{ color: #888; font-weight: 800; font-size: .9rem; }}

/* ── Rich card ── */
.rich-card    {{ padding-bottom: 12px; margin-bottom: 12px; border-bottom: 1px solid #1f1f1f; }}
.rich-header  {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
.rich-left    {{ display: flex; flex-direction: column; gap: 2px; }}
.rich-right   {{ display: flex; flex-direction: column; align-items: flex-end; gap: 2px; }}
.rich-cat     {{ font-size: 1.1rem; font-weight: 900; color: #fff; }}
.rich-sub     {{ font-size: .75rem; font-weight: 700; color: #666; text-transform: uppercase; letter-spacing: .5px; }}
.rich-amt     {{ font-size: 1.2rem; font-weight: 900; color: #fff; font-family: 'JetBrains Mono', monospace; }}
.rich-pct     {{ font-size: .9rem; font-weight: 800; }}
.rich-bar-bg  {{ width: 100%; height: 6px; background: #2b2b2b; border-radius: 99px; margin-top: 6px; overflow: hidden; }}
.rich-bar-fill {{ height: 100%; border-radius: 99px; }}

/* ── Budget ── */
.budget-bar-bg   {{ width: 100%; height: 8px; background: #1f1f1f; border-radius: 99px; overflow: hidden; margin-top: 10px; }}
.budget-bar-fill {{ height: 100%; border-radius: 99px; transition: width .4s ease; }}
.budget-meta     {{ display: flex; justify-content: space-between; margin-top: 4px; }}
.budget-spent    {{ color: #fff; font-size: .8rem; font-weight: 800; }}
.budget-remain   {{ font-size: .8rem; font-weight: 800; }}

/* ── Skeleton ── */
@keyframes shimmer {{
  0%   {{ background-position: -600px 0; }}
  100% {{ background-position:  600px 0; }}
}}
.skeleton {{
  background: linear-gradient(90deg,#1a1a1a 25%,#242424 50%,#1a1a1a 75%);
  background-size: 600px 100%;
  animation: shimmer 1.4s infinite linear;
  border-radius: 14px;
}}
.skeleton-card {{ height: 140px; margin-bottom: 12px; border-radius: 28px; }}
.skeleton-pill {{ height: 72px; flex: 1; border-radius: 18px; }}
.skeleton-row  {{ height: 64px; margin-bottom: 8px; border-radius: 18px; }}

/* ── Preview ── */
.preview-card {{
  background: #0f1f19; border: 1px solid #1f4a30;
  border-radius: 22px; padding: 22px 20px; margin-bottom: 16px;
}}
.preview-row {{
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 0; border-bottom: 1px solid #162a1e;
}}
.preview-row:last-child {{ border-bottom: none; }}
.preview-label  {{ color: #8fa397; font-size: .82rem; font-weight: 800; text-transform: uppercase; letter-spacing: .8px; }}
.preview-value  {{ color: #fff; font-weight: 900; font-size: .95rem; }}
.preview-amount {{ color: {p}; font-weight: 900; font-size: 1.6rem; font-family: 'JetBrains Mono', monospace; }}

/* ── Sort bar ── */
.sort-label {{ color: #555; font-size: .78rem; font-weight: 800; letter-spacing: 1px; text-transform: uppercase; padding-top: 10px; }}

/* ── Empty state ── */
.empty-state {{
  text-align: center; padding: 48px 24px;
}}
.empty-icon  {{ font-size: 3rem; margin-bottom: 12px; }}
.empty-title {{ font-size: 1.2rem; font-weight: 900; color: #666; margin-bottom: 6px; }}
.empty-sub   {{ font-size: .9rem; color: #444; }}

/* ── Toast ── */
div[data-testid="stToast"] {{
  background-color: #111211 !important; border: 1px solid #1f1f1f !important;
  color: #fff !important; border-radius: 12px !important;
}}
div[data-testid="stToast"] p, div[data-testid="stToast"] svg {{
  color: #fff !important; fill: #fff !important;
}}
</style>
    """, unsafe_allow_html=True)


# ============================================================
# 5) GOOGLE SHEETS
# ============================================================
@st.cache_resource
def get_client():
    try:
        scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        info  = json.loads(st.secrets["GCP_SERVICE_ACCOUNT"])
        creds = Credentials.from_service_account_info(info, scopes=scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error("❌ Error conectando con Google Sheets")
        st.exception(e)
        return None


def normalize_mes(m):
    if not isinstance(m, str):
        return None
    return {k.lower(): k for k in MESES_ORD}.get(m.strip().lower(), m.strip().capitalize())


def normalize_cat(c):
    c = str(c).strip()
    return CAT_ALIASES.get(c, c if c in VALID_CATS else "Otros")


@st.cache_data(ttl=180, show_spinner=False)
def load_data() -> pd.DataFrame:
    client = get_client()
    if not client:
        return pd.DataFrame()
    try:
        sheet = client.open(SHEET_NAME).sheet1
        df    = pd.DataFrame(sheet.get_all_records())
        if df.empty:
            return df

        cu = {c.strip().upper(): c for c in df.columns}

        # FECHA
        fcol = cu.get("FECHA")
        df["FECHA"] = pd.to_datetime(df[fcol], errors="coerce", dayfirst=True) if fcol else pd.NaT

        # MES
        df["MES"] = (
            df[cu["MES"]].apply(normalize_mes) if "MES" in cu
            else df["FECHA"].dt.month.map(lambda x: MESES_ORD[x-1] if pd.notna(x) else None)
        )

        # AÑO
        df["AÑO"] = (
            pd.to_numeric(df[cu["AÑO"]], errors="coerce").fillna(0).astype(int) if "AÑO" in cu
            else df["FECHA"].dt.year.fillna(0).astype(int)
        )

        # CATEGORÍA
        ccat = cu.get("CATEGORÍA") or cu.get("CATEGORIA")
        df["CATEGORÍA"] = df[ccat].apply(normalize_cat) if ccat else "Otros"

        # DESCRIPCION
        cdesc = cu.get("DESCRIPCION") or cu.get("DESCRIPCIÓN")
        df["DESCRIPCION"] = df[cdesc].astype(str).str.strip() if cdesc else ""

        # MONTO
        if "MONTO" in cu:
            df["MONTO"] = pd.to_numeric(
                df[cu["MONTO"]].astype(str).str.replace(",", "", regex=False),
                errors="coerce",
            ).fillna(0.0)
        else:
            df["MONTO"] = 0.0

        # ID — columna clave para eliminar de forma segura
        if "ID" in cu:
            df["ID"] = df[cu["ID"]].astype(str).str.strip()
        else:
            # Gastos legacy sin ID: asignamos temporal (no se puede borrar de forma segura)
            df["ID"] = [f"legacy_{i}" for i in range(len(df))]

        df = df[(df["AÑO"] > 0) & (df["MES"].notna()) & (df["MONTO"] > 0)]
        return df.reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def save_to_sheet(data: dict) -> tuple[bool, str]:
    client = get_client()
    if not client:
        return False, "Sin credenciales."
    try:
        sheet    = client.open(SHEET_NAME).sheet1
        mes_name = MESES_ORD[data["date"].month - 1]
        gasto_id = str(uuid.uuid4())[:8]

        # Asegurar que existe la columna ID en el header
        headers = sheet.row_values(1)
        if "ID" not in headers:
            sheet.update_cell(1, len(headers) + 1, "ID")

        row = [
            data["date"].strftime("%d/%m/%Y"),
            mes_name,
            int(data["date"].year),
            data["category"],
            data["description"],
            float(data["amount"]),
            gasto_id,
        ]
        sheet.append_row(row)
        load_data.clear()
        return True, gasto_id
    except Exception as e:
        return False, str(e)


def delete_from_sheet(gasto_id: str) -> tuple[bool, str]:
    """Busca la fila por ID único y la elimina. Nunca borra la fila equivocada."""
    client = get_client()
    if not client:
        return False, "Sin credenciales."
    try:
        sheet   = client.open(SHEET_NAME).sheet1
        values  = sheet.get_all_values()
        headers = [h.strip().upper() for h in values[0]]
        id_col  = next((i for i, h in enumerate(headers) if h == "ID"), None)

        if id_col is None:
            return False, "Columna ID no encontrada. Agrega la columna ID al Sheet."

        row_to_delete = next(
            (i + 2 for i, row in enumerate(values[1:])
             if len(row) > id_col and str(row[id_col]).strip() == gasto_id),
            None,
        )
        if row_to_delete is None:
            return False, f"No se encontró el gasto con ID '{gasto_id}'."

        sheet.delete_rows(row_to_delete)
        load_data.clear()
        return True, "OK"
    except Exception as e:
        return False, str(e)


# ============================================================
# 6) HELPERS DE DATOS
# ============================================================
def now_peru() -> dt.datetime:
    return dt.datetime.now(TZ_OFFSET)


def filter_data(df: pd.DataFrame, mes, anio: int) -> pd.DataFrame:
    if df.empty:
        return df
    mask = df["AÑO"] == int(anio)
    if mes is not None:
        mask &= df["MES"] == mes
    return df[mask].copy()


def compute_stats(dfm: pd.DataFrame, total: float) -> dict:
    if dfm.empty or total <= 0:
        return {}
    now     = now_peru()
    avg_day = total / max(now.day, 1)
    return {
        "avg_day": avg_day,
        "proj":    avg_day * 30,
        "n_tx":    len(dfm),
        "top_cat": dfm.groupby("CATEGORÍA")["MONTO"].sum().idxmax(),
    }


def days_without_expense(df: pd.DataFrame) -> int:
    """Días consecutivos sin gasto — vectorizado."""
    if df.empty:
        return 0
    today = now_peru().date()
    dates = set(df["FECHA"].dropna().dt.date.unique())
    past  = pd.date_range(end=today - dt.timedelta(days=1), periods=365, freq="D")
    streak = 0
    for d in reversed(past):
        if d.date() in dates:
            break
        streak += 1
    return streak


def apply_sort(dfm: pd.DataFrame) -> pd.DataFrame:
    col = "FECHA" if st.session_state.sort_by == "fecha" else "MONTO"
    return dfm.sort_values(col, ascending=st.session_state.sort_asc)


def export_csv(dfm: pd.DataFrame) -> bytes:
    keep = [c for c in ["FECHA","MES","AÑO","CATEGORÍA","DESCRIPCION","MONTO","ID"] if c in dfm.columns]
    buf  = io.StringIO()
    dfm[keep].to_csv(buf, index=False)
    return buf.getvalue().encode()


def prev_month():
    idx = MESES_ORD.index(st.session_state.sel_month)
    if idx == 0:
        st.session_state.sel_month = MESES_ORD[11]
        st.session_state.sel_year -= 1
    else:
        st.session_state.sel_month = MESES_ORD[idx - 1]


def next_month():
    idx = MESES_ORD.index(st.session_state.sel_month)
    if idx == 11:
        st.session_state.sel_month = MESES_ORD[0]
        st.session_state.sel_year += 1
    else:
        st.session_state.sel_month = MESES_ORD[idx + 1]


# ============================================================
# 7) CHARTS
# ============================================================
def _fig_base(w=5, h=5, dpi=200):
    fig, ax = plt.subplots(figsize=(w, h), dpi=dpi)
    fig.patch.set_facecolor("none")
    ax.set_facecolor("none")
    return fig, ax


def render_donut(grp_df: pd.DataFrame, center_cat: str, center_pct: float):
    colors = [COLORS_MAP.get(c, "#888") for c in grp_df["CATEGORÍA"]]
    fig, ax = _fig_base(5, 5, 220)
    ax.pie(grp_df["MONTO"], colors=colors, startangle=90, counterclock=False,
           wedgeprops=dict(width=0.20, edgecolor="none"))
    ax.text(0, 0.24, center_cat.upper(), ha="center", va="center",
            fontsize=9, fontweight="800", color="#666666")
    ax.text(-0.05, -0.05, f"{int(center_pct)}", ha="center", va="center",
            fontsize=52, fontweight="900", color="#FFFFFF")
    ax.text(0.35, -0.02, "%", ha="center", va="center",
            fontsize=24, fontweight="900", color=COLORS_MAP.get(center_cat, "#fff"))
    ax.set(aspect="equal")
    ax.axis("off")
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)


def render_history_chart(df: pd.DataFrame, view_mode="Diario"):
    if df.empty:
        st.info("No hay datos para mostrar.")
        return
    df = df.copy()
    df["_dt"] = pd.to_datetime(df["FECHA"])

    if view_mode == "Diario":
        grouped = df.groupby(df["_dt"].dt.day)["MONTO"].sum()
        xlabels = [str(int(v)) for v in grouped.index]
    elif view_mode == "Semanal":
        df["_w"] = (df["_dt"].dt.day - 1) // 7 + 1
        grouped  = df.groupby("_w")["MONTO"].sum()
        xlabels  = [f"SEM {int(v)}" for v in grouped.index]
    else:
        grouped = df.groupby(df["_dt"].dt.month)["MONTO"].sum()
        xlabels = [MESES_ORD[int(v)-1][:3].upper() for v in grouped.index]

    x, y    = list(grouped.index), list(grouped.values)
    fig, ax = _fig_base(6, 3, 180)
    bars    = ax.bar(x, y, color=THEME["primary"], alpha=0.85, edgecolor="none", width=0.6)
    if y:
        bars[y.index(max(y))].set_color("#FFFFFF")

    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.spines['bottom'].set_color('#333')
    ax.tick_params(axis='x', colors='#888', labelsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(xlabels, fontweight="700")
    ax.yaxis.grid(True, linestyle='--', alpha=0.08, color='#fff')
    ax.tick_params(axis='y', labelsize=8, labelcolor="#666")
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)


# ============================================================
# 8) COMPONENTES REUTILIZABLES
# ============================================================
def render_skeleton():
    st.markdown("""
        <div class="skeleton skeleton-card"></div>
        <div style="display:flex;gap:10px;margin-top:12px;">
          <div class="skeleton skeleton-pill"></div>
          <div class="skeleton skeleton-pill"></div>
          <div class="skeleton skeleton-pill"></div>
          <div class="skeleton skeleton-pill"></div>
        </div>
        <br>
        <div class="skeleton skeleton-row"></div>
        <div class="skeleton skeleton-row"></div>
        <div class="skeleton skeleton-row"></div>
    """, unsafe_allow_html=True)


def render_success_banner(cat: str, amount: float, desc: str):
    icon = ICON_MAP.get(cat, "✅")
    st.markdown(f"""
        <div class="success-flash"></div>
        <div class="success-banner">
          <div class="success-icon">{icon}</div>
          <div>
            <div class="success-title">¡Gasto guardado!</div>
            <div class="success-sub">{cat} · S/ {amount:,.2f} · {desc}</div>
          </div>
        </div>
    """, unsafe_allow_html=True)


def render_mov_item(desc: str, subtitle: str, amt: float, gasto_id: str, key_prefix: str):
    """Fila de movimiento con botón eliminar compacto."""
    c_mov, c_del = st.columns([11, 1])
    with c_mov:
        st.markdown(f"""
            <div class="mov-item">
              <div class="mov-left">
                <div class="mov-cat">{desc}</div>
                <div class="mov-desc">{subtitle}</div>
              </div>
              <div class="mov-amt">S/ {amt:,.2f}</div>
            </div>
        """, unsafe_allow_html=True)
    with c_del:
        # Botón inline, solo visible si hay ID real
        is_legacy = gasto_id.startswith("legacy_")
        if not is_legacy:
            st.markdown("<div style='margin-top:8px;'>", unsafe_allow_html=True)
            if st.button("🗑", key=f"{key_prefix}_{gasto_id}", help="Eliminar gasto"):
                st.session_state.confirm_delete = gasto_id
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)


def render_sort_bar():
    c1, c2, c3, _ = st.columns([1.5, 2, 2, 4])
    with c1:
        st.markdown('<div class="sort-label">Ordenar:</div>', unsafe_allow_html=True)
    with c2:
        arrow = "↑" if st.session_state.sort_asc else "↓"
        if st.button(
            f"{arrow if st.session_state.sort_by == 'fecha' else '↕'} Fecha",
            key="sort_f", use_container_width=True,
            type="primary" if st.session_state.sort_by == "fecha" else "secondary",
        ):
            if st.session_state.sort_by == "fecha":
                st.session_state.sort_asc = not st.session_state.sort_asc
            else:
                st.session_state.sort_by = "fecha"
                st.session_state.sort_asc = False
            st.rerun()
    with c3:
        if st.button(
            f"{arrow if st.session_state.sort_by == 'monto' else '↕'} Monto",
            key="sort_m", use_container_width=True,
            type="primary" if st.session_state.sort_by == "monto" else "secondary",
        ):
            if st.session_state.sort_by == "monto":
                st.session_state.sort_asc = not st.session_state.sort_asc
            else:
                st.session_state.sort_by = "monto"
                st.session_state.sort_asc = False
            st.rerun()


# ============================================================
# 9) VISTA PRINCIPAL
# ============================================================
def main_view():
    # Skeleton en primera carga real
    if not st.session_state.data_loaded:
        ph = st.empty()
        with ph.container():
            render_skeleton()
        df = load_data()
        st.session_state.data_loaded = True
        ph.empty()
    else:
        df = load_data()

    now          = now_peru()
    date_display = f"{DIAS_ORD[now.weekday()]}, {now.day} DE {MESES_ORD[now.month-1].upper()}"

    # ── Banner éxito post-guardado ───────────────────────────
    if st.session_state.show_success and st.session_state.preview_data:
        pd_ = st.session_state.preview_data
        render_success_banner(pd_.get("category",""), pd_.get("amount",0), pd_.get("description",""))
        st.session_state.show_success = False
        st.session_state.preview_data = None

    # ── Header ──────────────────────────────────────────────
    c_l, c_r = st.columns([7, 3], vertical_alignment="center")
    with c_l:
        st.markdown(
            f'<div class="badge">● {date_display}</div>'
            f'<div style="margin-top:10px;font-size:2rem;font-weight:900;line-height:1.1;">Hola, Andrés 👋</div>',
            unsafe_allow_html=True,
        )
    with c_r:
        if st.button("➕ Nuevo gasto", type="primary", use_container_width=True):
            st.session_state.view = "add"
            st.rerun()

    st.write("")

    # ── Navegación rápida mes ────────────────────────────────
    c_prev, c_lbl, c_next, c_pick = st.columns([1, 5, 1, 1.5], vertical_alignment="center")
    with c_prev:
        if st.button("‹", key="pm", type="secondary", use_container_width=True):
            prev_month(); st.rerun()
    with c_lbl:
        st.markdown(
            f'<div class="month-label">{st.session_state.sel_month} {st.session_state.sel_year}</div>',
            unsafe_allow_html=True,
        )
    with c_next:
        if st.button("›", key="nm", type="secondary", use_container_width=True):
            next_month(); st.rerun()
    with c_pick:
        with st.expander("📅"):
            cy1, cy2, cy3 = st.columns([1,2,1])
            with cy1:
                if st.button("‹", key="py", type="secondary", use_container_width=True):
                    st.session_state.sel_year -= 1; st.rerun()
            with cy2:
                st.markdown(f"<div style='text-align:center;font-weight:900;padding-top:8px;'>{st.session_state.sel_year}</div>",
                            unsafe_allow_html=True)
            with cy3:
                if st.button("›", key="ny", type="secondary", use_container_width=True):
                    st.session_state.sel_year += 1; st.rerun()
            abbrs = ["ENE","FEB","MAR","ABR","MAY","JUN","JUL","AGO","SEP","OCT","NOV","DIC"]
            for row in [abbrs[i:i+3] for i in range(0,12,3)]:
                cols = st.columns(3)
                for i, abbr in enumerate(row):
                    full = MESES_ORD[abbrs.index(abbr)]
                    with cols[i]:
                        t = "primary" if full == st.session_state.sel_month else "secondary"
                        if st.button(abbr, key=f"mp_{abbr}", type=t, use_container_width=True):
                            st.session_state.sel_month = full; st.rerun()

    mes_sel  = st.session_state.sel_month
    anio_sel = st.session_state.sel_year
    dfm      = filter_data(df, mes_sel, anio_sel)
    total    = float(dfm["MONTO"].sum()) if not dfm.empty else 0.0
    stats    = compute_stats(dfm, total)

    # ── Card total ──────────────────────────────────────────
    presup       = st.session_state.presupuesto.get(mes_sel, 0)
    presup_pct   = min(total / presup * 100, 100) if presup > 0 else 0
    presup_color = (THEME["primary"] if presup_pct < 80
                    else THEME["warning"] if presup_pct < 100
                    else THEME["danger"])

    st.markdown(f"""
        <div class="card">
          <div class="card-watermark">👛</div>
          <div class="card-title">TOTAL GASTADO · {mes_sel.upper()}</div>
          <div class="card-amount">S/ {total:,.2f}</div>
          {"" if not presup else f'<div class="card-sub">Presupuesto S/ {presup:,.0f} · {presup_pct:.0f}%</div>'}
        </div>
    """, unsafe_allow_html=True)

    if presup > 0:
        st.markdown(f"""
            <div class="budget-bar-bg">
              <div class="budget-bar-fill" style="width:{presup_pct:.1f}%;background:{presup_color};"></div>
            </div>
            <div class="budget-meta">
              <span class="budget-spent">S/ {total:,.2f} gastado</span>
              <span class="budget-remain" style="color:{presup_color};">S/ {max(presup-total,0):,.2f} restante</span>
            </div>
        """, unsafe_allow_html=True)

    # ── Stats ────────────────────────────────────────────────
    if stats:
        streak = days_without_expense(df)
        green  = "green" if streak > 0 else ""
        st.markdown(f"""
            <div class="stat-row">
              <div class="stat-pill">
                <div class="stat-label">Prom/día</div>
                <div class="stat-value">S/ {stats['avg_day']:,.0f}</div>
              </div>
              <div class="stat-pill">
                <div class="stat-label">Proyección</div>
                <div class="stat-value">S/ {stats['proj']:,.0f}</div>
              </div>
              <div class="stat-pill">
                <div class="stat-label">Gastos</div>
                <div class="stat-value">{stats['n_tx']}</div>
              </div>
              <div class="stat-pill">
                <div class="stat-label">🔥 Racha</div>
                <div class="stat-value {green}">{streak}d</div>
              </div>
            </div>
        """, unsafe_allow_html=True)

    # ── Acciones ─────────────────────────────────────────────
    st.write("")
    if not dfm.empty:
        ca, cb, _ = st.columns([2, 2, 4])
        with ca:
            st.download_button(
                "⬇️ CSV", data=export_csv(dfm),
                file_name=f"gastos_{mes_sel}_{anio_sel}.csv",
                mime="text/csv", type="secondary", use_container_width=True,
            )
        with cb:
            if st.button("🎯 Presupuesto", type="secondary", use_container_width=True):
                st.session_state.budget_mode = not st.session_state.budget_mode
                st.rerun()

    if st.session_state.budget_mode:
        with st.expander("🎯 Presupuesto mensual", expanded=True):
            bv = st.number_input(
                f"Presupuesto para {mes_sel} (S/)", min_value=0.0, step=50.0,
                value=float(st.session_state.presupuesto.get(mes_sel, 0)),
            )
            if st.button("Guardar presupuesto", type="primary"):
                st.session_state.presupuesto[mes_sel] = bv
                st.session_state.budget_mode = False
                st.toast(f"Presupuesto S/ {bv:,.0f} guardado 🎯")
                st.rerun()

    # ── Búsqueda ─────────────────────────────────────────────
    if not dfm.empty:
        st.markdown('<div class="section-title">BUSCAR</div>', unsafe_allow_html=True)
        sq = st.text_input("", value=st.session_state.search_query,
                           placeholder="Buscar por descripción o categoría…",
                           label_visibility="collapsed")
        st.session_state.search_query = sq
        if sq:
            mask = (
                dfm["DESCRIPCION"].str.contains(sq, case=False, na=False) |
                dfm["CATEGORÍA"].str.contains(sq, case=False, na=False)
            )
            dfm = dfm[mask]

    # ── Sin datos ─────────────────────────────────────────────
    if dfm.empty or total <= 0:
        st.markdown("""
            <div class="empty-state">
              <div class="empty-icon">🪴</div>
              <div class="empty-title">Sin gastos este mes</div>
              <div class="empty-sub">Presiona "➕ Nuevo gasto" para empezar.</div>
            </div>
        """, unsafe_allow_html=True)
        return

    # ── Distribución ─────────────────────────────────────────
    grp = (dfm.groupby("CATEGORÍA")["MONTO"].sum()
              .reset_index()
              .sort_values("MONTO", ascending=False))
    grp["PCT"] = grp["MONTO"] / total * 100

    st.markdown('<div class="section-title">DISTRIBUCIÓN</div>', unsafe_allow_html=True)
    cv1, cv2, _ = st.columns([2, 2, 4])
    with cv1:
        if st.button("Categorías", key="vc",
                     type="primary" if st.session_state.chart_mode == "Categorías" else "secondary",
                     use_container_width=True):
            st.session_state.chart_mode = "Categorías"; st.rerun()
    with cv2:
        if st.button("Histórico", key="vh",
                     type="primary" if st.session_state.chart_mode == "Histórico" else "secondary",
                     use_container_width=True):
            st.session_state.chart_mode = "Histórico"; st.rerun()

    st.write("")

    # ── Vista CATEGORÍAS ─────────────────────────────────────
    if st.session_state.chart_mode == "Categorías":
        top = grp.iloc[0]
        cc, cl = st.columns([1, 1], vertical_alignment="center")
        with cc:
            render_donut(grp, top["CATEGORÍA"], float(top["PCT"]))
        with cl:
            for _, r in grp.iterrows():
                color = COLORS_MAP.get(r["CATEGORÍA"], "#888")
                st.markdown(f"""
                    <div class="legend-row">
                      <div class="legend-left">
                        <div class="legend-dot" style="background:{color};box-shadow:0 0 6px {color};"></div>
                        <div class="legend-name">{r['CATEGORÍA']}</div>
                      </div>
                      <div class="legend-pct">{int(float(r['PCT'])+.5)}%</div>
                    </div>
                """, unsafe_allow_html=True)

        st.write("")
        st.markdown('<div class="section-title">DETALLE POR CATEGORÍA</div>', unsafe_allow_html=True)
        render_sort_bar()

        for _, r in grp.iterrows():
            cat     = r["CATEGORÍA"]
            amt     = float(r["MONTO"])
            pct     = float(r["PCT"])
            color   = COLORS_MAP.get(cat, "#888")
            icon    = ICON_MAP.get(cat, "•")
            details = apply_sort(dfm[dfm["CATEGORÍA"] == cat])

            with st.expander(f"{icon}  {cat}", expanded=(st.session_state.expanded_cat == cat)):
                st.markdown(f"""
                    <div class="rich-card">
                      <div class="rich-header">
                        <div class="rich-left">
                          <div class="rich-cat">{cat}</div>
                          <div class="rich-sub">{len(details)} MOVIMIENTOS</div>
                        </div>
                        <div class="rich-right">
                          <div class="rich-amt">S/ {amt:,.2f}</div>
                          <div class="rich-pct" style="color:{color};">{int(pct+.5)}%</div>
                        </div>
                      </div>
                      <div class="rich-bar-bg">
                        <div class="rich-bar-fill" style="width:{pct}%;background:{color};"></div>
                      </div>
                    </div>
                """, unsafe_allow_html=True)

                for _, d in details.iterrows():
                    dstr = d["FECHA"].strftime("%d/%m") if pd.notna(d["FECHA"]) else ""
                    desc = str(d.get("DESCRIPCION","")).strip() or cat
                    render_mov_item(desc, dstr, float(d.get("MONTO",0)),
                                    str(d.get("ID","")), f"c_{cat[:3]}")

    # ── Vista HISTÓRICO ──────────────────────────────────────
    else:
        ch1, ch2, ch3, _ = st.columns([1.5,1.5,1.5,2.5])
        for label, col in [("Diario",ch1),("Semanal",ch2),("Mensual",ch3)]:
            with col:
                if st.button(label, key=f"hm_{label}",
                             type="primary" if st.session_state.hist_mode == label else "secondary",
                             use_container_width=True):
                    st.session_state.hist_mode = label; st.rerun()

        st.write("")
        chart_df = filter_data(df, None, anio_sel) if st.session_state.hist_mode == "Mensual" else dfm
        render_history_chart(chart_df, st.session_state.hist_mode)

        st.markdown('<div class="section-title">MOVIMIENTOS</div>', unsafe_allow_html=True)
        render_sort_bar()
        for _, d in apply_sort(dfm).iterrows():
            cat  = d["CATEGORÍA"]
            dstr = d["FECHA"].strftime("%d/%m") if pd.notna(d["FECHA"]) else ""
            desc = str(d.get("DESCRIPCION","")).strip() or cat
            render_mov_item(desc, f"{cat} · {dstr}", float(d.get("MONTO",0)),
                            str(d.get("ID","")), "h")

    # ── Confirm delete ───────────────────────────────────────
    if st.session_state.confirm_delete:
        gid = st.session_state.confirm_delete

        @st.dialog("Confirmar eliminación")
        def confirm_dialog():
            st.markdown("¿Seguro que quieres **eliminar** este gasto?\nEsta acción no se puede deshacer.")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Cancelar", type="secondary", use_container_width=True):
                    st.session_state.confirm_delete = None; st.rerun()
            with c2:
                if st.button("Eliminar", type="primary", use_container_width=True):
                    ok, err = delete_from_sheet(gid)
                    st.session_state.confirm_delete = None
                    st.toast("Eliminado 🗑️" if ok else f"Error: {err}")
                    st.rerun()
        confirm_dialog()


# ============================================================
# 10) VISTA AÑADIR (con pantalla de preview)
# ============================================================
def add_view():
    # ── Preview / confirmación ───────────────────────────────
    if st.session_state.preview_data:
        pd_   = st.session_state.preview_data
        cat   = pd_["category"]
        amt   = pd_["amount"]
        desc  = pd_["description"]
        fecha = pd_["date"]
        color = COLORS_MAP.get(cat, "#888")
        icon  = ICON_MAP.get(cat, "•")

        cb, ct, _ = st.columns([1.2, 6, 1.2], vertical_alignment="center")
        with cb:
            if st.button("←", type="secondary"):
                st.session_state.preview_data = None; st.rerun()
        with ct:
            st.markdown("<div style='text-align:center;font-size:1.5rem;font-weight:900;'>Confirmar gasto</div>",
                        unsafe_allow_html=True)

        st.write("")
        st.markdown(f"""
            <div class="preview-card">
              <div class="preview-row">
                <span class="preview-label">Categoría</span>
                <span class="preview-value">{icon} {cat}</span>
              </div>
              <div class="preview-row">
                <span class="preview-label">Descripción</span>
                <span class="preview-value">{desc}</span>
              </div>
              <div class="preview-row">
                <span class="preview-label">Fecha</span>
                <span class="preview-value">{fecha.strftime('%d/%m/%Y')}</span>
              </div>
              <div class="preview-row">
                <span class="preview-label">Monto</span>
                <span class="preview-amount" style="color:{color};">S/ {amt:,.2f}</span>
              </div>
            </div>
        """, unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        with c1:
            if st.button("✏️ Editar", type="secondary", use_container_width=True):
                st.session_state.preview_data = None; st.rerun()
        with c2:
            if st.button("✅ Confirmar y guardar", type="primary", use_container_width=True):
                with st.spinner("Guardando…"):
                    ok, msg = save_to_sheet(pd_)
                if ok:
                    st.session_state.show_success = True
                    st.session_state.view = "main"
                    st.rerun()
                else:
                    st.error(f"❌ Error: {msg}")
        return

    # ── Formulario ───────────────────────────────────────────
    cb, ct, _ = st.columns([1.2, 6, 1.2], vertical_alignment="center")
    with cb:
        if st.button("←", type="secondary"):
            st.session_state.view = "main"; st.rerun()
    with ct:
        st.markdown("<div style='text-align:center;font-size:1.5rem;font-weight:900;'>Nuevo Gasto</div>",
                    unsafe_allow_html=True)

    st.write("")
    st.markdown("<div class='section-title' style='text-align:center;'>MONTO</div>", unsafe_allow_html=True)
    monto = st.number_input("Monto", min_value=0.0, step=1.0, label_visibility="collapsed")
    st.markdown(f"<div style='text-align:center;color:{THEME['muted']};margin-top:-8px;font-weight:800;'>soles</div>",
                unsafe_allow_html=True)

    st.write("")
    st.markdown("<div class='section-title' style='text-align:center;'>CATEGORÍA</div>", unsafe_allow_html=True)
    cats      = [f"{v[0]} {k}" for k, v in CATEGORIES.items()]
    cat_sel   = st.radio("Cat", cats, horizontal=True, label_visibility="collapsed")
    cat_clean = cat_sel.split(" ",1)[1] if " " in cat_sel else cat_sel
    if cat_clean not in VALID_CATS:
        cat_clean = "Otros"

    st.write("")
    st.markdown("<div class='section-title' style='text-align:center;'>FECHA</div>", unsafe_allow_html=True)
    fecha = st.date_input("Fecha", value=now_peru().date(), label_visibility="collapsed")

    st.write("")
    st.markdown("<div class='section-title' style='text-align:center;'>NOTA</div>", unsafe_allow_html=True)
    nota = st.text_input("Nota", placeholder="Descripción (opcional)…", label_visibility="collapsed")

    st.write("")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Cancelar", type="secondary", use_container_width=True):
            st.session_state.view = "main"; st.rerun()
    with c2:
        if st.button("Revisar →", type="primary", disabled=(monto <= 0), use_container_width=True):
            st.session_state.preview_data = {
                "date":        dt.datetime.combine(fecha, dt.time()),
                "amount":      float(monto),
                "category":    cat_clean,
                "description": nota.strip() or cat_clean,
            }
            st.rerun()


# ============================================================
# 11) ENTRY POINT
# ============================================================
inject_css()
try:
    if st.session_state.view == "main":
        main_view()
    else:
        add_view()
except Exception:
    st.error("Error fatal en la app")
    st.code(traceback.format_exc())
