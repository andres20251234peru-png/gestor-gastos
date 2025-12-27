# app.py
import streamlit as st
import datetime as dt
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import os
import time
import json
import pathlib
from dotenv import load_dotenv
import google.generativeai as genai
import traceback
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

# ============================================================
# 1) CONFIG
# ============================================================
st.set_page_config(
    page_title="Gestor de Gastos",
    page_icon="💸",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# Env (.env o .env.local)
env_path = pathlib.Path(".") / ".env"
if not env_path.exists():
    env_path = pathlib.Path(".") / ".env.local"
load_dotenv(dotenv_path=env_path)

api_key = os.getenv("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

SHEET_NAME = "Gastos_Diarios"

THEME = {
    "bg": "#000000",
    "surface": "#0F0F10",
    "card": "#121212",
    "card_green": "#0a1f13",
    "primary": "#00E054",
    "text": "#FFFFFF",
    "muted": "#A6A6A6",
    "stroke": "#242424",
    "input": "#1E1E1E",
    "disabled": "#333333",
    "card2": "#161617",
}

MESES_ORD = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
]

COLORS_MAP = {
    "Comida": "#00E054",
    "Transporte": "#00F0FF",
    "Salud": "#FFC700",
    "Trabajo": "#FF4B4B",
    "Ocio": "#FFFFFF",
    "Casa": "#A259FF",
    "Inversión": "#4A90E2",
    "Otros": "#888888",
    "Pareja": "#FF69B4",
    "Estudios": "#F5A623",
    "Viaje": "#50E3C2",
}

ICON_MAP = {
    "Comida": "🍔",
    "Transporte": "🚗",
    "Salud": "💊",
    "Trabajo": "💼",
    "Ocio": "🎵",
    "Casa": "🏠",
    "Inversión": "📈",
    "Otros": "📦",
    "Pareja": "❤️",
    "Estudios": "📚",
    "Viaje": "✈️",
}

VALID_CATS = list(ICON_MAP.keys())

# ============================================================
# 1.1) STATE
# ============================================================
if "view" not in st.session_state:
    st.session_state.view = "main"

if "show_ai" not in st.session_state:
    st.session_state.show_ai = False

if "messages" not in st.session_state:
    st.session_state.messages = []

if "expanded_cat" not in st.session_state:
    st.session_state.expanded_cat = None

if "ai_last_processed" not in st.session_state:
    st.session_state.ai_last_processed = ""

CLEAR_CHAT_ON_CLOSE = True  # al cerrar IA, limpiar historial

# ============================================================
# 2) CSS (Evita pantallas blancas y mejora layout)
# ============================================================
def inject_css():
    st.markdown(
        f"""
<style>
/* Layout general */
.block-container {{
  max-width: 860px !important;
  padding-top: 18px !important;
  padding-bottom: 40px !important; /* no botones flotantes */
}}
.stApp {{ background: {THEME['bg']} !important; }}
header, footer {{ visibility: hidden; }}
html, body, [class*="css"] {{ color: {THEME['text']} !important; }}

/* Links y textos */
a, p, span, div, label, li {{ color: {THEME['text']} !important; }}

/* Selectbox */
div[data-baseweb="select"] > div {{
  background: {THEME['input']} !important;
  border: 1px solid {THEME['stroke']} !important;
  border-radius: 999px !important;
  color: {THEME['text']} !important;
}}
div[data-baseweb="menu"], div[data-baseweb="popover"], ul[data-testid="stSelectboxVirtualDropdown"] {{
  background-color: #121212 !important;
  border: 1px solid {THEME['stroke']} !important;
}}
li[role="option"] {{ color: white !important; }}
li[role="option"][aria-selected="true"] {{
  background: #2a2a2a !important;
  color: {THEME['primary']} !important;
}}

/* Botones base */
button {{
  border-radius: 18px !important;
}}
button[kind="primary"] {{
  background: {THEME['primary']} !important;
  color: #000 !important;
  border: none !important;
  font-weight: 900 !important;
  height: 46px !important;
}}
button[kind="secondary"] {{
  background: #121212 !important;
  border: 1px solid #2a2a2a !important;
  color: {THEME['text']} !important;
  height: 46px !important;
}}
button[kind="secondary"]:hover {{
  border-color: {THEME['primary']} !important;
}}

/* Card total */
.card {{
  background: linear-gradient(180deg, #192b23 0%, #0f1613 100%) !important;
  border: 1px solid #1f332a !important;
  border-radius: 28px !important;
  padding: 28px 22px !important;
  box-shadow: 0 18px 36px rgba(0,0,0,0.55) !important;
  position: relative;
  overflow: hidden;
  margin-top: 10px;
  display: flex !important;
  flex-direction: column !important;
  align-items: center !important;
  justify-content: center !important;
}}
.card-title {{
  color: #8fa397 !important;
  font-size: 0.78rem !important;
  letter-spacing: 2.4px !important;
  text-transform: uppercase !important;
  margin-bottom: 10px !important;
  text-align: center !important;
  font-weight: 800 !important;
}}
.card-amount {{
  font-size: 3.2rem !important;
  font-weight: 900 !important;
  margin: 0 !important;
  text-align: center !important;
  color: #FFFFFF !important;
  line-height: 1 !important;
}}
.card-watermark {{
  position: absolute;
  right: -22px;
  bottom: -42px;
  opacity: 0.05;
  font-size: 9.6rem;
  color: white;
  transform: rotate(-15deg);
  pointer-events: none;
}}

/* Input monto (pill grande) */
div[data-testid="stNumberInput"] {{
  background: transparent !important;
  box-shadow: none !important;
}}
div[data-testid="stNumberInput"] input {{
  background: #0f1713 !important;
  border: 1px solid #1f2a23 !important;
  border-radius: 22px !important;
  color: {THEME['primary']} !important;
  font-size: 3.2rem !important;
  font-weight: 900 !important;
  text-align: center !important;
  padding: 22px 0 !important;
  caret-color: {THEME['primary']} !important;
}}

/* Chips (categorías) */
div[role="radiogroup"] {{
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: center;
}}
div[role="radiogroup"] label {{
  background: {THEME['input']} !important;
  border: 1px solid {THEME['stroke']} !important;
  border-radius: 999px !important;
  padding: 10px 16px !important;
  cursor: pointer;
  transition: all .15s ease;
}}
div[role="radiogroup"] label p {{
  color: #cfcfcf !important;
  font-weight: 800 !important;
  font-size: .9rem !important;
  margin: 0 !important;
}}
div[role="radiogroup"] label:has(input:checked) {{
  background: {THEME['primary']} !important;
  border-color: {THEME['primary']} !important;
  box-shadow: 0 8px 18px rgba(0,224,84,0.25) !important;
}}
div[role="radiogroup"] label:has(input:checked) p {{
  color: #000 !important;
  font-weight: 900 !important;
}}
div[role="radiogroup"] label > div:first-child {{ display: none; }}

/* Secciones */
.section-title {{
  color: #777 !important;
  font-weight: 900;
  font-size: 0.86rem;
  letter-spacing: 1.7px;
  margin-top: 16px;
  margin-bottom: 10px;
}}

/* Acordeón (expander) */
div[data-testid="stExpander"] {{
  border: 1px solid #1f1f1f !important;
  border-radius: 18px !important;
  background: #111211 !important;
  overflow: hidden;
}}
div[data-testid="stExpander"] details {{
  background: #111211 !important;
}}
div[data-testid="stExpander"] summary {{
  padding: 14px 16px !important;
  background-color: #111211 !important; /* Force background */
  transition: background-color 0.2s;
}}
div[data-testid="stExpander"] summary:hover {{
  color: #fff !important;
  background-color: #181918 !important; /* Subtle hover */
}}
div[data-testid="stExpander"] summary:focus {{
  background-color: #111211 !important;
  color: #fff !important;
}}
/* Fix SVG icon color manually if needed, usually handles itself */
div[data-testid="stExpander"] summary p {{
  font-weight: 900 !important;
}}

/* Item movimientos */
.mov-item {{
  background: #111111;
  border: 1px solid #1f1f1f;
  border-radius: 18px;
  padding: 14px 16px;
  margin-bottom: 10px;
  display:flex;
  justify-content:space-between;
  align-items:center;
}}
.mov-left {{
  display:flex;
  flex-direction:column;
  gap: 4px;
  min-width: 0;
}}
.mov-cat {{
  font-weight: 900;
}}
.mov-desc {{
  color: #8a8a8a;
  font-size: 0.86rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 520px;
}}
.mov-amt {{
  font-weight: 900;
  color: {THEME['primary']};
  white-space: nowrap;
}}

/* Mini badge */
.badge {{
  display:inline-flex;
  align-items:center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 999px;
  border: 1px solid #1f332a;
  background: #0b1410;
  color: #9fc4b0 !important;
  font-weight: 800;
  font-size: .78rem;
  letter-spacing: .6px;
}}
/* Legend Items */
.legend-row {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0;
  margin-bottom: 4px;
  border-bottom: 1px solid #1f1f1f;
}}
.legend-row:last-child {{ border-bottom: none; }}
.legend-left {{
  display: flex;
  align-items: center;
  gap: 10px;
}}
.legend-dot {{
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}}
.legend-name {{
  color: #e0e0e0;
  font-weight: 700;
  font-size: 0.9rem;
}}
.legend-pct {{
  color: #888;
  font-weight: 800;
  font-size: 0.9rem;
}}

/* Rich Card Inside Expander */
.rich-card {{
  padding-bottom: 12px;
  margin-bottom: 12px;
  border-bottom: 1px solid #1f1f1f;
}}
.rich-header {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}}
.rich-left {{
  display: flex;
  flex-direction: column;
  gap: 2px;
}}
.rich-right {{
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
}}
.rich-cat {{
  font-size: 1.1rem;
  font-weight: 900;
  color: #fff;
}}
.rich-sub {{
  font-size: 0.75rem;
  font-weight: 700;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}}
.rich-amt {{
  font-size: 1.2rem;
  font-weight: 900;
  color: #fff;
}}
.rich-pct {{
  font-size: 0.9rem;
  font-weight: 800;
}}
.rich-bar-bg {{
  width: 100%;
  height: 6px;
  background: #2b2b2b;
  border-radius: 99px;
  margin-top: 6px;
  overflow: hidden;
}}
.rich-bar-fill {{
  height: 100%;
  border-radius: 99px;
}}
/* Toast Styling */
div[data-testid="stToast"] {{
  background-color: #111211 !important;
  border: 1px solid #1f1f1f !important;
  color: #ffffff !important;
  border-radius: 12px !important;
}}
div[data-testid="stToast"] p, div[data-testid="stToast"] svg {{
  color: #ffffff !important;
  fill: #ffffff !important;
}}
</style>
        """,
        unsafe_allow_html=True,
    )

# ============================================================
# 3) GOOGLE SHEETS
# ============================================================
@st.cache_resource
def get_client():
    if not os.path.exists("credentials.json"):
        return None
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    try:
        creds = Credentials.from_service_account_file("credentials.json", scopes=scope)
        return gspread.authorize(creds)
    except:
        return None

def normalize_mes_es(m):
    if not isinstance(m, str):
        return None
    m = m.strip().lower()
    mapa = {k.lower(): k for k in MESES_ORD}
    return mapa.get(m, m.capitalize())

@st.cache_data(ttl=300, show_spinner=False)
def load_data():
    client = get_client()
    if not client:
        return pd.DataFrame()

    try:
        sheet = client.open(SHEET_NAME).sheet1
        df = pd.DataFrame(sheet.get_all_records())
        if df.empty:
            return df

        cols_upper = {c.strip().upper(): c for c in df.columns}

        # FECHA
        if "FECHA" in cols_upper:
            df["FECHA"] = pd.to_datetime(df[cols_upper["FECHA"]], errors="coerce", dayfirst=True)
        else:
            df["FECHA"] = pd.NaT

        # MES
        if "MES" in cols_upper:
            df["MES"] = df[cols_upper["MES"]].apply(normalize_mes_es)
        else:
            df["MES"] = df["FECHA"].dt.month.map(lambda x: MESES_ORD[x - 1] if pd.notna(x) else None)

        # AÑO
        if "AÑO" in cols_upper:
            df["AÑO"] = pd.to_numeric(df[cols_upper["AÑO"]], errors="coerce").fillna(0).astype(int)
        else:
            df["AÑO"] = df["FECHA"].dt.year.fillna(0).astype(int)

        # CATEGORÍA
        cat_col = cols_upper.get("CATEGORÍA") or cols_upper.get("CATEGORIA")
        if cat_col:
            df["CATEGORÍA"] = df[cat_col].astype(str)
        else:
            df["CATEGORÍA"] = "Otros"

        # DESCRIPCION
        desc_col = cols_upper.get("DESCRIPCION") or cols_upper.get("DESCRIPCIÓN") or cols_upper.get("DESCRIPCION ")
        if desc_col:
            df["DESCRIPCION"] = df[desc_col].astype(str)
        else:
            df["DESCRIPCION"] = ""

        # MONTO
        if "MONTO" in cols_upper:
            df["MONTO"] = pd.to_numeric(
                df[cols_upper["MONTO"]].astype(str).str.replace(",", "", regex=False),
                errors="coerce",
            ).fillna(0.0)
        else:
            df["MONTO"] = 0.0

        # limpieza mínima
        df = df[(df["AÑO"] > 0) & (df["MES"].notna()) & (df["MONTO"] > 0)]
        return df
    except:
        return pd.DataFrame()

def save_to_sheet(data):
    client = get_client()
    if not client:
        return False, "No auth (credentials.json o permisos)."
    try:
        sheet = client.open(SHEET_NAME).sheet1
        mes_name = MESES_ORD[data["date"].month - 1]
        row = [
            data["date"].strftime("%d/%m/%Y"),
            mes_name,
            int(data["date"].year),
            data["category"],
            data["description"],
            float(data["amount"]),
        ]
        sheet.append_row(row)
        load_data.clear() # Invalidar cache para que se actualice
        return True, "OK"
    except Exception as e:
        return False, str(e)

def filter_data(df, mes, anio):
    if df.empty:
        return df
    return df[(df["MES"] == mes) & (df["AÑO"] == int(anio))].copy()

# ============================================================
# 4) IA (Gemini) - robusta (sin duplicar, sin años inventados)
# ============================================================
def call_gemini_safe(text):
    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        return model.generate_content(text)
    except:
        return None

def analyze_intent(user_txt, current_year, current_month, allowed_years):
    allowed_years_sorted = sorted(list(set(int(y) for y in allowed_years if pd.notna(y))))
    allowed_years_str = ", ".join(str(y) for y in allowed_years_sorted) if allowed_years_sorted else str(current_year)

    prompt = f"""
Devuelve SOLO JSON válido. Sin texto extra.

Categorías válidas: {", ".join(VALID_CATS)}.
Mes actual: {current_month}.
Año actual: {current_year}.
Años con datos disponibles (si necesitas año): {allowed_years_str}.
Regla: si el usuario NO indica año, usa {current_year}. Si el año pedido NO está en años disponibles, devuelve el más cercano disponible o {current_year}.

Acciones:
1) Guardar:
{{"accion":"guardar","monto":40.0,"categoria":"Comida","descripcion":"pizza"}}

2) Resumen mes:
{{"accion":"resumen_mes","anio":2025,"mes":"Octubre"}}

3) Chat:
{{"accion":"chat","respuesta":"..."}}

Mes debe ser uno de: {", ".join(MESES_ORD)}.

Texto usuario: "{user_txt}"
    """.strip()

    resp = call_gemini_safe(prompt)
    if not resp or not getattr(resp, "text", None):
        return {"accion": "chat", "respuesta": "No pude conectar con IA. Intenta nuevamente."}

    try:
        clean = resp.text.replace("```json", "").replace("```", "").strip()
        obj = json.loads(clean)
    except:
        return {"accion": "chat", "respuesta": "No entendí. Ej: 'pizza 40' o 'resumen Octubre'."}

    # normalizaciones defensivas
    accion = str(obj.get("accion", "chat")).strip().lower()
    if accion not in ["guardar", "resumen_mes", "chat"]:
        return {"accion": "chat", "respuesta": "No entendí. Prueba: 'pizza 40'."}

    if accion == "guardar":
        cat = str(obj.get("categoria", "Otros")).strip()
        if cat not in VALID_CATS:
            cat = "Otros"
        obj["categoria"] = cat
        return obj

    if accion == "resumen_mes":
        mes = obj.get("mes")
        if not isinstance(mes, str) or mes not in MESES_ORD:
            # intenta arreglar caso
            if isinstance(mes, str):
                mes_fix = normalize_mes_es(mes)
                if mes_fix in MESES_ORD:
                    mes = mes_fix
            obj["mes"] = mes
        try:
            anio = int(obj.get("anio", current_year))
        except:
            anio = current_year

        if allowed_years_sorted:
            if anio not in allowed_years_sorted:
                # escoger el más cercano
                anio = min(allowed_years_sorted, key=lambda y: abs(y - anio))
        obj["anio"] = anio
        return obj

    # chat
    return {"accion": "chat", "respuesta": str(obj.get("respuesta", "¿En qué te ayudo?"))}

def ai_chat_interface(df_context):
    st.markdown("""
    <style>
    /* SUPER NUCLEAR OPTION - FORCE BLACK BACKGROUND EVERYWHERE IN MODAL */
    div[role="dialog"],
    div[data-testid="stDialog"],
    section[data-testid="stDialog"],
    div[class*="stDialog"] {
        background-color: #000000 !important;
        background: #000000 !important;
        color: #ffffff !important;
    }
    
    /* Target the inner content containers to ensure no white leaks through */
    div[role="dialog"] > div,
    div[role="dialog"] > div > div,
    div[data-testid="stDialog"] > div,
    div[data-testid="stDialog"] .stVerticalBlock {
        background-color: #000000 !important;
        background: #000000 !important;
        padding: 0 !important;
    }
    
    /* KILL THE WHITE HEADER & CLOSE BUTTONS */
    [data-testid="stDialog"] header,
    [data-testid="stHeader"],
    div[role="dialog"] > button,
    div[role="dialog"] button[aria-label="Close"] {
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
        opacity: 0 !important;
    }
    
    /* Force text color strictly white to avoid dark-on-dark issues if something fails */
    [data-testid="stDialog"] p, 
    [data-testid="stDialog"] span, 
    [data-testid="stDialog"] div,
    [data-testid="stDialog"] h1,
    [data-testid="stDialog"] h2,
    [data-testid="stDialog"] h3 {
        color: #ffffff !important;
    }
    
    /* Chat Input Area */
    [data-testid="stChatInput"] {
        padding: 24px !important;
        background: #000 !important;
        border-top: 1px solid rgba(255,255,255,0.08) !important;
    }
    [data-testid="stChatInput"] textarea {
        background: rgba(45, 45, 45, 0.7) !important;
        backdrop-filter: blur(12px) !important;
        color: #fff !important;
        border: 1px solid rgba(255, 255, 255, 0.2) !important;
        border-radius: 30px !important;
        padding: 14px 22px !important;
        font-size: 15px !important;
        transition: all 0.3s ease !important;
    }
    [data-testid="stChatInput"] textarea:focus {
        border-color: #00E054 !important;
        background: rgba(60, 60, 60, 0.7) !important;
    }
    [data-testid="stChatInput"] textarea::placeholder {
        color: rgba(255, 255, 255, 0.6) !important;
        font-weight: 500;
    }
    [data-testid="stChatInput"] button svg {
        fill: #00E054 !important;
        filter: drop-shadow(0 0 8px rgba(0, 224, 84, 0.4));
    }
    
    /* Premium Header - Full Width */
    .chat-header {
        background: linear-gradient(135deg, #00E054 0%, #00a833 100%);
        padding: 30px 28px;
        position: relative;
        overflow: hidden;
        border-bottom: 2px solid rgba(0,0,0,0.15);
        margin: 0 !important;
    }
    .chat-header h2 {
        color: #000;
        font-size: 24px;
        font-weight: 900;
        margin: 0 0 4px 0;
        letter-spacing: -0.8px;
    }
    .chat-header p {
        color: #000;
        font-size: 13.5px;
        opacity: 0.85;
        margin: 0;
        font-weight: 600;
    }
    /* Custom Close X Button */
    .custom-close {
        position: absolute;
        top: 28px;
        right: 28px;
        color: #000;
        background: rgba(0, 0, 0, 0.1);
        width: 38px;
        height: 38px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 900;
        cursor: pointer;
        font-size: 22px;
        transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        z-index: 99999;
    }
    .custom-close:hover {
        background: rgba(0, 0, 0, 0.2);
        transform: rotate(90deg) scale(1.15);
    }

    /* Tips & Messages Glassmorphism */
    .chat-tips {
        background: rgba(255,255,255,0.02);
        padding: 14px 28px;
        border-bottom: 1px solid rgba(255,255,255,0.05);
    }
    .chat-tips-text { color: #777; font-size: 12px; margin: 0; }
    .chat-tips-text strong { color: #00E054; font-weight: 700; }

    .chat-messages {
        padding: 28px 20px;
        min-height: 420px;
        max-height: 420px;
        overflow-y: auto;
        background: #000;
    }
    .chat-messages::-webkit-scrollbar { width: 5px; }
    .chat-messages::-webkit-scrollbar-thumb { background: #333; border-radius: 10px; }
    
    /* Empty State */
    .empty-state {
        text-align: center;
        padding: 80px 30px;
        opacity: 0.65;
        animation: fadeIn 0.8s ease-out;
    }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 0.65; transform: translateY(0); } }
    .empty-state-icon { font-size: 64px; margin-bottom: 20px; text-shadow: 0 0 20px rgba(0, 224, 84, 0.3); }
    .empty-state-title { color: #fff; font-size: 18px; font-weight: 800; margin-bottom: 10px; }
    .empty-state-sub { color: #999; font-size: 14px; line-height: 1.5; }
    
    /* User Message */
    .msg-user {
        display: flex;
        justify-content: flex-end;
        margin-bottom: 22px;
        animation: slideInR 0.3s ease-out;
    }
    @keyframes slideInR { from { opacity: 0; transform: translateX(10px); } to { opacity: 1; transform: translateX(0); } }
    .msg-user-content {
        background: linear-gradient(135deg, #00E054 0%, #00bc45 100%);
        color: #000;
        font-weight: 800;
        padding: 14px 20px;
        border-radius: 22px;
        border-bottom-right-radius: 4px;
        box-shadow: 0 4px 15px rgba(0, 224, 84, 0.3);
    }
    
    /* AI Message - GLASSMORPHISM */
    .msg-ai {
        display: flex;
        gap: 12px;
        margin-bottom: 22px;
        animation: slideInL 0.3s ease-out;
    }
    @keyframes slideInL { from { opacity: 0; transform: translateX(-10px); } to { opacity: 1; transform: translateX(0); } }
    .msg-ai-avatar {
        width: 38px;
        height: 38px;
        background: #00E054;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 20px;
        flex-shrink: 0;
        box-shadow: 0 4px 10px rgba(0, 224, 84, 0.2);
    }
    .msg-ai-content { flex: 1; max-width: 82%; }
    .msg-ai-bubble {
        background: rgba(255, 255, 255, 0.06) !important;
        backdrop-filter: blur(20px) !important;
        border: 1px solid rgba(255, 255, 255, 0.15) !important;
        border-radius: 22px;
        border-bottom-left-radius: 4px;
        color: #eee;
        padding: 16px 20px;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
    }
    
    /* Expense Card */
    .expense-preview {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 14px;
        padding: 18px;
        margin-top: 14px;
    }
    .exp-title { color: #00E054; font-size: 11px; font-weight: 900; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 16px; }
    .exp-row { display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid rgba(255, 255, 255, 0.04); }
    .exp-row:last-child { border-bottom: none; }
    .exp-label { color: #aaa; font-size: 13.5px; }
    .exp-value { color: #fff; font-size: 13.5px; font-weight: 700; }
    .exp-value.highlight { color: #00E054; font-size: 16px; }
    .exp-confirm { margin-top: 16px; text-align: center; font-size: 12.5px; color: #999; }
    .exp-confirm strong { color: #00E054; }

    /* Success Message */
    .msg-success {
        display: inline-flex;
        align-items: center;
        gap: 12px;
        background: rgba(0, 224, 84, 0.12);
        border: 1.5px solid #00E054;
        padding: 14px 22px;
        border-radius: 35px;
        color: #00E054;
        font-weight: 800;
        font-size: 14.5px;
        box-shadow: 0 4px 20px rgba(0, 224, 84, 0.15);
    }
    </style>

    <script>
    // JS hack to close the modal if our custom close is clicked
    parent.document.addEventListener('click', function(e) {
        if (e.target.classList.contains('custom-close')) {
            // Find and click the hidden streamlit close button
            const closeBtn = parent.document.querySelector('[data-testid=\"stDialog\"] button[aria-label=\"Close\"]');
            if (closeBtn) closeBtn.click();
        }
    });
    </script>
    """, unsafe_allow_html=True)

    now = dt.datetime.now()
    current_month_name = MESES_ORD[now.month - 1]
    allowed_years = df_context["AÑO"].unique().tolist() if (not df_context.empty and "AÑO" in df_context.columns) else [now.year]
    
    # Build all messages HTML
    messages_html = ""
    
    if not st.session_state.messages:
        messages_html = '<div class="empty-state"><div class="empty-state-icon">✨</div><p class="empty-state-title">Hola, soy tu asistente</p><p class="empty-state-sub">Registra tus gastos por voz o chat</p></div>'
    else:
        for m in st.session_state.messages:
            role = m["role"]
            content = m["content"]
            
            if role == "user":
                messages_html += f'<div class="msg-user"><div class="msg-user-content">{content}</div></div>'
            else:
                bubble_content = ""
                if isinstance(content, dict) and content.get("type") == "proposal":
                    d = content.get("data", {})
                    cat, desc, monto = d.get("categoria", "Otros"), d.get("descripcion", ""), d.get("monto", 0)
                    bubble_content = f'<div class="expense-preview"><div class="exp-title">📍 Gasto Detectado</div><div class="exp-row"><span class="exp-label">Categoría</span><span class="exp-value">{cat}</span></div><div class="exp-row"><span class="exp-label">Monto</span><span class="exp-value highlight">S/ {monto:.2f}</span></div><div class="exp-row"><span class="exp-label">Detalle</span><span class="exp-value">{desc}</span></div><div class="exp-confirm">Dime <strong>"Sí"</strong> o <strong>"Guarda"</strong> para confirmar</div></div>'
                elif isinstance(content, dict) and content.get("type") == "success":
                    d = content.get("data", {})
                    cat, monto = d.get("categoria", ""), d.get("monto", 0)
                    bubble_content = f'<div class="msg-success"><span>✅</span><span>Registrado: {cat} (S/ {monto:.2f})</span></div>'
                else: bubble_content = str(content)
                
                messages_html += f'<div class="msg-ai"><div class="msg-ai-avatar">🤖</div><div class="msg-ai-content"><div class="msg-ai-bubble">{bubble_content}</div></div></div>'
    
    # Render UI
    st.markdown(f"""
    <div class="chat-header">
        <div class="custom-close">✕</div>
        <h2>💬 Asistente IA</h2>
        <p>Hoy es {now.strftime('%d de')} {current_month_name}, {now.year}</p>
    </div>
    <div class="chat-tips">
        <p class="chat-tips-text">💡 Prueba: <strong>"Pizza 45"</strong> • <strong>"Taxi 15"</strong> • <strong>"Resumen de este mes"</strong></p>
    </div>
    <div class="chat-messages" id="chat-container">
        {messages_html}
    </div>
    """, unsafe_allow_html=True)

    # Chat input
    prompt = st.chat_input("Escribe aquí...", key="ai_input")
    
    if prompt:
        # Add user message FIRST
        st.session_state.messages.append({"role": "user", "content": prompt})
        # Immediately rerun to show user message before processing
        st.rerun()
        
    # Process pending messages (this runs after rerun)
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
        last_msg = st.session_state.messages[-1]["content"]
        
        # Check if this message was already processed to avoid double triggers
        if "ai_processing" not in st.session_state:
            st.session_state.ai_processing = True
            
            # Check pending confirmation
            if "pending_expense" in st.session_state:
                pe = st.session_state.pending_expense
                text_lower = last_msg.lower()
                
                if any(x in text_lower for x in ["si", "sí", "yes", "ok", "confirmar", "dale", "guarda"]):
                    ok, msg = save_to_sheet({
                        "date": now,
                        "amount": pe["monto"],
                        "category": pe["categoria"],
                        "description": pe["descripcion"],
                    })
                    if ok:
                        st.session_state.messages.append({"role": "assistant", "content": {"type": "success", "data": pe}})
                        st.toast("Gasto registrado", icon="✅")
                    else:
                        st.session_state.messages.append({"role": "assistant", "content": f"❌ Error: {msg}"})
                    del st.session_state.pending_expense
                else:
                    del st.session_state.pending_expense
                    st.session_state.messages.append({"role": "assistant", "content": "Cancelado. ¿En qué más te ayudo?"})
                
                del st.session_state.ai_processing
                st.rerun()
            
            # Normal AI analysis
            with st.spinner("Pensando..."):
                # Pass current month to the analyzer
                plan = analyze_intent(last_msg, now.year, current_month_name, allowed_years)
                acc = plan.get("accion")

                if acc == "guardar":
                    try:
                        monto = float(plan.get("monto", 0))
                        cat = str(plan.get("categoria", "Otros"))
                        desc = str(plan.get("descripcion", "")).strip()

                        if monto <= 0:
                             st.session_state.messages.append({"role": "assistant", "content": "Monto inválido."})
                        else:
                            proposal = {"monto": monto, "categoria": cat, "descripcion": desc or cat}
                            st.session_state.pending_expense = proposal
                            st.session_state.messages.append({"role": "assistant", "content": {"type": "proposal", "data": proposal}})
                    except:
                        st.session_state.messages.append({"role": "assistant", "content": "Error procesando datos."})

                elif acc == "resumen_mes":
                     anio = int(plan.get("anio", now.year))
                     mes = plan.get("mes")
                     if not mes or mes not in MESES_ORD:
                         out = "Indica un mes válido."
                     else:
                         dfm = filter_data(df_context, mes, anio)
                         total = float(dfm["MONTO"].sum()) if not dfm.empty else 0.0
                         if total <= 0:
                             out = f"No hay gastos para {mes} {anio}."
                         else:
                             out = f"📊 **{mes} {anio}**\n\nTotal: **S/ {total:,.2f}**"
                     st.session_state.messages.append({"role": "assistant", "content": out})
                
                else:
                    st.session_state.messages.append({"role": "assistant", "content": plan.get("respuesta", "No entendí.")})

                del st.session_state.ai_processing
                st.rerun()


# ============================================================
# 5) CHART HELPERS (Matplotlib)
# ============================================================
def render_donut(grp_df, center_cat, center_pct):
    labels = grp_df["CATEGORÍA"].tolist()
    values = grp_df["MONTO"].tolist()
    colors = [COLORS_MAP.get(c, "#888888") for c in labels]

    fig, ax = plt.subplots(figsize=(5, 5), dpi=220)
    fig.patch.set_facecolor("none")
    ax.set_facecolor("none")

    ax.pie(
        values,
        colors=colors,
        startangle=90,
        counterclock=False,
        wedgeprops=dict(width=0.20, edgecolor="none"),
    )

    ax.text(
        0, 0.24, f"{center_cat.upper()}",
        ha="center", va="center",
        fontsize=10, fontweight="800", color="#666666"
    )

    ax.text(
        -0.05, -0.05, f"{int(center_pct)}",
        ha="center", va="center",
        fontsize=52, fontweight="900", color="#FFFFFF"
    )

    cat_color = COLORS_MAP.get(center_cat, "#FFFFFF")
    ax.text(
        0.35, -0.02, "%",
        ha="center", va="center",
        fontsize=24, fontweight="900", color=cat_color
    )

    ax.set(aspect="equal")
    ax.axis("off")
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)

