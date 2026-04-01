# ============================================================
# GESTOR DE GASTOS v3.1
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
# Mejoras v3.1:
#   - Presupuesto persistente en Google Sheets (tab "Presupuesto")
#   - Botón "➕ Nuevo gasto" flotante en móvil (siempre visible)
#   - Chips de categoría más grandes y táctiles en iPhone
#   - Alerta visual al superar 80% / 100% del presupuesto
#   - Racha corregida: días CON gasto consecutivos (gastos hormiga)
#   - Teclado numérico en monto al abrir formulario (inputmode)
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

# ── Meta tags PWA (iPhone "Añadir a pantalla de inicio") ──
st.markdown("""
<head>
  <!-- PWA: se ve como app nativa en iPhone -->
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="Gastos">
  <meta name="theme-color" content="#000000">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <!-- Ícono para pantalla de inicio iPhone -->
  <link rel="apple-touch-icon" href="https://em-content.zobj.net/source/apple/354/money-bag_1f4b0.png">
</head>
""", unsafe_allow_html=True)

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
    "show_picker":     False,
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ============================================================
# 4) CSS
# ============================================================
def inject_css():
    primary = THEME["primary"]
    # CSS base — no f-string para evitar conflictos con llaves CSS
    css = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@500;700&display=swap');

html, body, [class*="css"] {
  font-family: 'Inter', -apple-system, sans-serif !important;
  color: #e0e0e0 !important;
  -webkit-font-smoothing: antialiased !important;
}
html, body { background: #040404 !important; overflow-x: hidden !important; }
.stApp { background: #040404 !important; }
.block-container {
  max-width: 800px !important;
  padding: max(20px, env(safe-area-inset-top)) 18px max(100px, env(safe-area-inset-bottom)) 18px !important;
}
#MainMenu, header, footer,
div[data-testid="stToolbar"],
div[data-testid="stDecoration"],
div[data-testid="stStatusWidget"] {
  display: none !important; visibility: hidden !important; height: 0 !important;
}
button {
  font-family: 'Inter', sans-serif !important;
  border-radius: 13px !important;
  letter-spacing: -.1px !important;
  transition: all .14s cubic-bezier(.4,0,.2,1) !important;
}
button[kind="primary"] {
  background: #00E054 !important; color: #000 !important; border: none !important;
  font-weight: 700 !important; font-size: .92rem !important; height: 50px !important;
}
button[kind="primary"]:hover {
  filter: brightness(1.08) !important;
  box-shadow: 0 6px 22px rgba(0,224,84,.25) !important;
  transform: translateY(-1px) !important;
}
button[kind="primary"]:active  { transform: scale(.97) !important; }
button[kind="primary"]:disabled { background: #141414 !important; color: #2a2a2a !important; }
button[kind="secondary"] {
  background: #0c0c0c !important; border: 1px solid #1a1a1a !important;
  color: #555 !important; font-weight: 600 !important;
  height: 42px !important; font-size: .82rem !important;
}
button[kind="secondary"]:hover {
  background: #111 !important; border-color: #242424 !important; color: #aaa !important;
}
div[data-baseweb="select"] > div {
  background: #0c0c0c !important; border: 1px solid #1a1a1a !important; border-radius: 12px !important;
}
div[data-baseweb="menu"], div[data-baseweb="popover"],
ul[data-testid="stSelectboxVirtualDropdown"] {
  background: #0e0e0e !important; border: 1px solid #1a1a1a !important; border-radius: 12px !important;
}
li[role="option"] { color: #999 !important; font-size: .88rem !important; }
li[role="option"][aria-selected="true"] { background: #141414 !important; color: #00E054 !important; }
input[type="text"], div[data-testid="stTextInput"] input {
  background: #0c0c0c !important; border: 1px solid #1a1a1a !important;
  border-radius: 12px !important; color: #ddd !important;
  padding: 13px 16px !important; font-size: .88rem !important;
  font-family: 'Inter', sans-serif !important;
  transition: border-color .15s ease, box-shadow .15s ease !important;
}
input[type="text"]:focus, div[data-testid="stTextInput"] input:focus {
  border-color: rgba(0,224,84,.3) !important;
  box-shadow: 0 0 0 3px rgba(0,224,84,.06) !important;
  outline: none !important;
}
input[type="text"]::placeholder,
div[data-testid="stTextInput"] input::placeholder { color: #252525 !important; }
/* Monto input — grande y centrado */
div[data-testid="stTextInput"]:has([placeholder="0.00"]) input {
  font-size: clamp(2.2rem, 8vw, 3.5rem) !important;
  font-weight: 800 !important;
  font-family: 'JetBrains Mono', monospace !important;
  text-align: center !important;
  letter-spacing: -1.5px !important;
  color: #f0f0f0 !important;
  border-radius: 18px !important;
  padding: 20px 16px !important;
  caret-color: #00E054 !important;
}
div[data-testid="stNumberInput"] {
  background: transparent !important; border: none !important;
  width: 100% !important;
}
div[data-testid="stNumberInput"] > div {
  background: transparent !important; border: none !important;
  width: 100% !important; gap: 0 !important;
}
div[data-testid="stNumberInput"] input {
  background: transparent !important; border: none !important;
  color: #fff !important;
  font-size: clamp(2.8rem, 11vw, 4.5rem) !important;
  font-weight: 800 !important;
  font-family: 'JetBrains Mono', monospace !important;
  text-align: center !important; padding: 4px 0 !important;
  caret-color: #00E054 !important; letter-spacing: -2px !important;
  box-shadow: none !important; width: 100% !important;
  -webkit-appearance: none !important;
}
div[data-testid="stNumberInput"] input:focus {
  border: none !important; box-shadow: none !important; outline: none !important;
  background: transparent !important;
}
/* Ocultar flechas +/- del number input */
div[data-testid="stNumberInput"] button,
div[data-testid="stNumberInput"] > div > div:last-child,
div[data-testid="stNumberInput"] [data-testid="stNumberInputStepDown"],
div[data-testid="stNumberInput"] [data-testid="stNumberInputStepUp"] {
  display: none !important;
}
/* Fix fondo azul oscuro del contenedor Streamlit */
div[data-testid="stNumberInput"] > div > div:first-child {
  background: transparent !important; border: none !important; box-shadow: none !important;
}
div[role="radiogroup"] {
  display: flex; flex-wrap: wrap; gap: 6px; justify-content: center;
  width: 100% !important; margin: 0 auto !important;
}
/* Centrar el contenedor padre que Streamlit agrega */
div[data-testid="stRadio"] > div {
  display: flex !important;
  justify-content: center !important;
  width: 100% !important;
}
div[data-testid="stRadio"] {
  width: 100% !important;
}
div[role="radiogroup"] label {
  background: #0c0c0c !important; border: 1px solid #181818 !important;
  border-radius: 11px !important; padding: 10px 15px !important;
  cursor: pointer; transition: all .12s ease;
  min-height: 44px !important; display: flex !important; align-items: center !important;
}
div[role="radiogroup"] label p {
  color: #444 !important; font-weight: 600 !important; font-size: .83rem !important;
  margin: 0 !important; font-family: 'Inter', sans-serif !important;
  white-space: nowrap !important; transition: color .12s ease;
}
div[role="radiogroup"] label:hover { background: #111 !important; border-color: #222 !important; }
div[role="radiogroup"] label:hover p { color: #aaa !important; }
div[role="radiogroup"] label:has(input:checked) {
  background: rgba(0,224,84,.08) !important; border-color: rgba(0,224,84,.25) !important;
}
div[role="radiogroup"] label:has(input:checked) p { color: #00E054 !important; font-weight: 700 !important; }
div[role="radiogroup"] label > div:first-child { display: none; }
@media (max-width: 599px) {
  div[role="radiogroup"] {
    display: grid !important;
    grid-template-columns: 1fr 1fr !important;
    gap: 6px !important;
    width: 100% !important;
    margin: 0 auto !important;
    padding: 0 !important;
  }
  div[role="radiogroup"] label {
    justify-content: center !important; text-align: center !important;
    min-height: 48px !important; border-radius: 13px !important;
    width: 100% !important;
  }
  div[role="radiogroup"] label p { font-size: .85rem !important; }
  button[kind="secondary"] { height: 40px !important; font-size: .78rem !important; }
  button[kind="primary"]   { height: 50px !important; }
  .block-container { padding-left: 13px !important; padding-right: 13px !important; }
  .card { border-radius: 19px !important; padding: 20px 16px 17px !important; }
  .card-amount { letter-spacing: -2px !important; }
  .mov-item { padding: 12px 12px !important; border-radius: 12px !important; }
  .stat-pill { padding: 11px 11px 9px !important; border-radius: 13px !important; }
  .amount-hero { border-radius: 17px !important; }
}
.badge {
  display: inline-flex; align-items: center; gap: 7px; padding: 5px 11px 5px 8px;
  border-radius: 999px; background: #080808; border: 1px solid #161616;
  color: #2a2a2a !important; font-weight: 600; font-size: .68rem;
  letter-spacing: 1.8px; text-transform: uppercase;
}
.badge-dot {
  width: 5px; height: 5px; border-radius: 50%; background: #00E054;
  box-shadow: 0 0 6px #00E054; flex-shrink: 0;
}
.greeting {
  font-size: clamp(1.65rem, 5vw, 2rem); font-weight: 800; line-height: 1.2;
  color: #e8e8e8; margin: 8px 0 14px; letter-spacing: -.5px;
}
.card {
  background: #0c0c0c !important; border: 1px solid #151515 !important;
  border-radius: 22px !important; padding: 26px 22px 22px !important;
  position: relative; overflow: hidden; margin-top: 6px;
  display: flex !important; flex-direction: column !important; align-items: center !important;
}
.card::before {
  content: ''; position: absolute; top: 0; left: 50%; transform: translateX(-50%);
  width: 40%; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(0,224,84,.18), transparent);
}
.card::after {
  content: ''; position: absolute; top: 35%; left: 50%; transform: translate(-50%,-50%);
  width: 55%; height: 70px;
  background: radial-gradient(ellipse, rgba(0,224,84,.035) 0%, transparent 70%);
  pointer-events: none;
}
.card-title {
  color: #242424 !important; font-size: .65rem !important; letter-spacing: 3px !important;
  text-transform: uppercase !important; margin-bottom: 8px !important; font-weight: 600 !important;
}
.card-amount-wrap { display: flex; align-items: baseline; gap: 5px; position: relative; z-index: 1; }
.card-currency {
  font-size: clamp(1rem, 2.5vw, 1.3rem); font-weight: 600; color: #252525;
  font-family: 'JetBrains Mono', monospace;
}
.card-amount {
  font-size: clamp(2.6rem, 9vw, 3.8rem) !important; font-weight: 800 !important;
  color: #f0f0f0 !important; font-family: 'JetBrains Mono', monospace !important;
  letter-spacing: -2.5px !important; line-height: 1 !important;
}
.card-sub {
  color: #222 !important; font-size: .72rem !important;
  font-weight: 500 !important; margin-top: 10px !important;
}
.card-sub span { color: #2d6644; font-weight: 600; }
.budget-wrap { margin-top: 10px; padding: 0 2px; }
.budget-bar-bg { width: 100%; height: 3px; background: #141414; border-radius: 99px; overflow: hidden; }
.budget-bar-fill { height: 100%; border-radius: 99px; transition: width .8s cubic-bezier(.4,0,.2,1); }
.budget-meta { display: flex; justify-content: space-between; margin-top: 6px; }
.budget-spent  { color: #242424; font-size: .7rem; font-weight: 500; }
.budget-remain { font-size: .7rem; font-weight: 600; }
.budget-alert {
  border-radius: 11px; padding: 10px 13px; margin-top: 9px;
  font-weight: 600; font-size: .8rem; display: flex; align-items: center; gap: 8px;
  animation: fadeUp .25s ease forwards;
}
.budget-alert.warn   { background: rgba(200,140,0,.06); border: 1px solid rgba(200,140,0,.14); color: #8a6500; }
.budget-alert.danger { background: rgba(200,50,50,.06);  border: 1px solid rgba(200,50,50,.16);  color: #903030; }
.stat-row { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-top: 8px; }
@media (min-width: 600px) { .stat-row { grid-template-columns: repeat(4, 1fr); } }
.stat-pill {
  background: #080808; border: 1px solid #141414; border-radius: 15px;
  padding: 13px 13px 11px; display: flex; flex-direction: column; gap: 6px;
}
.stat-label { color: #222; font-size: .63rem; font-weight: 600; letter-spacing: 2px; text-transform: uppercase; }
.stat-value { color: #b0b0b0; font-size: 1rem; font-weight: 700; font-family: 'JetBrains Mono', monospace; letter-spacing: -.4px; }
.stat-value.streak { color: #00E054; font-size: 1.1rem; }
.month-nav { display: flex; align-items: center; justify-content: center; padding: 4px 0 0; }
.month-nav-label { font-size: .98rem; font-weight: 700; color: #bbb; text-align: center; }
.month-label     { font-size: .98rem; font-weight: 700; color: #bbb; text-align: center; }
.section-title {
  color: #1e1e1e !important; font-weight: 600; font-size: .63rem;
  letter-spacing: 3px; margin-top: 20px; margin-bottom: 8px; text-transform: uppercase;
}
div[data-testid="stExpander"] {
  background: #0c0c0c !important; border: 1px solid #151515 !important;
  border-radius: 17px !important; overflow: hidden; margin-bottom: 5px !important;
}
div[data-testid="stExpander"]:hover { border-color: #1e1e1e !important; }
div[data-testid="stExpander"] details { background: #0c0c0c !important; }
div[data-testid="stExpander"] summary {
  padding: 15px 17px !important; background: #0c0c0c !important; min-height: 52px !important;
}
div[data-testid="stExpander"] summary:hover { background: #0f0f0f !important; }
div[data-testid="stExpander"] summary p { font-weight: 700 !important; font-size: .88rem !important; color: #aaa !important; }
div[data-testid="stExpander"] summary svg { width: 17px !important; height: 17px !important; color: #2a2a2a !important; }
.mov-item {
  background: #0c0c0c; border: 1px solid #151515; border-radius: 13px;
  padding: 13px 15px; margin-bottom: 4px;
  display: flex; justify-content: space-between; align-items: center;
  transition: border-color .12s ease;
}
.mov-item:hover { border-color: #1e1e1e; }
.mov-left { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
.mov-cat  { font-weight: 600; font-size: .88rem; color: #bbb; }
.mov-desc { color: #242424; font-size: .75rem; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 380px; }
.mov-right { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; }
.mov-amt  { font-weight: 700; color: #00E054; white-space: nowrap; font-family: 'JetBrains Mono', monospace; font-size: .86rem; letter-spacing: -.3px; }
.mov-date { font-size: .66rem; color: #202020; font-weight: 500; }
.legend-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #0f0f0f; }
.legend-row:last-child { border-bottom: none; }
.legend-left { display: flex; align-items: center; gap: 8px; }
.legend-dot  { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.legend-name { color: #777; font-weight: 600; font-size: .82rem; }
.legend-pct  { color: #2e2e2e; font-weight: 600; font-size: .8rem; font-family: 'JetBrains Mono', monospace; }
.rich-card   { padding-bottom: 12px; margin-bottom: 12px; border-bottom: 1px solid #101010; }
.rich-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 7px; }
.rich-left   { display: flex; flex-direction: column; gap: 3px; }
.rich-right  { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; }
.rich-cat    { font-size: .88rem; font-weight: 700; color: #aaa; }
.rich-sub    { font-size: .65rem; font-weight: 600; color: #252525; text-transform: uppercase; letter-spacing: 1px; }
.rich-amt    { font-size: 1rem; font-weight: 700; color: #ccc; font-family: 'JetBrains Mono', monospace; letter-spacing: -.5px; }
.rich-pct    { font-size: .75rem; font-weight: 700; }
.rich-bar-bg  { width: 100%; height: 3px; background: #111; border-radius: 99px; margin-top: 7px; overflow: hidden; }
.rich-bar-fill { height: 100%; border-radius: 99px; opacity: .65; }
.amount-hero {
  background: #0c0c0c; border: 1px solid #151515; border-radius: 20px;
  padding: 22px 20px 16px; text-align: center; position: relative; overflow: hidden;
}
.amount-hero::before {
  content: ''; position: absolute; bottom: 0; left: 50%; transform: translateX(-50%);
  width: 35%; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(0,224,84,.12), transparent);
}
.amount-currency-label { font-size: .63rem; font-weight: 600; color: #242424; letter-spacing: 3px; text-transform: uppercase; }
.amount-hint           { font-size: .7rem; color: #1e1e1e; font-weight: 500; margin-top: 4px; }
.amount-hint.has-value { color: #1e4a2e; }
.cat-section-label  { font-size: .63rem; font-weight: 600; color: #1e1e1e; letter-spacing: 3px; text-transform: uppercase; text-align: center; margin: 18px 0 9px; }
.form-field-label   { font-size: .63rem; font-weight: 600; color: #1e1e1e; letter-spacing: 3px; text-transform: uppercase; text-align: center; margin: 16px 0 7px; }
.preview-card { background: #0c0c0c; border: 1px solid #151515; border-radius: 18px; padding: 18px; margin: 14px 0; }
.preview-amount-big { text-align: center; font-size: clamp(2.2rem, 7vw, 3rem); font-weight: 800; font-family: 'JetBrains Mono', monospace; letter-spacing: -2px; margin-bottom: 18px; line-height: 1; }
.preview-row   { display: flex; justify-content: space-between; align-items: center; padding: 9px 0; border-bottom: 1px solid #101010; }
.preview-row:last-child { border-bottom: none; }
.preview-label { color: #242424; font-size: .65rem; font-weight: 600; text-transform: uppercase; letter-spacing: 1.8px; }
.preview-value { color: #888; font-weight: 600; font-size: .86rem; }
@keyframes fadeUp { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
.success-flash  { position: fixed; inset: 0; z-index: 9999; pointer-events: none; background: radial-gradient(ellipse at 50% 0%, rgba(0,224,84,.04) 0%, transparent 60%); animation: fadeUp .3s ease forwards; }
.success-banner { background: #090e0b; border: 1px solid #121c14; border-radius: 14px; padding: 14px 16px; display: flex; align-items: center; gap: 12px; margin-bottom: 12px; animation: fadeUp .35s ease forwards; }
.success-icon   { font-size: 1.6rem; }
.success-title  { font-weight: 700; color: #00E054; font-size: .88rem; margin-bottom: 2px; }
.success-sub    { font-size: .75rem; color: #162a1c; font-weight: 500; }
@keyframes shimmer { 0% { background-position: -700px 0; } 100% { background-position: 700px 0; } }
.skeleton      { background: linear-gradient(90deg, #0a0a0a 25%, #121212 50%, #0a0a0a 75%); background-size: 700px 100%; animation: shimmer 1.8s infinite linear; border-radius: 13px; }
.skeleton-card { height: 148px; margin-bottom: 7px; border-radius: 22px; }
.skeleton-pill { height: 70px; flex: 1; border-radius: 15px; }
.skeleton-row  { height: 58px; margin-bottom: 4px; border-radius: 13px; }
.sort-label    { color: #1e1e1e; font-size: .63rem; font-weight: 600; letter-spacing: 2px; text-transform: uppercase; padding-top: 10px; }
div[data-testid="stToast"] { background: #0e0e0e !important; border: 1px solid #1a1a1a !important; color: #bbb !important; border-radius: 11px !important; box-shadow: 0 8px 28px rgba(0,0,0,.55) !important; }
div[data-testid="stToast"] p, div[data-testid="stToast"] svg { color: #bbb !important; fill: #bbb !important; }
.empty-state { text-align: center; padding: 60px 24px; }
.empty-icon  { font-size: 2.8rem; margin-bottom: 12px; opacity: .35; }
.empty-title { font-size: .95rem; font-weight: 700; color: #1e1e1e; margin-bottom: 5px; }
.empty-sub   { font-size: .8rem; color: #161616; font-weight: 500; }
"""
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


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
# 5b) PRESUPUESTO PERSISTENTE (tab "Presupuesto" en el Sheet)
# ============================================================
BUDGET_SHEET = "Presupuesto"   # nombre de la segunda hoja


def _get_budget_sheet():
    """Devuelve la hoja Presupuesto, creándola si no existe."""
    client = get_client()
    if not client:
        return None
    try:
        ss = client.open(SHEET_NAME)
        try:
            return ss.worksheet(BUDGET_SHEET)
        except Exception:
            ws = ss.add_worksheet(title=BUDGET_SHEET, rows=50, cols=4)
            ws.update("A1:D1", [["AÑO", "MES", "PRESUPUESTO", "UPDATED"]])
            return ws
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def load_budgets() -> dict:
    """Carga todos los presupuestos → {(año, mes): valor}."""
    ws = _get_budget_sheet()
    if not ws:
        return {}
    try:
        rows = ws.get_all_records()
        out  = {}
        for r in rows:
            try:
                anio = int(r.get("AÑO", 0))
                mes  = str(r.get("MES", "")).strip()
                val  = float(r.get("PRESUPUESTO", 0))
                if anio > 0 and mes and val > 0:
                    out[(anio, mes)] = val
            except Exception:
                pass
        return out
    except Exception:
        return {}


def save_budget(anio: int, mes: str, valor: float):
    """Guarda o actualiza el presupuesto de un mes/año en Sheets."""
    ws = _get_budget_sheet()
    if not ws:
        return False
    try:
        rows   = ws.get_all_values()
        header = [h.upper() for h in rows[0]] if rows else []
        # Buscar fila existente
        for i, row in enumerate(rows[1:], start=2):
            if len(row) >= 3:
                try:
                    if int(row[0]) == anio and row[1].strip() == mes:
                        ws.update(f"C{i}:D{i}", [[valor, dt.datetime.now().strftime("%Y-%m-%d %H:%M")]])
                        load_budgets.clear()
                        return True
                except Exception:
                    pass
        # Fila nueva
        ws.append_row([anio, mes, valor, dt.datetime.now().strftime("%Y-%m-%d %H:%M")])
        load_budgets.clear()
        return True
    except Exception:
        return False


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


def days_with_expense_streak(df: pd.DataFrame) -> int:
    """Racha: días CONSECUTIVOS con al menos un gasto (hasta hoy)."""
    if df.empty:
        return 0
    today = now_peru().date()
    dates = set(df["FECHA"].dropna().dt.date.unique())
    streak = 0
    d = today
    while d in dates:
        streak += 1
        d -= dt.timedelta(days=1)
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
    """Donut SVG con stroke-dasharray — geometría correcta garantizada."""
    import math
    size = 200
    cx = cy = size / 2
    r = 72
    circumference = 2 * math.pi * r

    total_val = float(grp_df["MONTO"].sum())
    circles   = []
    offset    = circumference * 0.25  # start from top

    for _, row in grp_df.iterrows():
        cat   = row["CATEGORÍA"]
        pct   = float(row["MONTO"]) / total_val if total_val > 0 else 0
        dash  = pct * circumference
        color = COLORS_MAP.get(cat, "#555")
        circles.append((dash, offset, color))
        offset += dash  # next slice starts where this ends (wrap handled by SVG)

    rings_svg = ""
    for dash, off, color in circles:
        gap = circumference - dash
        rings_svg += (
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
            f'stroke="{color}" stroke-width="28" stroke-opacity="0.92" '
            f'stroke-dasharray="{dash:.2f} {gap:.2f}" '
            f'stroke-dashoffset="-{off:.2f}" '
            f'transform="rotate(-90 {cx} {cy})"/>\n'
        )

    label_short = center_cat[:9] + "…" if len(center_cat) > 9 else center_cat
    color_pct   = COLORS_MAP.get(center_cat, "#00E054")

    svg = f"""<div style="width:100%;max-width:200px;margin:0 auto;">
<svg viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg" style="width:100%;display:block;">
  <circle cx="{cx}" cy="{cy}" r="{r + 16}" fill="#080808"/>
  {rings_svg}
  <circle cx="{cx}" cy="{cy}" r="{r - 15}" fill="#060606"/>
  <text x="{cx}" y="{cy - 22}" text-anchor="middle"
        font-size="9" font-weight="700" fill="#777"
        font-family="Inter,sans-serif" letter-spacing="2">{label_short.upper()}</text>
  <text x="{cx}" y="{cy + 18}" text-anchor="middle"
        font-size="36" font-weight="800" fill="#f0f0f0"
        font-family="'JetBrains Mono',monospace">{int(center_pct)}<tspan font-size="15" fill="{color_pct}" font-weight="700">%</tspan></text>
</svg></div>"""
    st.markdown(svg, unsafe_allow_html=True)


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
              <div class="mov-right">
                <div class="mov-amt">S/ {amt:,.2f}</div>
              </div>
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
    st.markdown(
        f'<div class="badge"><span class="badge-dot"></span>{date_display}</div>'
        f'<div class="greeting">Hola, Andrés 👋</div>',
        unsafe_allow_html=True,
    )
    if st.button("➕  Nuevo gasto", type="primary", use_container_width=True, key="btn_nuevo_top"):
        st.session_state.view = "add"
        st.rerun()

    st.write("")

    # ── Navegación mes ───────────────────────────────────────
    st.markdown(f"""
        <div style="text-align:center;font-size:.98rem;font-weight:700;
             color:#bbb;padding:8px 0 6px;letter-spacing:-.2px;">
          {st.session_state.sel_month} {st.session_state.sel_year}
        </div>
    """, unsafe_allow_html=True)
    cn1, cn2, cn3 = st.columns([2, 2, 1])
    with cn1:
        if st.button("‹  Anterior", key="pm", type="secondary", use_container_width=True):
            prev_month(); st.rerun()
    with cn2:
        if st.button("Siguiente  ›", key="nm", type="secondary", use_container_width=True):
            next_month(); st.rerun()
    with cn3:
        if st.button("📅", key="openpick", type="secondary", use_container_width=True):
            st.session_state.show_picker = not st.session_state.get("show_picker", False)
            st.rerun()

    # Picker año+mes — aparece debajo cuando se abre
    if st.session_state.get("show_picker", False):
        with st.container():
            # Selector de año
            py1, py2, py3 = st.columns([1, 3, 1])
            with py1:
                if st.button("‹", key="py", type="secondary", use_container_width=True):
                    st.session_state.sel_year -= 1; st.rerun()
            with py2:
                st.markdown(
                    f"<div style='text-align:center;font-weight:900;font-size:1.1rem;padding-top:6px;'>{st.session_state.sel_year}</div>",
                    unsafe_allow_html=True)
            with py3:
                if st.button("›", key="ny", type="secondary", use_container_width=True):
                    st.session_state.sel_year += 1; st.rerun()

            st.write("")
            # Grid 3x4 de meses — siempre 3 columnas
            abbrs = ["ENE","FEB","MAR","ABR","MAY","JUN","JUL","AGO","SEP","OCT","NOV","DIC"]
            for row in [abbrs[i:i+3] for i in range(0, 12, 3)]:
                cols = st.columns(3)
                for i, abbr in enumerate(row):
                    full = MESES_ORD[abbrs.index(abbr)]
                    with cols[i]:
                        t = "primary" if full == st.session_state.sel_month else "secondary"
                        if st.button(abbr, key=f"mp_{abbr}", type=t, use_container_width=True):
                            st.session_state.sel_month = full
                            st.session_state.show_picker = False
                            st.rerun()

    mes_sel  = st.session_state.sel_month
    anio_sel = st.session_state.sel_year
    dfm      = filter_data(df, mes_sel, anio_sel)
    total    = float(dfm["MONTO"].sum()) if not dfm.empty else 0.0
    stats    = compute_stats(dfm, total)

    # ── Cargar presupuesto persistente ──────────────────────
    budgets = load_budgets()
    presup  = budgets.get((anio_sel, mes_sel), 0.0)
    presup_pct   = min(total / presup * 100, 100) if presup > 0 else 0
    presup_color = (THEME["primary"] if presup_pct < 80
                    else THEME["warning"] if presup_pct < 100
                    else THEME["danger"])

    st.markdown(f"""
        <div class="card">
          <div class="card-title">TOTAL GASTADO · {mes_sel.upper()}</div>
          <div class="card-amount-wrap">
            <span class="card-currency">S/</span>
            <span class="card-amount">{total:,.2f}</span>
          </div>
          {"" if not presup else f'<div class="card-sub">de S/ {presup:,.0f} presupuestado · <span style="color:{"#00E054" if presup_pct < 80 else "#FFC700" if presup_pct < 100 else "#FF4B4B"}">{presup_pct:.0f}%</span></div>'}
        </div>
    """, unsafe_allow_html=True)

    if presup > 0:
        st.markdown(f"""
            <div class="budget-wrap">
              <div class="budget-bar-bg">
                <div class="budget-bar-fill" style="width:{presup_pct:.1f}%;background:{presup_color};"></div>
              </div>
              <div class="budget-meta">
                <span class="budget-spent">S/ {total:,.2f} gastado</span>
                <span class="budget-remain" style="color:{presup_color};">S/ {max(presup-total,0):,.2f} restante</span>
              </div>
            </div>
        """, unsafe_allow_html=True)

    # ── Stats ────────────────────────────────────────────────
    if stats:
        streak     = days_with_expense_streak(df)
        streak_cls = "streak" if streak > 0 else ""
        st.markdown(f"""
            <div class="stat-row">
              <div class="stat-pill">
                <div class="stat-label">Prom / día</div>
                <div class="stat-value">S/ {stats['avg_day']:,.0f}</div>
              </div>
              <div class="stat-pill">
                <div class="stat-label">Proyección</div>
                <div class="stat-value">S/ {stats['proj']:,.0f}</div>
              </div>
              <div class="stat-pill">
                <div class="stat-label">Movimientos</div>
                <div class="stat-value">{stats['n_tx']}</div>
              </div>
              <div class="stat-pill">
                <div class="stat-label">🔥 Racha</div>
                <div class="stat-value {streak_cls}">{streak}d</div>
              </div>
            </div>
        """, unsafe_allow_html=True)

    # ── Alerta presupuesto ──────────────────────────────────
    if presup > 0:
        if presup_pct >= 100:
            st.markdown(
                f'<div class="budget-alert danger">🚨 Superaste el presupuesto de S/ {presup:,.0f} — llevas S/ {total:,.2f}</div>',
                unsafe_allow_html=True,
            )
        elif presup_pct >= 80:
            st.markdown(
                f'<div class="budget-alert warn">⚠️ Ya usaste el {presup_pct:.0f}% — te quedan S/ {max(presup-total,0):,.2f}</div>',
                unsafe_allow_html=True,
            )

    # ── Acciones secundarias — compactas ────────────────────
    if not dfm.empty:
        st.markdown('<div class="section-title">ACCIONES</div>', unsafe_allow_html=True)
        ca, cb, cc = st.columns([1, 1, 2])
        with ca:
            st.download_button(
                "⬇️ CSV", data=export_csv(dfm),
                file_name=f"gastos_{mes_sel}_{anio_sel}.csv",
                mime="text/csv", type="secondary", use_container_width=True,
            )
        with cb:
            lbl = "🎯 Presupuesto" if not st.session_state.budget_mode else "✕ Cerrar"
            if st.button(lbl, type="secondary", use_container_width=True):
                st.session_state.budget_mode = not st.session_state.budget_mode
                st.rerun()

    if st.session_state.budget_mode:
        with st.expander("🎯 Presupuesto mensual", expanded=True):
            bv = st.number_input(
                f"Presupuesto para {mes_sel} {anio_sel} (S/)", min_value=0.0, step=50.0,
                value=float(presup),
            )
            if st.button("Guardar presupuesto", type="primary"):
                with st.spinner("Guardando en la nube…"):
                    ok = save_budget(anio_sel, mes_sel, bv)
                st.session_state.budget_mode = False
                if ok:
                    st.toast(f"Presupuesto S/ {bv:,.0f} guardado 🎯")
                else:
                    st.toast("⚠️ No se pudo guardar en Sheets — revisa la conexión")
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

    # ── Tabs distribución — compactos ───────────────────────
    st.markdown('<div class="section-title">DISTRIBUCIÓN</div>', unsafe_allow_html=True)
    cv1, cv2, cv3 = st.columns([1, 1, 1])
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
    with cv3:
        pass

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
    # Header con botón volver
    cb, ct, _ = st.columns([1, 5, 1], vertical_alignment="center")
    with cb:
        if st.button("←", type="secondary", use_container_width=True):
            st.session_state.view = "main"; st.rerun()
    with ct:
        st.markdown(
            "<div style='text-align:center;font-size:1rem;font-weight:700;color:#666;letter-spacing:-.2px;'>Nuevo Gasto</div>",
            unsafe_allow_html=True)

    # ── Monto ────────────────────────────────────────────────
    st.markdown("""
        <div style='text-align:center;font-size:.63rem;font-weight:600;color:#242424;
             letter-spacing:3px;text-transform:uppercase;margin:20px 0 10px;'>MONTO</div>
    """, unsafe_allow_html=True)

    monto_str = st.text_input(
        "Monto", value="0",
        label_visibility="collapsed",
        placeholder="0.00",
        key="monto_input"
    )
    # Parse monto safely
    try:
        monto = max(0.0, float(monto_str.replace(",", ".")))
    except (ValueError, AttributeError):
        monto = 0.0

    st.markdown(
        f"<div style='text-align:center;color:#252525;font-size:.72rem;font-weight:600;"
        f"letter-spacing:2px;text-transform:uppercase;margin-top:4px;margin-bottom:20px;'>SOLES</div>",
        unsafe_allow_html=True)

    # ── Categoría ────────────────────────────────────────────
    st.markdown("""
        <div style='text-align:center;font-size:.63rem;font-weight:600;color:#242424;
             letter-spacing:3px;text-transform:uppercase;margin-bottom:10px;'>CATEGORÍA</div>
    """, unsafe_allow_html=True)

    CAT_SHORT = {
        "Alimentación": "🍽️ Comida",   "Transporte": "🚗 Transporte",
        "Salud":        "💊 Salud",      "Trabajo":    "💼 Trabajo",
        "Ocio":         "🎵 Ocio",       "Casa":       "🏠 Casa",
        "Inversión":    "📈 Inversión",  "Pareja":     "❤️ Pareja",
        "Estudios":     "📚 Estudios",   "Viaje":      "✈️ Viaje",
        "Frutas":       "🍎 Frutas",     "Golosinas":  "🍬 Dulces",
        "Compras Generales": "🛒 Compras", "Otros":    "📦 Otros",
    }
    cats_display = list(CAT_SHORT.values())
    cats_keys    = list(CAT_SHORT.keys())
    cat_sel_disp = st.radio("Cat", cats_display, horizontal=True, label_visibility="collapsed")
    cat_clean    = cats_keys[cats_display.index(cat_sel_disp)] if cat_sel_disp in cats_display else "Otros"
    if cat_clean not in VALID_CATS:
        cat_clean = "Otros"

    # ── Fecha ────────────────────────────────────────────────
    st.markdown("""
        <div style='text-align:center;font-size:.63rem;font-weight:600;color:#242424;
             letter-spacing:3px;text-transform:uppercase;margin:20px 0 8px;'>FECHA</div>
    """, unsafe_allow_html=True)
    fecha = st.date_input("Fecha", value=now_peru().date(), label_visibility="collapsed")

    # ── Nota ─────────────────────────────────────────────────
    st.markdown("""
        <div style='text-align:center;font-size:.63rem;font-weight:600;color:#242424;
             letter-spacing:3px;text-transform:uppercase;margin:16px 0 8px;'>NOTA</div>
    """, unsafe_allow_html=True)
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

# Forzar teclado numérico en iPhone para campos de monto
st.markdown("""
<script>
(function() {
  function patchInputs() {
    document.querySelectorAll('input[type="number"]').forEach(function(el) {
      el.setAttribute('inputmode', 'decimal');
      el.setAttribute('pattern', '[0-9]*');
    });
  }
  patchInputs();
  var obs = new MutationObserver(patchInputs);
  obs.observe(document.body, { childList: true, subtree: true });
})();
</script>
""", unsafe_allow_html=True)
try:
    if st.session_state.view == "main":
        main_view()
    else:
        add_view()
except Exception:
    st.error("Error fatal en la app")
    st.code(traceback.format_exc())