def render_history_chart(df, view_mode="Diario", current_month_name=""):
    if df.empty:
        st.info("No hay datos para mostrar en este período.")
        return

    # Preparar datos según view_mode
    if view_mode == "Diario":
        df["_dt"] = pd.to_datetime(df["FECHA"])
        df["_day"] = df["_dt"].dt.day
        grouped = df.groupby("_day")["MONTO"].sum()
        x = grouped.index.tolist()
        y = grouped.values.tolist()
        x_label = "Día"
    
    elif view_mode == "Semanal":
        df["_dt"] = pd.to_datetime(df["FECHA"])
        # Semana relativa al mes: (dia - 1) // 7 + 1
        df["_week_rel"] = (df["_dt"].dt.day - 1) // 7 + 1
        grouped = df.groupby("_week_rel")["MONTO"].sum()
        x = grouped.index.tolist()
        y = grouped.values.tolist()
        x_label = "Semana"

    elif view_mode == "Mensual":
        df["_dt"] = pd.to_datetime(df["FECHA"])
        df["_month"] = df["_dt"].dt.month
        grouped = df.groupby("_month")["MONTO"].sum()
        x = grouped.index.tolist()
        y = grouped.values.tolist()
        x_label = "Mes"

    # Graficar
    fig, ax = plt.subplots(figsize=(6, 3), dpi=180)
    fig.patch.set_facecolor("none")
    ax.set_facecolor("none")

    # Barras
    bars = ax.bar(x, y, color=THEME["primary"], alpha=0.9, edgecolor="none", width=0.6)

    # Estilo ejes
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.spines['bottom'].set_color('#333')
    
    # Eje X
    ax.tick_params(axis='x', colors='#888', labelsize=8)
    
    # Forzar Ticks Enteros Exactos
    ax.set_xticks(x)
    
    # Etiquetas personalizadas
    if view_mode == "Mensual":
        labels = [MESES_ORD[int(val)-1][:3].upper() if 1 <= val <= 12 else str(val) for val in x]
        ax.set_xticklabels(labels, fontweight="700")
    elif view_mode == "Semanal":
        labels = [f"SEM {int(val)}" for val in x]
        ax.set_xticklabels(labels, fontweight="700")
    else:
        # Diario: solo números enteros
        ax.set_xticklabels([str(int(val)) for val in x])

    # Eje Y (ocultar eje vertical principal line)
    ax.spines['left'].set_visible(False)
    ax.yaxis.grid(True, linestyle='--', alpha=0.1, color='#fff')
    ax.tick_params(axis='y', labelsize=8, labelcolor="#666")

    st.pyplot(fig, use_container_width=True)
    plt.close(fig)

def render_daily_line(daily_df):
    fig, ax = plt.subplots(figsize=(6.6, 2.7), dpi=160)
    fig.patch.set_facecolor("none")
    ax.set_facecolor("none")

    x = daily_df["DIA"].astype(int).tolist()
    y = daily_df["MONTO"].astype(float).tolist()

    ax.plot(x, y, linewidth=2.2)
    ax.fill_between(x, y, alpha=0.12)

    ax.tick_params(colors="#9a9a9a", labelsize=8)
    for spine in ax.spines.values():
        spine.set_visible(False)

    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.grid(False)
    st.pyplot(fig, use_container_width=True)

# ============================================================
# 6) VIEWS
# ============================================================
def main_view():
    df = load_data()
    now = dt.datetime.now()

    # Header superior: fecha + saludo + acciones (NUEVO GASTO arriba + IA)
    dias = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO", "DOMINGO"]
    date_display = f"{dias[now.weekday()]}, {now.day} DE {MESES_ORD[now.month - 1].upper()}"

    c_left, c_mid, c_right = st.columns([6, 2.2, 1.2], vertical_alignment="center")
    with c_left:
        st.markdown(
            f"""
            <div class="badge">● {date_display}</div>
            <div style="margin-top:10px; font-size:2.1rem; font-weight:900; line-height:1.05;">Hola, Andrés</div>
            """,
            unsafe_allow_html=True
        )
    with c_mid:
        if st.button("➕ Nuevo gasto", type="primary", use_container_width=True):
            st.session_state.view = "add"
            st.rerun()
    with c_right:
        if st.button("🤖", type="secondary", use_container_width=True):
            st.session_state.show_ai = True
            st.rerun()

    st.write("")

    # --- SELECTOR DE FECHA (RICH UI) ---
    if "sel_year" not in st.session_state:
        st.session_state.sel_year = now.year
    if "sel_month" not in st.session_state:
        st.session_state.sel_month = MESES_ORD[now.month - 1]

    # Variables finales para filtrar la data (definidas antes para usarlas en el título)
    anio_sel = st.session_state.sel_year
    mes_sel = st.session_state.sel_month

    # Título del expander (Muestra la selección actual)
    current_selection_title = f"📅 {mes_sel} {anio_sel}"

    with st.expander(current_selection_title, expanded=False):
        # 1. Selector de AÑO
        c_y1, c_y2, c_y3 = st.columns([1, 2, 1])
        with c_y1:
            if st.button("‹", key="prev_year", type="secondary", use_container_width=True):
                st.session_state.sel_year -= 1
                st.rerun()
        with c_y2:
            st.markdown(f"<h3 style='text-align:center; margin:0; padding-top:5px;'>{st.session_state.sel_year}</h3>", unsafe_allow_html=True)
        with c_y3:
            if st.button("›", key="next_year", type="secondary", use_container_width=True):
                st.session_state.sel_year += 1
                st.rerun()

        st.write("")

        # 2. Grid de MESES (4 filas x 3 columnas)
        month_abbrs = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]
        mes_map = {m: full for m, full in zip(month_abbrs, MESES_ORD)}
        rows = [month_abbrs[i:i+3] for i in range(0, len(month_abbrs), 3)]
        
        @st.fragment
        def month_grid():
            for row_months in rows:
                cols = st.columns(3)
                for idx, m_abbr in enumerate(row_months):
                    full_name = mes_map[m_abbr]
                    is_active = (full_name == st.session_state.sel_month)
                    btn_type = "primary" if is_active else "secondary"
                    
                    with cols[idx]:
                        if st.button(m_abbr, key=f"btn_{m_abbr}", type=btn_type, use_container_width=True):
                            st.session_state.sel_month = full_name
                            st.rerun()
        month_grid()
    
    # -----------------------------------

    # Data mensual
    dfm = filter_data(df, mes_sel, anio_sel)
    total = float(dfm["MONTO"].sum()) if not dfm.empty else 0.0

    # Card total
    st.markdown(
        f"""
        <div class="card">
          <div class="card-watermark">👛</div>
          <div class="card-title">TOTAL GASTADO</div>
          <div class="card-amount">S/ {total:,.2f}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    if dfm.empty or total <= 0:
        st.markdown(
            """
            <div style="text-align:center; padding:38px; color:#666;">
              <h4>Sin gastos este mes</h4>
              <p>Añade un nuevo gasto para ver el desglose.</p>
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        # Calcular grupo siempre (se usa en ambos modos para el detalle abajo)
        grp = dfm.groupby("CATEGORÍA")["MONTO"].sum().reset_index().sort_values("MONTO", ascending=False)
        grp["PCT"] = (grp["MONTO"] / total) * 100

        # Switcher Categorías / Histórico
        st.write("")
        st.markdown('<div class="section-title">DISTRIBUCIÓN</div>', unsafe_allow_html=True)
            
        if "chart_mode" not in st.session_state:
            st.session_state.chart_mode = "Categorías"
        
        # Switcher tipo Pills
        c_p1, c_p2, c_void = st.columns([2, 2, 4])
        with c_p1:
            if st.button("Categorías", key="btn_mn_cat", type="primary" if st.session_state.chart_mode == "Categorías" else "secondary", use_container_width=True):
                st.session_state.chart_mode = "Categorías"
                st.rerun()
        with c_p2:
            if st.button("Histórico", key="btn_mn_hist", type="primary" if st.session_state.chart_mode == "Histórico" else "secondary", use_container_width=True):
                st.session_state.chart_mode = "Histórico"
                st.rerun()
        
        st.write("")

        col_chart, col_legend = st.columns([1, 1], vertical_alignment="center")

        if st.session_state.chart_mode == "Categorías":
            top_row = grp.iloc[0]
            center_cat = top_row["CATEGORÍA"]
            center_pct = float(grp[grp["CATEGORÍA"] == center_cat]["PCT"].iloc[0])

            # --- VISUALIZACIÓN DONUT ---
            with col_chart:
                render_donut(grp, center_cat, center_pct)

            with col_legend:
                # Leyenda Custom HTML
                for _, r in grp.iterrows():
                    cat = r["CATEGORÍA"]
                    pct_val = float(r["PCT"])
                    pct = int(pct_val + 0.5)  # Redondeo estándar
                    color = COLORS_MAP.get(cat, "#888888")
                    
                    st.markdown(
                        f"""
                        <div class="legend-row">
                          <div class="legend-left">
                            <div class="legend-dot" style="background:{color}; box-shadow:0 0 6px {color};"></div>
                            <div class="legend-name">{cat}</div>
                          </div>
                          <div class="legend-pct">{pct}%</div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
        
        else:
            # --- VISUALIZACIÓN HISTÓRICO (BARS) ---
            if "hist_mode" not in st.session_state:
                st.session_state.hist_mode = "Diario"
            
            # Sub-selector Diario / Semanal / Mensual
            c_h1, c_h2, c_h3, c_hv = st.columns([1.5, 1.5, 1.5, 2.5])
            with c_h1:
                if st.button("Diario", key="hm_day", type="primary" if st.session_state.hist_mode == "Diario" else "secondary", use_container_width=True):
                    st.session_state.hist_mode = "Diario"
                    st.rerun()
            with c_h2:
                if st.button("Semanal", key="hm_week", type="primary" if st.session_state.hist_mode == "Semanal" else "secondary", use_container_width=True):
                    st.session_state.hist_mode = "Semanal"
                    st.rerun()
            with c_h3:
                if st.button("Mensual", key="hm_month", type="primary" if st.session_state.hist_mode == "Mensual" else "secondary", use_container_width=True):
                    st.session_state.hist_mode = "Mensual"
                    st.rerun()
            
            st.write("")
            
            # Preparar datos para el gráfico
            if st.session_state.hist_mode == "Mensual":
                # Necesitamos data del año completo
                df_year = filter_data(df, None, anio_sel)
                render_history_chart(df_year, "Mensual")
            elif st.session_state.hist_mode == "Semanal":
                render_history_chart(dfm, "Semanal")
            else:
                render_history_chart(dfm, "Diario")

        # Sección de Detalles
        st.write("")
        if st.session_state.chart_mode == "Categorías":
            # Acordeón (expander) por categoría (Modo Categorías)
            st.markdown('<div class="section-title">DETALLE POR CATEGORÍA</div>', unsafe_allow_html=True)
            for _, r in grp.iterrows():
                cat = r["CATEGORÍA"]
                amt = float(r["MONTO"])
                pct = float(r["PCT"])
                icon = ICON_MAP.get(cat, "•")
                color = COLORS_MAP.get(cat, "#888888")

                title = f"{icon}  {cat}"
                is_expanded = (st.session_state.expanded_cat == cat)
                
                with st.expander(title, expanded=is_expanded):
                    details = dfm[dfm["CATEGORÍA"] == cat].sort_values("FECHA", ascending=False)
                    num_mov = len(details)

                    # Rich Card HTML
                    st.markdown(
                        f"""
                        <div class="rich-card">
                          <div class="rich-header">
                            <div class="rich-left">
                                <div class="rich-cat">{cat}</div>
                                <div class="rich-sub">{num_mov} MOVIMIENTOS</div>
                            </div>
                            <div class="rich-right">
                                <div class="rich-amt">S/ {amt:,.2f}</div>
                                <div class="rich-pct" style="color:{color}">{int(pct + 0.5)}%</div>
                            </div>
                          </div>
                          <div class="rich-bar-bg">
                            <div class="rich-bar-fill" style="width:{pct}%; background:{color};"></div>
                          </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                    if details.empty:
                        st.caption("Sin movimientos en esta categoría.")
                    else:
                        for _, d in details.iterrows():
                            ddate = d["FECHA"]
                            dstr = ddate.strftime("%d/%m") if pd.notna(ddate) else ""
                            desc = (str(d.get("DESCRIPCION", "")) or "").strip() or cat
                            amt2 = float(d.get("MONTO", 0))

                            st.markdown(
                                f"""
                                <div class="mov-item">
                                  <div class="mov-left">
                                    <div class="mov-cat">{desc}</div>
                                    <div class="mov-desc">{dstr}</div>
                                  </div>
                                  <div class="mov-amt">S/ {amt2:,.2f}</div>
                                </div>
                                """,
                                unsafe_allow_html=True
                            )
        
        else:
            # Modo Histórico: Lista plana sin agrupar
            st.markdown('<div class="section-title">MOVIMIENTOS</div>', unsafe_allow_html=True)
            
            # Datos filtrados según historico mode? User asked for "grouping by week..." for chart, 
            # but list should just be "movements". 
            # Logic: If I select "Weekly" chart, what list should I see? The movements of that month?
            # User said: "Cuando se seleccione histórico... deberian ser sin agrupar."
            # We already have dfm (filtered by Month). Let's show all month movements flat.
            
            flat_movs = dfm.sort_values("FECHA", ascending=False)
            
            if flat_movs.empty:
                st.info("No hay movimientos en este periodo.")
            else:
                for _, d in flat_movs.iterrows():
                    cat = d["CATEGORÍA"]
                    ddate = d["FECHA"]
                    dstr = ddate.strftime("%d/%m") if pd.notna(ddate) else ""
                    desc = (str(d.get("DESCRIPCION", "")) or "").strip() or cat
                    amt2 = float(d.get("MONTO", 0))
                    
                    st.markdown(
                        f"""
                        <div class="mov-item">
                          <div class="mov-left">
                            <div class="mov-cat">{desc}</div>
                            <div class="mov-desc">{cat} • {dstr}</div>
                          </div>
                          <div class="mov-amt">S/ {amt2:,.2f}</div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

    # Modal IA
    if st.session_state.show_ai:
        @st.dialog("Asistente IA")

        def ai_modal():
            c1, c2 = st.columns([10, 1])
            with c2:
                if st.button("✕", key="close_ai"):
                    st.session_state.show_ai = False
                    if CLEAR_CHAT_ON_CLOSE:
                        st.session_state.messages = []
                        st.session_state.ai_last_processed = ""
                    st.rerun()
            ai_chat_interface(df)
        ai_modal()

def add_view():
    # Header superior (evita blanco / evita botones flotantes)
    c_back, c_title, c_void = st.columns([1.2, 6, 1.2], vertical_alignment="center")
    with c_back:
        if st.button("←", type="secondary"):
            st.session_state.view = "main"
            st.rerun()
    with c_title:
        st.markdown("<div style='text-align:center; font-size:1.5rem; font-weight:900;'>Nuevo Gasto</div>", unsafe_allow_html=True)
    with c_void:
        st.write("")

    st.write("")
    st.markdown("<div class='section-title' style='text-align:center;'>MONTO</div>", unsafe_allow_html=True)

    monto = st.number_input("Monto", min_value=0.0, step=1.0, label_visibility="collapsed")
    st.markdown(f"<div style='text-align:center; color:{THEME['muted']}; margin-top:-8px; font-weight:800;'>soles</div>", unsafe_allow_html=True)

    st.write("")
    st.markdown("<div class='section-title' style='text-align:center;'>CATEGORÍA</div>", unsafe_allow_html=True)

    # Generar lista de categorías dinámica
    cats = [f"{icon} {name}" for name, icon in ICON_MAP.items()]
    cat_sel = st.radio("Categoria", cats, horizontal=True, label_visibility="collapsed")
    cat_clean = cat_sel.split(" ", 1)[1] if " " in cat_sel else cat_sel
    if cat_clean not in VALID_CATS:
        cat_clean = "Otros"

    st.write("")
    st.markdown("<div class='section-title' style='text-align:center;'>NOTA</div>", unsafe_allow_html=True)
    nota = st.text_input("Nota", placeholder="Descripción (opcional)…", label_visibility="collapsed")

    st.write("")
    valid = monto > 0

    # Botones abajo (normales, no fijos)
    c1, c2 = st.columns([1, 1], vertical_alignment="center")
    with c1:
        if st.button("Cancelar", type="secondary", use_container_width=True):
            st.session_state.view = "main"
            st.rerun()
    with c2:
        if st.button("Guardar", type="primary", disabled=not valid, use_container_width=True):
            with st.spinner("Guardando…"):
                ok, msg = save_to_sheet(
                    {
                        "date": dt.datetime.now(),
                        "amount": float(monto),
                        "category": cat_clean,
                        "description": (nota.strip() if nota else "") or cat_clean,
                    }
                )

            if ok:
                st.toast("Gasto guardado", icon="✅")
                # Removed artificial sleep for faster transition
                st.session_state.view = "main"
                st.rerun()
            else:
                st.error(f"❌ Error: {msg}")

# ============================================================
# 7) RUN
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
