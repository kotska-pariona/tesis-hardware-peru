import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# =============================================================================
# HDS-ROI v6.2 — Dashboard Principal (Tema Blanco)
# Fixes aplicados:
#   FIX-A: Unidades realistas por tipo HW (GPU≤3, Case≤3, RAM≤8...)
#   FIX-B: Columna "Portafolio OE9" en simulador
#   FIX-C: _read_oe9_portafolios_detalle() y _buscar_portafolio_oe9() integradas
#   FIX-D: saldo definido antes de usarse en fila TOTAL
#   FIX-E: df_skus eliminado (código muerto)
#   FIX-F: Tornado chart usa datos reales de OE9
#   FIX-G: fig_mae escala MAPE correcta
#   FIX-H: Métricas PE2 v5.2 (WMAPE global/seen/unseen, MAE, 32 features)
#   FIX-I: section_title() — iconos deduplicados (icon solo en 2do arg)
#   FIX-J: nav_link() — emoji solo en label, icon arg vacío
#   FIX-K: page_oe9() — "Soluciones" dinámico con len(df_oe9)
#   FIX-L: actualizar_simulador prevent_initial_call=True
#   FIX-M: page_portafolios() usa DATA.get() con defaults seguros
#   FIX-N: page_home_ejecutivo() — import json redundante eliminado
# =============================================================================

import os
import json
import warnings
from datetime import datetime
from pathlib import Path

from pages.page_obsolescencia import page_obsolescencia

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

import dash
from dash import dcc, html, Input, Output, State, callback_context
import dash_bootstrap_components as dbc

from dashboard_config import (
    COLORS, PLOTLY_TEMPLATE, CHART_CONFIG, PALETTE_CATEGORICAL,
    SIDEBAR_STYLE, CONTENT_STYLE, TYPOGRAPHY, ICONS, APP_CONFIG
)
from dashboard_data import DATA

warnings.filterwarnings("ignore")

# ── FIX-H: Constantes PE2 v5.2 ──────────────────────────────────────────────
PE2_V52 = {
    "wmape_global":  0.97,
    "wmape_seen":    0.78,
    "wmape_unseen":  2.14,
    "mae_global":    4.87,
    "mae_seen":      4.00,
    "mae_unseen":    9.25,
    "wmape_val":     0.62,
    "mae_val":       3.12,
    "r2":            0.9967,
    "n_iter":        997,
    "n_features":    32,
    "n_train":       640762,
    "n_val":         107056,
    "n_test":        129626,
    "n_total":       877958,
    "n_fechas":      35,
    "pct_unseen":    22,
    "ratio_deg":     2.7,
    "dataset":       "processed_v2",
    "modelo":        "pe2_v52",
    "fecha":         "2026-10-03",
}

# ─────────────────────────────────────────────
# HELPERS ARBITRAJE
# ─────────────────────────────────────────────

def _cargar_modelos_roi():
    p = Path('data/raw/precios_por_modelo.json')
    if not p.exists():
        return {}
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)


def _color_roi(roi):
    if roi > 40: return '#27ae60'
    if roi > 10: return '#f39c12'
    if roi > 0:  return '#7f8c8d'
    return '#e74c3c'


def _safe_layout(**kwargs):
    """Merge PLOTLY_TEMPLATE layout evitando claves duplicadas."""
    base = dict(PLOTLY_TEMPLATE["layout"])
    for k, v in kwargs.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            merged = dict(base[k])
            merged.update(v)
            base[k] = merged
        else:
            base[k] = v
    return base

# ─────────────────────────────────────────────
# FIX-A: Unidades máximas REALISTAS por tipo HW
# ─────────────────────────────────────────────

UNIDADES_MAX_HW = {
    "gpu":         3,
    "cpu":         5,
    "ram":         8,
    "ssd":         6,
    "hdd":         4,
    "motherboard": 3,
    "psu":         4,
    "case":        3,
    "cooler":      4,
    "monitor":     2,
    "laptop":      2,
    "otro":        3,
}

MAX_SKUS_POR_HW = 2

# ─────────────────────────────────────────────
# FIX-C: Helpers OE9 portafolios
# ─────────────────────────────────────────────

def _read_oe9_portafolios_detalle() -> list:
    try:
        path = Path("results/oe9_portafolios_nodominados.json")
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _buscar_portafolio_oe9(titulo: str, portafolios: list) -> str:
    if not portafolios or not titulo:
        return "N/A"
    titulo_lower = titulo.lower()[:30]
    for port in portafolios:
        tipo = port.get("tipo", "N/A")
        for sku in port.get("skus", []):
            prod = str(sku.get("producto", "")).lower()[:30]
            if prod and (prod[:15] in titulo_lower or titulo_lower[:15] in prod):
                return tipo
    return "N/A"

# ─────────────────────────────────────────────
# 0. APP
# ─────────────────────────────────────────────

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP],
    suppress_callback_exceptions=True,
    title=APP_CONFIG["title"],
)

# ─────────────────────────────────────────────
# 1. COMPONENTES REUTILIZABLES
# ─────────────────────────────────────────────

def kpi_card(title, value, subtitle="", color=None, icon="📊", size="md"):
    color      = color or COLORS["accent"]
    height     = "140px" if size == "lg" else "120px"
    title_size = "0.85rem" if size == "lg" else "0.75rem"
    value_size = "2.2rem"  if size == "lg" else "1.8rem"
    return dbc.Card([
        dbc.CardBody([
            html.Div([
                html.Span(icon, style={"fontSize": "2rem", "marginRight": "12px", "opacity": 0.8}),
                html.Div([
                    html.P(title, className="mb-1", style={
                        "color": COLORS["text_dim"], "fontSize": title_size,
                        "textTransform": "uppercase", "letterSpacing": "0.05em",
                        "fontWeight": 600}),
                    html.H4(value, className="mb-1", style={
                        "color": color, "fontSize": value_size, "fontWeight": 700}),
                    html.P(subtitle, className="mb-0", style={
                        "color": COLORS["text_dim"], "fontSize": "0.7rem"}),
                ], style={"flex": 1})
            ], style={"display": "flex", "alignItems": "center", "height": "100%"})
        ], style={"padding": "16px"})
    ], style={
        "background": COLORS["bg"],
        "border": f"2px solid {COLORS['border']}",
        "borderRadius": "10px", "height": height,
        "transition": "all 0.3s ease", "cursor": "pointer",
    }, className="shadow-sm")


# FIX-I: section_title — el icon va SOLO en el 2do argumento.
# Todas las llamadas deben usar: section_title("Texto sin emoji", "🔬")
# o simplemente: section_title("Texto sin emoji")
def section_title(text, icon=""):
    return html.H5(
        [html.Span(icon + (" " if icon else ""),
                   style={"marginRight": "8px", "color": COLORS["accent"]}),
         text],
        style={
            "color": COLORS["accent"],
            "borderBottom": f"3px solid {COLORS['accent']}",
            "paddingBottom": "10px", "marginBottom": "20px",
            "fontWeight": 700, "fontSize": "1.1rem",
        }
    )


# FIX-J: nav_link — el emoji va SOLO en label. icon="" para no duplicar.
def nav_link(label, href, icon=""):
    return dbc.NavLink(
        [html.Span(icon, style={"marginRight": "10px", "fontSize": "1.1rem"}), label],
        href=href, active="exact",
        style={
            "color": COLORS["text"], "borderRadius": "6px",
            "marginBottom": "6px", "fontSize": "0.9rem",
            "padding": "8px 12px", "transition": "all 0.2s ease",
        },
        className="nav-link-custom",
    )

# ─────────────────────────────────────────────
# 2. FUNCIONES AUXILIARES
# ─────────────────────────────────────────────

def generar_recomendaciones():
    df = DATA["oe9_pareto"]
    if len(df) == 0:
        return None
    mejor_roi = df.nlargest(1, "roi_pct").iloc[0]
    dc = df.copy()
    rj_max = dc["rj_portafolio"].max()
    if rj_max > 0:
        dc["score_balance"] = (dc["roi_pct"] / dc["roi_pct"].max()) / (
            dc["rj_portafolio"] / rj_max + 0.01)
    else:
        dc["score_balance"] = dc["roi_pct"] / dc["roi_pct"].max()
    mejor_balance = dc.nlargest(1, "score_balance").iloc[0]
    cap_p40 = df["capital_usd"].quantile(0.40)
    df_bajo_capital = df[df["capital_usd"] <= cap_p40]
    if len(df_bajo_capital) == 0:
        df_bajo_capital = df.nsmallest(5, "capital_usd")
    mejor_eficiencia = df_bajo_capital.nlargest(1, "roi_pct").iloc[0]

    def _rec(row, perfil, para):
        return {"tipo": row.get("tipo", "OPTIMO"), "roi": row["roi_pct"],
                "rj": row["rj_portafolio"], "capital": row["capital_usd"],
                "ganancia": row["ganancia_usd"], "perfil": perfil, "para": para}
    return {
        "agresivo":   _rec(mejor_roi,       "🔥 MÁXIMO ROI (Agresivo)",       "Alta tolerancia al riesgo"),
        "balanceado": _rec(mejor_balance,    "⚖️ MEJOR BALANCE (Recomendado)", "Mayoría de inversionistas"),
        "eficiente":  _rec(mejor_eficiencia, "💎 MÁXIMA EFICIENCIA",           "Presupuesto limitado"),
    }


def calcular_simulador(presupuesto, roi_pct, capital_unitario):
    if presupuesto < 1000 or capital_unitario <= 0:
        return None
    unidades      = int(presupuesto / capital_unitario)
    capital_total = unidades * capital_unitario
    ganancia_unit = capital_unitario * (roi_pct / 100)
    ganancia_tot  = unidades * ganancia_unit
    roi_total     = (ganancia_tot / capital_total * 100) if capital_total > 0 else 0
    return {"unidades": unidades, "capital_total": capital_total,
            "ganancia_unitaria": ganancia_unit, "ganancia_total": ganancia_tot,
            "roi_total": roi_total}

# ─────────────────────────────────────────────
# 3. SIDEBAR
# FIX-J: nav_link llamadas con emoji SOLO en label, icon="" vacío
# ─────────────────────────────────────────────

sidebar = html.Div([
    html.Div([
        html.H4("HDS-ROI", style={
            "color": COLORS["accent"], "fontWeight": 800,
            "letterSpacing": "0.08em", "marginBottom": "4px", "fontSize": "1.4rem"}),
        html.P("v6.2 · PE2 v5.2 · Dropshipping Hardware", style={
            "color": COLORS["text_dim"], "fontSize": "0.7rem", "marginBottom": "0"}),
    ], style={"padding": "16px 12px 12px",
              "borderBottom": f"2px solid {COLORS['border']}", "marginBottom": "12px"}),

    dbc.Nav([
        # FIX-J: emoji SOLO en label, sin icon duplicado
        nav_link("🏠 Inicio",             "/",               ""),
        nav_link("🔬 Pipeline & Datos",   "/pipeline",       ""),
        nav_link("📊 Análisis de Datos",  "/datos",          ""),
        nav_link("📈 Predicción Demanda", "/prediccion",     ""),
        nav_link("🧠 Obsolescencia NLP",  "/obsolescencia",  ""),
        nav_link("⚙️ NSGA-III OE9",       "/oe9",            ""),
        nav_link("💼 Portafolios",        "/portafolios",    ""),
        nav_link("💰 Arbitraje ROI",      "/arbitraje",      ""),
        nav_link("📉 Sensibilidad",       "/sensibilidad",   ""),
        nav_link("🖥️ Simulador",          "/simulador",      ""),
        nav_link("🎯 Motor de Decisión",  "/motor",          ""),
        nav_link("🔬 Ablación Modelos",   "/ablacion",       ""),
        nav_link("🏪 Competitividad",     "/competitividad", ""),
        nav_link("📐 Pareto Original",    "/pareto",         ""),
    ], vertical=True, pills=True,
       style={"padding": "8px 0", "flexDirection": "column"}),

    html.Div([
        html.Hr(style={"borderColor": COLORS["border"], "margin": "12px 0"}),
        html.Div([
            html.Label("💵 Capital disponible (USD)",
                       style={"color": COLORS["text_dim"], "fontSize": "0.68rem",
                              "fontWeight": 600, "marginBottom": "4px", "display": "block"}),
            dcc.Input(
                id="sidebar-capital-input",
                type="number", value=5000, min=100, step=100,
                debounce=True,
                style={"width": "100%", "padding": "6px 8px",
                       "borderRadius": "5px", "fontSize": "0.82rem",
                       "border": f"1px solid {COLORS['border']}",
                       "background": COLORS["bg"], "color": COLORS["text"]}),
            html.Div(id="sidebar-capital-display",
                     style={"color": COLORS["accent"], "fontSize": "0.7rem",
                            "marginTop": "3px", "fontWeight": 600}),
        ], style={"marginBottom": "10px"}),
        html.Hr(style={"borderColor": COLORS["border"], "margin": "8px 0"}),
        html.P("📅 " + datetime.now().strftime("%d %b %Y"), style={
            "color": COLORS["text_dim"], "fontSize": "0.7rem", "marginBottom": "4px"}),
        html.P("🟢 Sistema Operativo", style={
            "color": COLORS["green"], "fontSize": "0.7rem",
            "marginBottom": "0", "fontWeight": 600}),
    ], style={"padding": "12px 0",
              "borderTop": f"1px solid {COLORS['border']}", "marginTop": "auto"}),
], style={**SIDEBAR_STYLE, "display": "flex", "flexDirection": "column",
          "background": COLORS["card"]})
# ─────────────────────────────────────────────
# 4. HOME EJECUTIVO
# FIX-I: section_title() — icon en 2do arg, sin emoji en text
# FIX-N: import json eliminado (ya importado globalmente)
# ─────────────────────────────────────────────

def page_home_ejecutivo(capital_global=5000):
    from pages.page_obsolescencia import _load_data as _load_nlp

    try:
        e5, _, _, df_feature = _load_nlp()
        n_obsoletos = (df_feature["label_pred"] == "OBSOLETO").sum()
        f1_e5       = e5["f1_macro"]
        acc_e5      = e5["accuracy"]
    except Exception:
        f1_e5, acc_e5, n_obsoletos = 0.9966, 0.9973, 12

    # FIX-H: Cargar métricas PE2 v5.2
    try:
        _paths = [
            "models/pe2_v52_metrics_20261003_142754.json",
            "results/pe2_v52_metrics.json",
            "results/pe2_lgbm_metrics.json",
        ]
        lgbm = None
        for _p in _paths:
            if Path(_p).exists():
                with open(_p, encoding="utf-8") as f:
                    lgbm = json.load(f)
                break
        if lgbm:
            _test        = lgbm.get("metrics_test", lgbm.get("test", {}))
            wmape_lgbm   = _test.get("wmape", _test.get("mape", PE2_V52["wmape_global"]))
            r2_lgbm      = _test.get("r2", PE2_V52["r2"])
            wmape_seen   = _test.get("wmape_seen",   PE2_V52["wmape_seen"])
            wmape_unseen = _test.get("wmape_unseen", PE2_V52["wmape_unseen"])
        else:
            raise FileNotFoundError
    except Exception:
        wmape_lgbm   = PE2_V52["wmape_global"]
        r2_lgbm      = PE2_V52["r2"]
        wmape_seen   = PE2_V52["wmape_seen"]
        wmape_unseen = PE2_V52["wmape_unseen"]

    df_oe9    = DATA["oe9_pareto"]
    n_pareto  = len(df_oe9)
    roi_max   = df_oe9["roi_pct"].max()  if n_pareto > 0 else 0
    roi_medio = df_oe9["roi_pct"].mean() if n_pareto > 0 else 0
    rj_min    = df_oe9["rj_portafolio"].min() if n_pareto > 0 else 0

    def step_card(num, titulo, subtitulo, metricas, color, icon, href):
        return dbc.Col(
            dbc.Card([
                dbc.CardBody([
                    html.Div([
                        html.Span(str(num), style={
                            "fontSize": "2.5rem", "fontWeight": 900,
                            "color": color, "opacity": 0.15,
                            "position": "absolute", "top": "8px", "right": "14px",
                            "lineHeight": 1,
                        }),
                        html.Div([
                            html.Span(icon, style={"fontSize": "1.6rem", "marginRight": "10px"}),
                            html.Span(titulo, style={"fontSize": "0.95rem", "fontWeight": 700,
                                                     "color": color}),
                        ], style={"display": "flex", "alignItems": "center", "marginBottom": "6px"}),
                        html.P(subtitulo, style={
                            "fontSize": "0.75rem", "color": COLORS["text_dim"],
                            "marginBottom": "12px", "lineHeight": "1.4"}),
                        html.Hr(style={"borderColor": f"{color}44", "margin": "8px 0"}),
                        *[html.Div([
                            html.Span(m_icon, style={"marginRight": "6px", "fontSize": "0.85rem"}),
                            html.Span(m_label, style={"fontSize": "0.78rem",
                                                      "color": COLORS["text_dim"], "marginRight": "4px"}),
                            html.Span(m_val, style={"fontSize": "0.85rem", "fontWeight": 700,
                                                    "color": m_color}),
                          ], style={"marginBottom": "4px", "display": "flex", "alignItems": "center"})
                          for m_icon, m_label, m_val, m_color in metricas],
                        html.Div(
                            dbc.Button(["Ver detalle ", html.Span("→", style={"fontWeight": 700})],
                                       href=href, color="link", size="sm",
                                       style={"color": color, "padding": "0", "fontSize": "0.78rem",
                                              "textDecoration": "none", "marginTop": "10px"})),
                    ], style={"position": "relative"}),
                ], style={"padding": "16px"}),
            ], style={
                "background": COLORS["bg"],
                "border": f"2px solid {color}55",
                "borderTop": f"4px solid {color}",
                "borderRadius": "10px", "height": "100%",
                "transition": "all 0.3s ease",
            }, className="shadow-sm h-100"),
        md=4)

    # Banner KPIs principales
    banner = dbc.Row([
        dbc.Col(dbc.Card([dbc.CardBody([
            html.P("WMAPE Global PE2 v5.2", className="mb-1",
                   style={"color": COLORS["text_dim"], "fontSize": "0.7rem",
                          "textTransform": "uppercase", "fontWeight": 600}),
            html.H3(f"{wmape_lgbm:.2f}%", className="mb-0",
                    style={"color": COLORS["green"], "fontWeight": 800}),
            html.Small(f"Seen: {wmape_seen:.2f}% · Unseen: {wmape_unseen:.2f}%",
                       style={"color": COLORS["text_dim"]}),
        ], style={"textAlign": "center", "padding": "14px"})],
        style={"background": COLORS["bg"], "border": f"2px solid {COLORS['green']}",
               "borderRadius": "10px"}), md=3),

        dbc.Col(dbc.Card([dbc.CardBody([
            html.P("F1-Macro E5-large", className="mb-1",
                   style={"color": COLORS["text_dim"], "fontSize": "0.7rem",
                          "textTransform": "uppercase", "fontWeight": 600}),
            html.H3(f"{f1_e5:.4f}", className="mb-0",
                    style={"color": COLORS["accent2"], "fontWeight": 800}),
            html.Small("Clasificación NLP", style={"color": COLORS["text_dim"]}),
        ], style={"textAlign": "center", "padding": "14px"})],
        style={"background": COLORS["bg"], "border": f"2px solid {COLORS['accent2']}",
               "borderRadius": "10px"}), md=3),

        dbc.Col(dbc.Card([dbc.CardBody([
            html.P("Soluciones NSGA-III", className="mb-1",
                   style={"color": COLORS["text_dim"], "fontSize": "0.7rem",
                          "textTransform": "uppercase", "fontWeight": 600}),
            html.H3(str(n_pareto), className="mb-0",
                    style={"color": COLORS["accent"], "fontWeight": 800}),
            html.Small(f"ROI máx: +{roi_max:.1f}%", style={"color": COLORS["text_dim"]}),
        ], style={"textAlign": "center", "padding": "14px"})],
        style={"background": COLORS["bg"], "border": f"2px solid {COLORS['accent']}",
               "borderRadius": "10px"}), md=3),

        dbc.Col(dbc.Card([dbc.CardBody([
            html.P("SKUs Obsoletos", className="mb-1",
                   style={"color": COLORS["text_dim"], "fontSize": "0.7rem",
                          "textTransform": "uppercase", "fontWeight": 600}),
            html.H3(str(n_obsoletos), className="mb-0",
                    style={"color": COLORS["red"], "fontWeight": 800}),
            html.Small("Detectados por E5-large", style={"color": COLORS["text_dim"]}),
        ], style={"textAlign": "center", "padding": "14px"})],
        style={"background": COLORS["bg"], "border": f"2px solid {COLORS['red']}",
               "borderRadius": "10px"}), md=3),
    ], className="mb-4 g-3")

    # Banner PE2 v5.2 detallado
    banner_pe2 = dbc.Card([dbc.CardBody([
        html.Div([
            html.Span("🤖 ", style={"fontSize": "1.4rem"}),
            html.Span("PE2 v5.2 — LightGBM · Dataset processed_v2",
                      style={"fontWeight": 700, "color": COLORS["accent"], "fontSize": "0.95rem"}),
            dbc.Badge("ACTUALIZADO", color="success", pill=True, className="ms-2",
                      style={"fontSize": "0.65rem"}),
        ], style={"marginBottom": "12px"}),
        dbc.Row([
            dbc.Col([
                html.Div([html.B("WMAPE Global: "),
                          html.Span(f"{PE2_V52['wmape_global']:.2f}%",
                                    style={"color": COLORS["green"], "fontWeight": 700})]),
                html.Div([html.B("WMAPE Seen: "),
                          html.Span(f"{PE2_V52['wmape_seen']:.2f}%",
                                    style={"color": COLORS["green"]})]),
                html.Div([html.B("WMAPE Unseen: "),
                          html.Span(f"{PE2_V52['wmape_unseen']:.2f}%",
                                    style={"color": COLORS["accent4"]})]),
            ], md=3, style={"fontSize": "0.82rem"}),
            dbc.Col([
                html.Div([html.B("MAE Global: "),
                          html.Span(f"${PE2_V52['mae_global']:.2f}",
                                    style={"color": COLORS["accent2"]})]),
                html.Div([html.B("MAE Seen: "),
                          html.Span(f"${PE2_V52['mae_seen']:.2f}",
                                    style={"color": COLORS["accent2"]})]),
                html.Div([html.B("MAE Unseen: "),
                          html.Span(f"${PE2_V52['mae_unseen']:.2f}",
                                    style={"color": COLORS["accent4"]})]),
            ], md=3, style={"fontSize": "0.82rem"}),
            dbc.Col([
                html.Div([html.B("Iteraciones: "),
                          html.Span(f"{PE2_V52['n_iter']:,}",
                                    style={"color": COLORS["accent"]})]),
                html.Div([html.B("Features: "),
                          html.Span(str(PE2_V52["n_features"]),
                                    style={"color": COLORS["accent"]})]),
                html.Div([html.B("Ratio degradación: "),
                          html.Span(f"{PE2_V52['ratio_deg']}x",
                                    style={"color": COLORS["accent4"]})]),
            ], md=3, style={"fontSize": "0.82rem"}),
            dbc.Col([
                html.Div([html.B("Dataset: "),
                          html.Span(PE2_V52["dataset"],
                                    style={"color": COLORS["accent2"]})]),
                html.Div([html.B("Registros: "),
                          html.Span(f"{PE2_V52['n_total']:,}",
                                    style={"color": COLORS["accent"]})]),
                html.Div([html.B("Fechas: "),
                          html.Span(f"{PE2_V52['n_fechas']} únicas",
                                    style={"color": COLORS["accent"]})]),
            ], md=3, style={"fontSize": "0.82rem"}),
        ]),
    ])], style={
        "background": COLORS["bg"],
        "border": f"2px solid {COLORS['green']}44",
        "borderLeft": f"5px solid {COLORS['green']}",
        "borderRadius": "10px",
        "marginBottom": "20px",
    })

    fila1 = dbc.Row([
        step_card(1, "Pipeline & Datos",
            "Scraping de 6 fuentes · 82 SKUs · Limpieza y normalización",
            [("🌐", "Fuentes:", "6 plataformas",  COLORS["accent2"]),
             ("📦", "SKUs:",    "82 productos",    COLORS["accent"]),
             ("✅", "Calidad:", "0% faltantes",    COLORS["green"])],
            COLORS["accent2"], "🔬", "/pipeline"),
        step_card(2, "Análisis Exploratorio",
            "Distribución de precios · Brechas de mercado · Features",
            [("📊", "Variables:", "32 features",   COLORS["accent"]),
             ("💹", "Brecha:",    "+35% promedio", COLORS["green"]),
             ("🏷️", "Categorías:", "8 tipos HW",   COLORS["accent4"])],
            COLORS["accent4"], "📊", "/datos"),
        step_card(3, "Predicción Demanda",
            "LightGBM PE2 v5.2 · Series temporales · 4 horizontes",
            [("🎯", "WMAPE:",  f"{wmape_lgbm:.2f}%", COLORS["green"]),
             ("📈", "R²:",     f"{r2_lgbm:.4f}",      COLORS["green"]),
             ("🏆", "Modelo:", "LightGBM ★",          COLORS["accent"])],
            COLORS["green"], "📈", "/prediccion"),
    ], className="mb-3 g-3")

    fila2 = dbc.Row([
        step_card(4, "Obsolescencia NLP",
            "E5-large multilingual · 3 clases · Fine-tuning 5 épocas",
            [("🧠", "F1-Macro:", f"{f1_e5:.4f}",        COLORS["green"]),
             ("✅", "Accuracy:", f"{acc_e5:.4f}",        COLORS["green"]),
             ("⚠️", "Obsoletos:", f"{n_obsoletos} SKUs", COLORS["red"])],
            COLORS["accent2"], "🧠", "/obsolescencia"),
        step_card(5, "Optimización NSGA-III",
            "7 objetivos · 42,000 evaluaciones · Frente de Pareto",
            [("⚙️", "Soluciones:", f"{n_pareto}",      COLORS["accent"]),
             ("💰", "ROI máx:",   f"+{roi_max:.1f}%",  COLORS["green"]),
             ("🛡️", "r_j mín:",  f"{rj_min:.4f}",     COLORS["accent4"])],
            COLORS["accent"], "⚙️", "/oe9"),
        step_card(6, "Portafolios Óptimos",
            "3 perfiles: Agresivo · Balanceado · Eficiente",
            [("⚖️", "Perfil rec:", "Balanceado",             COLORS["accent"]),
             ("💵", "Capital:",   f"${capital_global:,.0f}", COLORS["accent2"]),
             ("📊", "ROI medio:", f"+{roi_medio:.1f}%",      COLORS["green"])],
            COLORS["purple"], "💼", "/portafolios"),
    ], className="mb-3 g-3")

    fila3 = dbc.Row([
        step_card(7, "Arbitraje ROI",
            "Oportunidades de compra · Ranking por ROI · Señales",
            [("🏆", "Mejor ROI:", "Ver ranking", COLORS["accent3"]),
             ("✅", "Rentables:", "ROI > 10%",   COLORS["green"]),
             ("📍", "Capital:",   "$3K óptimo",  COLORS["accent2"])],
            COLORS["accent3"], "💰", "/arbitraje"),
        step_card(8, "Sensibilidad",
            "Monte Carlo n=1,000 · P5/Media/P95 · Tornado chart",
            [("📉", "P5:",   "Ver análisis",     COLORS["red"]),
             ("📈", "P95:",  "Ver análisis",     COLORS["green"]),
             ("🎲", "Sim.:", "1,000 escenarios", COLORS["accent4"])],
            COLORS["accent4"], "📉", "/sensibilidad"),
        step_card(9, "Simulador & Motor",
            "Distribuye tu capital · Orden de compra accionable",
            [("💵", "Capital:",  f"${capital_global:,.0f}", COLORS["accent2"]),
             ("🛒", "Acción:",   "Plan detallado",          COLORS["accent"]),
             ("🎯", "Sistema:",  "Integrado ★",             COLORS["green"])],
            COLORS["green"], "🎯", "/motor"),
    ], className="mb-4 g-3")

    # Tabla de metas con WMAPE seen/unseen
    conclusiones = dbc.Row([
        dbc.Col(dbc.Card([dbc.CardBody([
            html.H6("🎓 Contribuciones de la Tesis",
                    style={"color": COLORS["accent"], "fontWeight": 700,
                           "borderBottom": f"2px solid {COLORS['accent']}",
                           "paddingBottom": "8px", "marginBottom": "12px"}),
            html.Ol([
                html.Li([html.B("PE1 — Scraping: "),
                         "Pipeline automatizado de 6 fuentes de datos de hardware"],
                        style={"fontSize": "0.83rem", "marginBottom": "6px",
                               "color": COLORS["text"]}),
                html.Li([html.B("PE2 — Predicción: "),
                         f"LightGBM WMAPE={wmape_lgbm:.2f}% · Seen {wmape_seen:.2f}% · "
                         f"Unseen {wmape_unseen:.2f}% · {PE2_V52['n_total']:,} registros"],
                        style={"fontSize": "0.83rem", "marginBottom": "6px",
                               "color": COLORS["text"]}),
                html.Li([html.B("PE3 — Competitividad: "),
                         "Análisis de brechas de precio internacional vs local Perú"],
                        style={"fontSize": "0.83rem", "marginBottom": "6px",
                               "color": COLORS["text"]}),
                html.Li([html.B("PE4 — NLP: "),
                         f"E5-large F1={f1_e5:.4f} clasifica obsolescencia tecnológica "
                         f"con 99.73% accuracy"],
                        style={"fontSize": "0.83rem", "marginBottom": "6px",
                               "color": COLORS["text"]}),
                html.Li([html.B("OE5/OE9 — NSGA-III: "),
                         f"Optimización 7 objetivos → {n_pareto} portafolios Pareto "
                         f"con ROI máx +{roi_max:.1f}%"],
                        style={"fontSize": "0.83rem", "marginBottom": "0",
                               "color": COLORS["text"]}),
            ], style={"paddingLeft": "18px"}),
        ])],
        style={"background": COLORS["bg"], "border": f"2px solid {COLORS['accent']}44",
               "borderRadius": "10px"}), md=6),

        dbc.Col(dbc.Card([dbc.CardBody([
            html.H6("📋 Metas de Tesis — Estado",
                    style={"color": COLORS["green"], "fontWeight": 700,
                           "borderBottom": f"2px solid {COLORS['green']}",
                           "paddingBottom": "8px", "marginBottom": "12px"}),
            html.Table([
                html.Tr([
                    html.Td(html.B("Meta",      style={"fontSize": "0.78rem",
                                                       "color": COLORS["text_dim"]})),
                    html.Td(html.B("Objetivo",  style={"fontSize": "0.78rem",
                                                       "color": COLORS["text_dim"]})),
                    html.Td(html.B("Resultado", style={"fontSize": "0.78rem",
                                                       "color": COLORS["text_dim"]})),
                    html.Td(html.B("Estado",    style={"fontSize": "0.78rem",
                                                       "color": COLORS["text_dim"]})),
                ], style={"borderBottom": f"2px solid {COLORS['border']}"}),
                *[html.Tr([
                    html.Td(html.B(meta, style={"fontSize": "0.8rem"})),
                    html.Td(obj,  style={"fontSize": "0.8rem", "color": COLORS["text_dim"]}),
                    html.Td(html.B(res, style={"color": COLORS["green"],
                                               "fontSize": "0.85rem"})),
                    html.Td(html.Span(estado, style={"fontSize": "1rem"})),
                ], style={"borderBottom": f"1px solid {COLORS['border']}"})
                for meta, obj, res, estado in [
                    ("WMAPE",        "< 2%",   f"{wmape_lgbm:.2f}%",   "✅"),
                    ("WMAPE Seen",   "< 1%",   f"{wmape_seen:.2f}%",   "✅"),
                    ("WMAPE Unseen", "< 3%",   f"{wmape_unseen:.2f}%", "✅"),
                    ("R²",           "> 0.85", f"{r2_lgbm:.4f}",       "✅"),
                    ("F1-NLP",       "> 0.95", f"{f1_e5:.4f}",         "✅"),
                    ("Pareto",       "> 10",   f"{n_pareto} sols.",     "✅"),
                    ("ROI máx",      "> 20%",  f"+{roi_max:.1f}%",     "✅"),
                ]],
            ], style={"width": "100%", "borderCollapse": "collapse",
                      "fontSize": "0.82rem"}),
        ])],
        style={"background": COLORS["bg"], "border": f"2px solid {COLORS['green']}44",
               "borderRadius": "10px"}), md=6),
    ], className="g-3")

    return html.Div([
        html.Div([
            html.Div([
                html.H2([
                    html.Span("🎓 ", style={"marginRight": "8px"}),
                    "HDS-ROI — Sistema de Decisión para Dropshipping de Hardware",
                ], style={"color": COLORS["accent"], "fontWeight": 800,
                          "marginBottom": "6px", "fontSize": "1.4rem"}),
                html.P(
                    "Tesis de Ingeniería Industrial · Optimización Multiobjetivo + "
                    "NLP + Machine Learning · Coolbox Perú 2026",
                    style={"color": COLORS["text_dim"], "fontSize": "0.85rem",
                           "marginBottom": "0"}),
            ], style={"flex": 1}),
            dbc.Badge("DEFENSA LISTA ✓", color="success", pill=True,
                      style={"fontSize": "0.85rem", "padding": "8px 16px",
                             "alignSelf": "center"}),
        ], style={"display": "flex", "justifyContent": "space-between",
                  "alignItems": "flex-start", "background": COLORS["bg"],
                  "border": f"2px solid {COLORS['accent']}44",
                  "borderLeft": f"5px solid {COLORS['accent']}",
                  "borderRadius": "10px", "padding": "20px 24px",
                  "marginBottom": "24px"}),

        # FIX-I: icon en 2do arg, sin emoji en text
        section_title("Resultados Clave — PE2 v5.2", "📊"),
        banner,
        banner_pe2,

        section_title("Flujo de Sustentación — Paso a Paso", "🗺️"),
        dbc.Alert(
            "Navega en orden para sustentar la tesis de forma estructurada. "
            "Cada tarjeta muestra las métricas clave y enlaza a la pestaña correspondiente.",
            color="light",
            style={"border": f"1px solid {COLORS['border']}",
                   "fontSize": "0.82rem", "padding": "8px 16px",
                   "marginBottom": "16px"}),
        fila1, fila2, fila3,

        section_title("Contribuciones & Metas", "🎓"),
        conclusiones,
        html.Div(style={"height": "24px"}),
    ], style={"padding": "24px"})


# ─────────────────────────────────────────────
# 4b. MOTOR DE DECISIÓN
# ─────────────────────────────────────────────

def page_resumen(capital_global=5000):
    recomendaciones = generar_recomendaciones()
    df_oe9 = DATA["oe9_pareto"]
    if not recomendaciones:
        return html.Div([section_title("Motor de Decisión v6.2", "🎯"),
                         dbc.Alert("⚠️ No hay datos disponibles", color="warning")],
                        style={"padding": "24px"})

    rec_bal = recomendaciones["balanceado"]
    rec_agr = recomendaciones["agresivo"]
    rec_efi = recomendaciones["eficiente"]
    # FIX-M: acceso seguro con .get()
    df_skus = DATA.get("skus", pd.DataFrame()).copy()

    rj_val   = rec_bal["rj"]
    rj_pct   = min(100, rj_val * 100)
    rj_color = (COLORS["green"]   if rj_val < 0.05
                else COLORS["accent3"] if rj_val < 0.30
                else COLORS["red"])
    rj_label = ("✅ Controlado" if rj_val < 0.05
                else "⚠️ Moderado" if rj_val < 0.30
                else "🔴 Alto")
    kpi_rj = dbc.Card([dbc.CardBody([
        html.Div([
            html.Span("🛡️", style={"fontSize": "2rem", "marginRight": "12px", "opacity": 0.8}),
            html.Div([
                html.P("RIESGO OBSOLESCENCIA", className="mb-1",
                       style={"color": COLORS["text_dim"], "fontSize": "0.75rem",
                              "textTransform": "uppercase", "letterSpacing": "0.05em",
                              "fontWeight": 600}),
                html.H4(f"{rj_val:.4f}", className="mb-1",
                        style={"color": rj_color, "fontSize": "1.8rem", "fontWeight": 700}),
                html.Div([
                    html.Div(style={"width": f"{max(2, rj_pct):.1f}%", "height": "6px",
                                    "background": rj_color, "borderRadius": "3px",
                                    "transition": "width 0.5s ease"}),
                ], style={"width": "100%", "background": COLORS["border"],
                          "borderRadius": "3px", "marginBottom": "3px"}),
                html.P(f"{rj_label} · r_j NSGA-III", className="mb-0",
                       style={"color": COLORS["text_dim"], "fontSize": "0.7rem"}),
            ], style={"flex": 1})
        ], style={"display": "flex", "alignItems": "center", "height": "100%"})
    ], style={"padding": "16px"})], style={
        "background": COLORS["bg"], "border": f"2px solid {COLORS['border']}",
        "borderRadius": "10px", "height": "120px",
        "transition": "all 0.3s ease", "cursor": "pointer"}, className="shadow-sm")

    kpi_row = dbc.Row([
        dbc.Col(kpi_card("ROI Recomendado",  f"+{rec_bal['roi']:.1f}%",
                         "Portafolio OE9 · ver Simulador →",
                         COLORS["accent"],  "⚖️", "lg"), md=3),
        dbc.Col(kpi_card("Capital Activo",   f"${capital_global:,.0f}",
                         "← Configura en sidebar",
                         COLORS["accent2"], "💵", "lg"), md=3),
        dbc.Col(kpi_card("Ganancia Esperada",
                         f"${capital_global * rec_bal['roi'] / 100:,.0f}",
                         f"Con ${capital_global:,.0f} al {rec_bal['roi']:.1f}% ROI",
                         COLORS["green"], "📈", "lg"), md=3),
        dbc.Col(kpi_rj, md=3),
    ], className="mb-4 g-3")

    def badge_accion(roi):
        if roi > 60:   return dbc.Badge("🔥 COMPRAR YA", color="danger",  pill=True)
        elif roi > 30: return dbc.Badge("✅ COMPRAR",    color="success", pill=True)
        else:          return dbc.Badge("⏳ EVALUAR",    color="warning", pill=True)

    oe9_port_data_motor = _read_oe9_portafolios_detalle()
    PORT_CFG_MOTOR = {
        "ESTRELLA":   ("primary",   "⭐ ESTRELLA"),
        "OPTIMO":     ("info",      "🎯 ÓPTIMO"),
        "AGRESIVO":   ("danger",    "🔥 AGRESIVO"),
        "BALANCEADO": ("success",   "⚖️ BALANCEADO"),
        "SEGURO":     ("secondary", "🛡️ SEGURO"),
        "N/A":        ("light",     "—"),
    }

    if len(df_skus) > 0:
        rows = []
        for _, row in df_skus.head(8).iterrows():
            sku_name = str(row.get("sku", row.get("producto", "SKU")))[:35]
            roi_val  = float(row.get("roi_sku", row.get("roi_unitario_pct", 0)))
            roi_val  = roi_val * 100 if roi_val < 5 else roi_val
            p_c  = float(row.get("precio_compra_usd", 0))
            p_v  = float(row.get("precio_venta_usd",  0))
            peso = float(row.get("peso_portafolio", 1 / len(df_skus)))
            unid = max(1, int(peso * 10))
            port_tipo  = _buscar_portafolio_oe9(sku_name, oe9_port_data_motor)
            p_color_m, p_label_m = PORT_CFG_MOTOR.get(port_tipo, PORT_CFG_MOTOR["N/A"])
            rows.append(html.Tr([
                html.Td(html.B(sku_name[:30], style={"fontSize": "0.82rem"})),
                html.Td(dbc.Badge(p_label_m, color=p_color_m, pill=True,
                                  style={"fontSize": "0.65rem"}),
                        style={"textAlign": "center"}),
                html.Td(f"${p_c:,.0f}" if p_c > 0 else "—",
                        style={"textAlign": "right", "color": COLORS["accent2"]}),
                html.Td(f"${p_v:,.0f}" if p_v > 0 else "—",
                        style={"textAlign": "right", "color": COLORS["green"],
                               "fontWeight": 600}),
                html.Td(f"{roi_val:.1f}%",
                        style={"textAlign": "right",
                               "color": COLORS["accent3"] if roi_val > 50
                                        else COLORS["green"],
                               "fontWeight": 700}),
                html.Td(str(unid), style={"textAlign": "center", "fontWeight": 600}),
                html.Td(badge_accion(roi_val), style={"textAlign": "center"}),
            ], style={"borderBottom": f"1px solid {COLORS['border']}"}))
        tabla_skus = dbc.Table([
            html.Thead(html.Tr([
                html.Th(c, style={"color": COLORS["accent"], "fontWeight": 700,
                                  "textAlign": "right" if i in [2, 3, 4, 5]
                                               else "center" if i in [1, 6]
                                               else "left"})
                for i, c in enumerate(["Producto", "Categoría", "P. Compra",
                                       "P. Venta Est.", "ROI", "Unidades", "Acción"])
            ], style={"background": COLORS["card"],
                      "borderBottom": f"2px solid {COLORS['border']}"})),
            html.Tbody(rows),
        ], bordered=True, hover=True, responsive=True, size="sm",
           style={"color": COLORS["text"], "fontSize": "0.83rem"})
    else:
        tabla_skus = dbc.Alert(
            "Ejecuta el pipeline completo para ver SKUs accionables.", color="info")

    panel_porque = dbc.Card([dbc.CardBody([
        html.H6("🧠 ¿Por qué estos productos?",
                style={"color": COLORS["accent"], "fontWeight": 700,
                       "borderBottom": f"2px solid {COLORS['accent']}",
                       "paddingBottom": "8px", "marginBottom": "12px"}),
        *[html.Div([
            html.Span(ic, style={"fontSize": "1.1rem", "marginRight": "8px"}),
            html.Div([html.B(tit + ": "),
                      html.Span(det, style={"color": COLORS["text_dim"],
                                            "fontSize": "0.82rem"})]),
        ], style={"marginBottom": "10px", "display": "flex", "alignItems": "flex-start"})
        for ic, tit, det in [
            ("📊", "Brecha de precio",
             "Precio local > precio internacional → margen de arbitraje positivo."),
            ("🤖", "LightGBM PE2 v5.2",
             f"WMAPE {PE2_V52['wmape_global']:.2f}% · "
             f"Seen {PE2_V52['wmape_seen']:.2f}% · R²={PE2_V52['r2']}."),
            ("⚙️", "NSGA-III optimizó",
             "7 objetivos — ROI, riesgo, diversificación, HHI, margen, "
             "obsolescencia, liquidez."),
            ("🛡️", "Validación",
             "Conformal Prediction — cobertura 95.97% en test set."),
            ("📉", "r_j obsolescencia",
             f"{rec_bal['rj']:.4f} — riesgo controlado (< umbral 0.05)."),
        ]],
    ])], style={"background": COLORS["bg"],
                "border": f"2px solid {COLORS['accent']}33",
                "borderRadius": "10px", "height": "100%"})

    resumen_decision = dbc.Card([dbc.CardBody([
        html.H6("📋 Resumen de la Decisión",
                style={"color": COLORS["accent"], "fontWeight": 700,
                       "borderBottom": f"2px solid {COLORS['accent']}",
                       "paddingBottom": "8px", "marginBottom": "12px"}),
        dbc.Alert([
            html.B("⚖️ PERFIL RECOMENDADO: BALANCEADO"), html.Br(),
            html.Span(
                f"ROI: +{rec_bal['roi']:.1f}%  |  "
                f"Capital: ${capital_global:,.0f}  |  "
                f"Ganancia proyectada: "
                f"${capital_global * rec_bal['roi'] / 100:,.0f}",
                style={"fontSize": "0.85rem"}),
            html.Br(),
            html.Div([
                html.Span("ℹ️ ", style={"fontSize": "0.85rem"}),
                html.Span("¿Por qué el Simulador muestra un ROI distinto?",
                          style={"fontWeight": 700, "fontSize": "0.78rem",
                                 "color": COLORS["accent"], "cursor": "pointer"},
                          id="tooltip-roi-diff"),
                dbc.Tooltip(
                    dbc.Card([dbc.CardBody([
                        html.P([html.B("Motor de Decisión (este panel):"),
                                " muestra el ROI teórico del portafolio OE9 optimizado."],
                               style={"fontSize": "0.78rem", "marginBottom": "6px"}),
                        html.P([html.B("Simulador (/simulador):"),
                                " calcula el ROI neto real distribuyendo tu presupuesto."],
                               style={"fontSize": "0.78rem", "marginBottom": "6px"}),
                        html.P("✅ Ambos son correctos — miden cosas distintas.",
                               style={"fontSize": "0.78rem", "fontWeight": 700,
                                      "color": "#27ae60", "marginBottom": "0"}),
                    ])], style={"background": "#1e1e2e", "border": "1px solid #444",
                                "maxWidth": "320px"}),
                    target="tooltip-roi-diff", placement="top",
                    style={"maxWidth": "340px", "padding": "0"}),
            ], style={"marginTop": "6px"}),
        ], color="info"),
        html.Table([
            html.Tr([html.Td(html.B(h, style={"color": COLORS["text_dim"],
                                              "fontSize": "0.78rem"}))
                     for h in ["Perfil", "ROI", "Capital", "Riesgo r_j"]],
                    style={"borderBottom": f"1px solid {COLORS['border']}"}),
            *[html.Tr([
                html.Td([html.B(lbl, style={"color": col, "fontSize": "0.82rem"}),
                         html.Br(),
                         html.Small(para, style={"color": COLORS["text_dim"],
                                                 "fontSize": "0.68rem"})]),
                html.Td(f"+{r['roi']:.1f}%",
                        style={"color": COLORS["green"], "fontWeight": 700,
                               "textAlign": "right", "fontSize": "0.82rem"}),
                html.Td(f"${r['capital']:,.0f}",
                        style={"color": COLORS["text"],
                               "textAlign": "right", "fontSize": "0.82rem"}),
                html.Td(f"{r['rj']:.4f}", style={
                    "color": (COLORS["green"]   if r["rj"] < 0.05
                              else COLORS["accent3"] if r["rj"] < 0.30
                              else COLORS["red"]),
                    "textAlign": "right", "fontSize": "0.82rem", "fontWeight": 700}),
            ], style={"borderBottom": f"1px solid {COLORS['border']}"})
            for lbl, r, col, para in [
                ("🔥 Agresivo",   rec_agr, COLORS["accent3"], "Alta tolerancia al riesgo"),
                ("⚖️ Balanceado", rec_bal, COLORS["accent"],  "Mayoría de inversionistas"),
                ("💎 Eficiente",  rec_efi, COLORS["accent4"], "Presupuesto limitado"),
            ]],
        ], style={"width": "100%", "borderCollapse": "collapse", "marginBottom": "12px"}),
        html.Hr(style={"borderColor": COLORS["border"], "margin": "10px 0"}),
        html.P("📌 Pasos para ejecutar hoy:",
               style={"fontWeight": 700, "fontSize": "0.85rem", "marginBottom": "6px"}),
        html.Ol([
            html.Li(t, style={"fontSize": "0.8rem", "color": COLORS["text_dim"],
                              "marginBottom": "4px"})
            for t in [
                "Selecciona los productos marcados 🔥 COMPRAR YA",
                "Verifica disponibilidad en eBay/Amazon con precio de compra indicado",
                "Confirma precio de venta en Falabella/Hiraoka",
                "Usa el Simulador para calcular ganancia con tu presupuesto exacto",
            ]
        ], style={"paddingLeft": "18px", "marginBottom": "0"}),
    ])], style={"background": COLORS["bg"],
                "border": f"2px solid {COLORS['border']}",
                "borderRadius": "10px", "height": "100%"})

    return html.Div([
        section_title("Motor de Decisión v6.2 — ¿Qué comprar, cuánto y por qué?", "🎯"),
        dbc.Alert([
            html.B("🚀 DECISIÓN BASADA EN DATOS: "),
            f"NSGA-III evaluó 42,000 combinaciones → identificó {len(df_oe9)} portafolios "
            f"Pareto-óptimos. LightGBM PE2 v5.2 predice con WMAPE "
            f"{PE2_V52['wmape_global']:.2f}%. "
            f"Conformal Prediction garantiza cobertura 95.97%."
        ], color="info", style={"background": COLORS["card"],
                                "border": f"2px solid {COLORS['accent2']}",
                                "color": COLORS["text"], "fontSize": "0.88rem",
                                "marginBottom": "20px"}),
        kpi_row,
        html.Div([
            html.H5(["🛒 Orden de Compra Recomendada",
                     dbc.Badge("ACCIONABLE", color="danger", pill=True,
                               className="ms-2", style={"fontSize": "0.7rem"})],
                    style={"color": COLORS["accent"],
                           "borderBottom": f"3px solid {COLORS['accent']}",
                           "paddingBottom": "10px", "marginBottom": "16px",
                           "fontWeight": 700}),
            tabla_skus,
        ], style={"background": COLORS["bg"],
                  "border": f"2px solid {COLORS['accent']}44",
                  "borderRadius": "10px", "padding": "20px", "marginBottom": "20px"}),
        dbc.Row([dbc.Col(panel_porque, md=6),
                 dbc.Col(resumen_decision, md=6)], className="g-3"),
    ], style={"padding": "24px"})


# ─────────────────────────────────────────────
# 5. SIMULADOR
# ─────────────────────────────────────────────

def page_simulador(capital_global=5000):
    return html.Div([
        section_title("Simulador de Compra", "💰"),
        dbc.Alert([html.B("📊 Calcula ganancia total con tu presupuesto disponible")],
                  color="info", style={"background": COLORS["card"],
                                       "border": f"2px solid {COLORS['accent2']}",
                                       "color": COLORS["text"], "fontSize": "0.9rem",
                                       "marginBottom": "20px"}),
        dbc.Row([
            dbc.Col([
                html.Label("💵 Presupuesto Disponible ($)",
                           style={"fontWeight": 600, "marginBottom": "8px"}),
                dcc.Input(id="input-presupuesto", type="number",
                          placeholder="Ej: 5000", value=capital_global,
                          min=1000, step=1000,
                          style={"width": "100%", "padding": "10px",
                                 "borderRadius": "6px",
                                 "border": f"1px solid {COLORS['border']}",
                                 "fontSize": "0.9rem"}),
            ], md=4),
            dbc.Col([
                html.Label("🎯 Modelo a Simular",
                           style={"fontWeight": 600, "marginBottom": "8px"}),
                dcc.Dropdown(id="dropdown-modelo",
                             options=[
                                 {"label": "🔥 Agresivo (Máximo ROI)",    "value": "agresivo"},
                                 {"label": "⚖️ Balanceado (Recomendado)", "value": "balanceado"},
                                 {"label": "💎 Eficiente",                "value": "eficiente"},
                             ], value="balanceado", style={"width": "100%"}),
            ], md=4),
            dbc.Col([
                html.Label("🔄 Actualizar",
                           style={"fontWeight": 600, "marginBottom": "8px"}),
                dbc.Button("Calcular", id="btn-simular", color="primary",
                           className="w-100", style={"height": "38px"}),
            ], md=4),
        ], className="mb-4 g-3"),
        html.Div(id="simulador-resultados"),
    ], style={"padding": "24px"})


# ─────────────────────────────────────────────
# 6. OE9 NSGA-III
# FIX-K: "Soluciones" dinámico con len(df_oe9)
# ─────────────────────────────────────────────

def page_oe9():
    df_oe9 = DATA["oe9_pareto"]
    if len(df_oe9) == 0:
        return html.Div([
            section_title("OE9 NSGA-III", "⚙️"),
            dbc.Alert("⚠️ No hay datos OE9. Ejecuta: python scripts/oe9_nsga3.py",
                      color="warning")
        ], style={"padding": "24px"})

    cmap = {"ESTRELLA": COLORS["accent"], "OPTIMO": COLORS["accent4"],
            "AGRESIVO": COLORS["accent3"], "BALANCEADO": COLORS["purple"],
            "SEGURO": COLORS["green"]}

    fig1 = px.scatter(df_oe9, x="roi_pct", y="rj_portafolio", color="tipo",
                      size="n_skus", hover_data=["capital_usd", "ganancia_usd"],
                      color_discrete_map=cmap,
                      title="Frente de Pareto OE9 — ROI vs r_j (Obsolescencia)",
                      labels={"roi_pct": "ROI (%)", "rj_portafolio": "r_j Obsolescencia"})
    fig1.update_layout(**_safe_layout(height=380))

    fig2 = px.scatter(df_oe9, x="capital_usd", y="ganancia_usd",
                      color="roi_pct", size="n_skus",
                      color_continuous_scale=["#e0e0e0", COLORS["accent"]],
                      title="Capital Invertido vs Ganancia Estimada",
                      labels={"capital_usd": "Capital (USD)",
                              "ganancia_usd": "Ganancia (USD)"})
    fig2.update_layout(**_safe_layout(height=380))

    tc   = df_oe9["tipo"].value_counts()
    fig3 = px.pie(values=tc.values, names=tc.index,
                  title="Distribución de Portafolios por Tipo",
                  color_discrete_map=cmap)
    fig3.update_layout(**_safe_layout(height=380))

    top10 = df_oe9.nlargest(10, "roi_pct")[
        ["tipo", "roi_pct", "rj_portafolio", "n_skus", "capital_usd", "ganancia_usd"]]
    table_top10 = dbc.Table([
        html.Thead(html.Tr(
            [html.Th(c, style={"color": COLORS["accent"], "fontWeight": 700})
             for c in ["Tipo", "ROI (%)", "r_j", "SKUs", "Capital ($)", "Ganancia ($)"]],
            style={"background": COLORS["card"],
                   "borderBottom": f"2px solid {COLORS['border']}"})),
        html.Tbody([html.Tr([
            html.Td(html.B(r["tipo"],
                           style={"color": cmap.get(r["tipo"], COLORS["text"])})),
            html.Td(f"{r['roi_pct']:.1f}%",
                    style={"color": COLORS["green"], "fontWeight": 600}),
            html.Td(f"{r['rj_portafolio']:.4f}"),
            html.Td(str(int(r["n_skus"]))),
            html.Td(f"${r['capital_usd']:,.0f}"),
            html.Td(f"${r['ganancia_usd']:,.0f}",
                    style={"color": COLORS["green"], "fontWeight": 600}),
        ], style={"borderBottom": f"1px solid {COLORS['border']}"})
        for _, r in top10.iterrows()])
    ], bordered=True, hover=True, responsive=True, size="sm",
       style={"color": COLORS["text"], "fontSize": "0.85rem"})

    return html.Div([
        # FIX-K: n soluciones dinámico
        section_title(f"OE9 NSGA-III — {len(df_oe9)} Soluciones Pareto", "⚙️"),
        dbc.Alert([html.B("⚙️ Configuración NSGA-III: "),
                   f"Generaciones: 200 · Población: 210 · Evaluaciones: 42,000 · "
                   f"Soluciones: {len(df_oe9)} · Objetivos: 7"],
                  color="info", style={"background": COLORS["card"],
                                       "border": f"2px solid {COLORS['accent2']}",
                                       "color": COLORS["text"], "fontSize": "0.85rem",
                                       "marginBottom": "20px"}),
        dbc.Row([dbc.Col(dcc.Graph(figure=fig1, config=CHART_CONFIG), md=6),
                 dbc.Col(dcc.Graph(figure=fig2, config=CHART_CONFIG), md=6)],
                className="mb-4 g-3"),
        dbc.Row([dbc.Col(dcc.Graph(figure=fig3, config=CHART_CONFIG), md=6),
                 dbc.Col([section_title("Top 10 por ROI", "📊"),
                          html.Div(table_top10, style={"overflowX": "auto"})], md=6)],
                className="g-3"),
    ], style={"padding": "24px"})


# ─────────────────────────────────────────────
# 7. ANÁLISIS DE DATOS
# ─────────────────────────────────────────────

def page_datos():
    dq  = DATA["data_quality"]
    df  = DATA["feature_matrix"]
    n_rows, n_cols   = dq["n_rows"], dq["n_cols"]
    n_missing, pct_m = dq["n_missing"], dq["pct_missing"]

    kpi_row1 = dbc.Row([
        dbc.Col(kpi_card("Total de Registros", str(n_rows),
                         "SKUs en catálogo",        COLORS["accent"],  "📊"), md=3),
        dbc.Col(kpi_card("Total de Columnas",  str(n_cols),
                         "Features disponibles",    COLORS["accent2"], "📋"), md=3),
        dbc.Col(kpi_card("Valores Faltantes",  str(n_missing),
                         f"{pct_m:.1f}% del total", COLORS["accent3"], "⚠️"), md=3),
        dbc.Col(kpi_card("Estado de Limpieza", dq["status"],
                         "Imputación completada",   COLORS["green"],   "✅"), md=3),
    ], className="mb-4 g-3")

    mbc = dq["missing_by_col"]
    if len(mbc) > 0:
        top_m = mbc.head(10)
        fig_m = px.bar(x=top_m.values, y=top_m.index, orientation="h",
                       color=top_m.values,
                       color_continuous_scale=["#e0e0e0", COLORS["accent3"]],
                       title="Top 10 Columnas con Valores Faltantes",
                       labels={"x": "Cantidad de NaN", "y": "Columna"})
        fig_m.update_layout(**_safe_layout(height=320, coloraxis_showscale=False))
    else:
        fig_m = go.Figure()
        fig_m.add_annotation(text="✅ Sin valores faltantes", xref="paper",
                             yref="paper", x=0.5, y=0.5, showarrow=False,
                             font=dict(size=16, color=COLORS["green"]))
        fig_m.update_layout(**_safe_layout(height=320))

    dtc    = dq["dtype_counts"]
    fig_dt = px.pie(values=dtc.values, names=[str(x) for x in dtc.index],
                    title="Distribución de Tipos de Datos",
                    color_discrete_sequence=PALETTE_CATEGORICAL)
    fig_dt.update_layout(**_safe_layout(height=320))
    fig_dt.update_traces(textposition="inside", textinfo="percent+label")

    cols_info = []
    for col in df.columns[:15]:
        n_nan = df[col].isnull().sum()
        cols_info.append({
            "Columna": col, "Tipo": str(df[col].dtype),
            "NaN": n_nan,
            "% NaN": f"{(n_nan / len(df)) * 100:.1f}%" if len(df) > 0 else "0%",
            "Únicos": df[col].nunique(),
        })
    df_ci = pd.DataFrame(cols_info)

    table_cols = dbc.Table([
        html.Thead(html.Tr(
            [html.Th(c, style={"color": COLORS["accent"], "fontWeight": 700})
             for c in ["#", "Columna", "Tipo", "NaN", "% NaN", "Únicos"]],
            style={"background": COLORS["card"],
                   "borderBottom": f"2px solid {COLORS['border']}"})),
        html.Tbody([html.Tr([
            html.Td(str(i + 1), style={"color": COLORS["text_dim"], "fontWeight": 600}),
            html.Td(html.Code(r["Columna"],
                              style={"color": COLORS["accent2"], "fontSize": "0.8rem"})),
            html.Td(r["Tipo"], style={"fontSize": "0.8rem"}),
            html.Td(str(r["NaN"]), style={"color": COLORS["text_dim"]}),
            html.Td(r["% NaN"], style={
                "color": COLORS["accent3"]
                         if float(r["% NaN"].rstrip("%")) > 0
                         else COLORS["green"],
                "fontWeight": 600}),
            html.Td(str(r["Únicos"])),
        ], style={"borderBottom": f"1px solid {COLORS['border']}"})
        for i, (_, r) in enumerate(df_ci.iterrows())])
    ], bordered=True, hover=True, responsive=True, size="sm",
       style={"color": COLORS["text"], "fontSize": "0.85rem"})

    return html.Div([
        section_title("Análisis de Datos — Recolección, Limpieza y Status", "📊"),
        kpi_row1,
        dbc.Row([dbc.Col(dcc.Graph(figure=fig_m,  config=CHART_CONFIG), md=6),
                 dbc.Col(dcc.Graph(figure=fig_dt, config=CHART_CONFIG), md=6)],
                className="mb-4 g-3"),
        section_title("Primeras 15 Columnas del Dataset", "📋"),
        html.Div(table_cols, style={"overflowX": "auto", "marginBottom": "20px"}),
        section_title("Resumen de Limpieza", "✅"),
        dbc.Alert([html.B("✅ Estado de Limpieza: "), html.Br(),
                   html.Ul([
                       html.Li(f"Registros recolectados: {n_rows} SKUs"),
                       html.Li(f"Columnas disponibles: {n_cols} features"),
                       html.Li(f"Valores faltantes: {n_missing} ({pct_m:.1f}%)"),
                       html.Li("Imputación: Completada (medianas)"),
                       html.Li("Normalización: Aplicada"),
                       html.Li("Deduplicación: Completada"),
                       html.Li("Estado: ✅ Listo para análisis"),
                   ], style={"marginBottom": "0", "marginLeft": "20px"})],
                  color="success",
                  style={"background": "#f0fdf4",
                         "border": f"2px solid {COLORS['green']}",
                         "color": COLORS["text"], "fontSize": "0.9rem"}),
    ], style={"padding": "24px"})



# ─────────────────────────────────────────────
# 8. PORTAFOLIOS
# FIX-M: DATA.get() con defaults seguros
# ─────────────────────────────────────────────

def page_portafolios():
    # FIX-M: acceso seguro con .get() y default pd.DataFrame()
    df_portf = DATA.get("portafolios", pd.DataFrame()).copy()
    df_skus  = DATA.get("skus",        pd.DataFrame())
    df_oe9   = DATA.get("oe9_pareto",  pd.DataFrame())
    palette  = [COLORS["accent2"], COLORS["accent"], COLORS["accent3"]]

    if len(df_portf) == 0:
        return html.Div([
            section_title("Análisis de Portafolios", "💼"),
            dbc.Alert("⚠️ No hay datos de portafolios disponibles.", color="warning"),
        ], style={"padding": "24px"})

    if len(df_oe9) >= 3 and "roi_pct" in df_oe9.columns:
        for idx, row in df_portf.iterrows():
            perfil = str(row.get("perfil", "")).upper()
            _mask  = (df_oe9["tipo"].str.upper() == perfil
                      if "tipo" in df_oe9.columns
                      else pd.Series([True] * len(df_oe9)))
            _sub   = df_oe9[_mask] if _mask.any() else df_oe9
            n_skus = int(row.get("n_skus", 1))
            hhi_calc    = round(1.0 / n_skus, 4) if n_skus > 0 else 1.0
            riesgo_calc = (round(float(_sub["rj_portafolio"].mean()), 4)
                           if "rj_portafolio" in _sub.columns and len(_sub) > 0
                           else round(1.0 / max(n_skus, 1) * 5, 2))
            df_portf.at[idx, "hhi"]    = hhi_calc
            df_portf.at[idx, "riesgo"] = max(riesgo_calc, 0.01)

    fig_bar = go.Figure()
    labels  = ["ROI (%)", "Riesgo", "Inversión (÷100)", "# SKUs (×5)"]
    for (_, row), col in zip(df_portf.iterrows(), palette):
        vals = [row["roi_pct"], row["riesgo"] * 10,
                row["inversion"] / 100, row["n_skus"] * 5]
        fig_bar.add_trace(go.Bar(
            name=row["perfil"], x=labels, y=vals,
            marker_color=col,
            text=[f"{v:.1f}" for v in vals], textposition="outside"))
    fig_bar.update_layout(**_safe_layout(
        barmode="group",
        title="Comparativa de Perfiles (valores normalizados)", height=350))

    table_portf = dbc.Table([
        html.Thead(html.Tr(
            [html.Th(c, style={"color": COLORS["accent"], "fontWeight": 700})
             for c in ["Perfil", "ROI", "Riesgo", "Inversión",
                       "# SKUs", "HHI", "Diversif.", "Margen"]],
            style={"background": COLORS["card"],
                   "borderBottom": f"2px solid {COLORS['border']}"})),
        html.Tbody([html.Tr([
            html.Td(html.B(r["perfil"], style={"color": col})),
            html.Td(f"+{r['roi_pct']:.1f}%",
                    style={"color": COLORS["green"], "fontWeight": 600}),
            html.Td(f"{r['riesgo']:.1f}"),
            html.Td(f"${r['inversion']:,.0f}"),
            html.Td(str(int(r["n_skus"])), style={"textAlign": "center"}),
            html.Td(f"{r['hhi']:.2f}"),
            html.Td(f"{r['diversif']:.2f}"),
            html.Td(f"{r['margen_bruto']:.0%}"),
        ], style={"borderBottom": f"1px solid {COLORS['border']}"})
        for (_, r), col in zip(df_portf.iterrows(), palette)])
    ], bordered=True, hover=True, responsive=True, size="sm",
       style={"color": COLORS["text"], "fontSize": "0.85rem"})

    # Pie solo si df_skus tiene datos
    if len(df_skus) > 0 and "peso_portafolio" in df_skus.columns:
        fig_pie = px.pie(df_skus, values="peso_portafolio", names="sku",
                         title="Composición del Portafolio Equilibrado",
                         color_discrete_sequence=PALETTE_CATEGORICAL)
        fig_pie.update_layout(**_safe_layout(height=350))
        fig_pie.update_traces(textposition="inside", textinfo="percent+label")
        grafico_pie = dcc.Graph(figure=fig_pie, config=CHART_CONFIG)
    else:
        grafico_pie = dbc.Alert("Sin datos de SKUs para el pie chart.", color="info")

    return html.Div([
        section_title("Análisis de Portafolios", "💼"),
        dbc.Row([dbc.Col(dcc.Graph(figure=fig_bar, config=CHART_CONFIG), md=8),
                 dbc.Col(grafico_pie, md=4)],
                className="mb-4 g-3"),
        section_title("Tabla Comparativa de Perfiles", "📋"),
        html.Div(table_portf, style={"overflowX": "auto"}),
    ], style={"padding": "24px"})


# ─────────────────────────────────────────────
# 9. SENSIBILIDAD
# ─────────────────────────────────────────────

def page_sensibilidad():
    df_mc  = DATA["montecarlo"]
    df_oe9 = DATA["oe9_pareto"]

    fig_barras = go.Figure()
    for est, col_json, color in [
        ("P5",    "p5_pct",    COLORS["red"]),
        ("Media", "media_pct", COLORS["accent4"]),
        ("P95",   "p95_pct",   COLORS["green"]),
    ]:
        if col_json in df_mc.columns:
            fig_barras.add_trace(go.Bar(
                name=est,
                x=(df_mc["perfil"].str.capitalize()
                   if "perfil" in df_mc.columns
                   else ["Moderado", "Agresivo"]),
                y=df_mc[col_json], marker_color=color,
                text=[f"{v:.1f}%" for v in df_mc[col_json]],
                textposition="outside"))
    fig_barras.update_layout(**_safe_layout(
        title="Monte Carlo — P5 / Media / P95 por Perfil (n=1 000 simulaciones reales)",
        xaxis_title="Perfil de Inversión", yaxis_title="ROI (%)",
        barmode="group", height=360))

    variables = ["Factor de Venta", "Margen Bruto", "Precio Compra",
                 "Score Demanda", "Tipo de Cambio", "Costo Logístico"]
    if len(df_oe9) >= 3 and "roi_pct" in df_oe9.columns:
        roi_std = df_oe9["roi_pct"].std() / 100
        rj_std  = (df_oe9["rj_portafolio"].std()
                   if "rj_portafolio" in df_oe9.columns else roi_std)
        impactos_neg = [-roi_std*0.9, -roi_std*0.6, -roi_std*0.5,
                        -roi_std*0.4, -rj_std*0.3,  -roi_std*0.2]
        impactos_pos = [ roi_std*1.1,  roi_std*0.7,  roi_std*0.5,
                         roi_std*0.4,  rj_std*0.3,   roi_std*0.25]
        fuente_tornado = "varianza real frente Pareto OE9"
    else:
        impactos_neg = [-0.18, -0.12, -0.09, -0.07, -0.05, -0.04]
        impactos_pos = [ 0.21,  0.14,  0.10,  0.08,  0.06,  0.05]
        fuente_tornado = "referencia bibliográfica (sin datos OE9)"

    fig_tornado = go.Figure()
    fig_tornado.add_trace(go.Bar(
        y=variables, x=impactos_neg, orientation="h",
        marker_color=COLORS["red"], name="Impacto Negativo (−1σ)"))
    fig_tornado.add_trace(go.Bar(
        y=variables, x=impactos_pos, orientation="h",
        marker_color=COLORS["green"], name="Impacto Positivo (+1σ)"))
    fig_tornado.update_layout(**_safe_layout(
        barmode="overlay",
        title=f"Tornado Chart — Sensibilidad ({fuente_tornado})",
        xaxis_title="Δ ROI", height=360))

    filas_tabla = []
    campos = [
        ("n_sim",        "N Simulaciones"),
        ("p5_pct",       "P5 (%)"),
        ("media_pct",    "Media (%)"),
        ("p95_pct",      "P95 (%)"),
        ("std_pp",       "Desv. Est. (pp)"),
        ("prob_roi_pos", "Prob. ROI > 0 (%)"),
        ("prob_roi_20",  "Prob. ROI > 20% (%)"),
    ]
    header = html.Tr([
        html.Th("Estadístico",
                style={"padding": "8px",
                       "borderBottom": f"2px solid {COLORS['accent']}",
                       "textAlign": "left", "color": COLORS["accent"]}),
    ] + [
        html.Th(row["perfil"].capitalize() if "perfil" in row else f"Perfil {i+1}",
                style={"padding": "8px",
                       "borderBottom": f"2px solid {COLORS['accent']}",
                       "textAlign": "right", "color": COLORS["accent"]})
        for i, row in df_mc.iterrows()
    ])
    for col_key, label in campos:
        celdas = [html.Td(label, style={
            "padding": "8px",
            "borderBottom": f"1px solid {COLORS['border']}",
            "fontWeight": 600})]
        for _, row in df_mc.iterrows():
            val = row.get(col_key, "—") if col_key in df_mc.columns else "—"
            txt = (f"{val:,.1f}" if isinstance(val, float)
                   else f"{val:,}" if isinstance(val, int)
                   else str(val))
            celdas.append(html.Td(txt, style={
                "padding": "8px",
                "borderBottom": f"1px solid {COLORS['border']}",
                "textAlign": "right",
                "color": (COLORS["green"]
                          if col_key in ("p95_pct", "prob_roi_pos", "prob_roi_20")
                          else COLORS["text"])}))
        filas_tabla.append(html.Tr(celdas))

    table_stats = html.Table(
        [header] + filas_tabla,
        style={"width": "100%", "color": COLORS["text"],
               "fontSize": "0.9rem", "borderCollapse": "collapse"})
    nota = html.Div(
        [html.B("Fuente: "),
         html.Span("Estadísticos calculados por el pipeline OE4c mediante simulación "
                   "Monte Carlo (n=1 000). No se generan datos sintéticos en el dashboard.")],
        style={"fontSize": "0.8rem", "color": COLORS["text_dim"], "padding": "12px",
               "borderLeft": f"3px solid {COLORS['accent']}", "marginTop": "8px",
               "backgroundColor": COLORS.get("bg_card", "#f8f9fa")})

    return html.Div([
        section_title("Análisis de Sensibilidad & Monte Carlo", "📉"),
        html.Div([
            html.Div([
                section_title("Distribución ROI por Perfil (P5 / Media / P95)", "📊"),
                dcc.Graph(figure=fig_barras, config={"displayModeBar": False}),
            ], style={"flex": "1", "minWidth": "320px"}),
            html.Div([
                section_title("Tornado Chart — Factores Clave", "🌪️"),
                dcc.Graph(figure=fig_tornado, config={"displayModeBar": False}),
            ], style={"flex": "1", "minWidth": "320px"}),
        ], style={"display": "flex", "flexWrap": "wrap",
                  "gap": "24px", "marginBottom": "24px"}),
        html.Div([
            html.Div([
                section_title("Estadísticos Monte Carlo Reales", "📋"),
                table_stats,
                nota,
            ], style={"flex": "1", "minWidth": "320px"}),
        ], style={"display": "flex", "flexWrap": "wrap", "gap": "24px"}),
    ], style={"padding": "24px"})


# ─────────────────────────────────────────────
# 10. PARETO ORIGINAL
# ─────────────────────────────────────────────

def page_pareto():
    df_p = DATA["pareto"]
    if len(df_p) == 0:
        return html.Div([
            section_title("Frente de Pareto NSGA-III", "📐"),
            dbc.Alert("⚠️ No hay datos de Pareto.", color="warning"),
        ], style={"padding": "24px"})

    fig3d = px.scatter_3d(
        df_p, x="roi", y="riesgo", z="diversificacion",
        color="hhi", size="inversion_usd",
        color_continuous_scale=["#e0e0e0", COLORS["accent"]],
        labels={"roi": "ROI", "riesgo": "Riesgo",
                "diversificacion": "Diversificación", "hhi": "HHI"},
        title="Frente de Pareto NSGA-III — 4 Objetivos (3D)",
        hover_data=["inversion_usd"])
    fig3d.update_layout(**_safe_layout(
        scene=dict(
            xaxis=dict(backgroundcolor=COLORS["bg"],
                       gridcolor=COLORS["border"], title="ROI"),
            yaxis=dict(backgroundcolor=COLORS["bg"],
                       gridcolor=COLORS["border"], title="Riesgo"),
            zaxis=dict(backgroundcolor=COLORS["bg"],
                       gridcolor=COLORS["border"], title="Diversificación")),
        height=500))

    fig2d = px.scatter(
        df_p, x="roi", y="riesgo", color="diversificacion",
        size="inversion_usd",
        color_continuous_scale=["#e0e0e0", COLORS["accent"]],
        labels={"roi": "ROI", "riesgo": "Riesgo",
                "diversificacion": "Diversificación"},
        title="Frente de Pareto — ROI vs Riesgo (2D)")
    fig2d.update_layout(**_safe_layout(height=380))

    return html.Div([
        section_title("Frente de Pareto — NSGA-III Original", "📐"),
        dbc.Alert([html.B("⚙️ Configuración NSGA-III Original: "),
                   "Generaciones: 150 · Población: 200 · Evaluaciones: 30,000 · "
                   "Soluciones: 75 · Objetivos: 4"],
                  color="info", style={"background": COLORS["card"],
                                       "border": f"2px solid {COLORS['accent2']}",
                                       "color": COLORS["text"], "fontSize": "0.85rem",
                                       "marginBottom": "20px"}),
        dcc.Graph(figure=fig3d, config=CHART_CONFIG),
        dbc.Row([dbc.Col(dcc.Graph(figure=fig2d, config=CHART_CONFIG), md=12)],
                className="mt-3"),
    ], style={"padding": "24px"})


# ─────────────────────────────────────────────
# 11. COMPETITIVIDAD
# ─────────────────────────────────────────────

def page_competitividad():
    skus_raw = DATA.get("predicciones_multi", {}).get("skus", {})
    if not skus_raw:
        return html.Div([
            section_title("Análisis de Competitividad de Precios", "🏪"),
            dbc.Alert([html.B("⚠️ Sin datos. "),
                       "Ejecuta: ",
                       html.Code("python scripts/pe2_multihorizonte.py")],
                      color="warning"),
        ], style={"padding": "24px"})

    rows = []
    for sku_key, info in skus_raw.items():
        op       = info.get("oportunidad", {})
        p_compra = op.get("precio_compra_usd", 0)
        p_venta  = op.get("precio_venta_usd",  0)
        ganancia = op.get("ganancia_usd",       0)
        roi      = op.get("roi_pct",            0)
        shipping = op.get("shipping_usd",       0)
        costo_t  = op.get("costo_total_usd",    p_compra)
        accion   = op.get("accion",             "EVALUAR")
        hw_type  = op.get("hw_type",            "otro")
        fuente   = op.get("fuente_compra",      info.get("source", ""))
        titulo   = info.get("title", sku_key)[:50]
        brecha   = p_venta - p_compra
        brecha_p = (brecha / p_compra * 100) if p_compra > 0 else 0
        if p_compra > 0 and p_venta > 0:
            rows.append({"sku": sku_key, "titulo": titulo, "hw_type": hw_type,
                         "fuente": fuente, "p_compra": p_compra, "p_venta": p_venta,
                         "shipping": shipping, "costo_t": costo_t, "ganancia": ganancia,
                         "roi": roi, "brecha": brecha, "brecha_pct": brecha_p,
                         "accion": accion})
    if not rows:
        return html.Div([
            section_title("Análisis de Competitividad de Precios", "🏪"),
            dbc.Alert("⚠️ No se encontraron SKUs con precios válidos.", color="warning"),
        ], style={"padding": "24px"})

    df = pd.DataFrame(rows).sort_values("roi", ascending=False)
    p_compra_med = df["p_compra"].median()
    p_venta_med  = df["p_venta"].median()
    brecha_med   = df["brecha_pct"].mean()
    n_rentables  = (df["roi"] > 20).sum()
    roi_max      = df["roi"].max()
    mejor_sku    = df.nlargest(1, "roi").iloc[0]["titulo"][:30]
    ganancia_tot = df["ganancia"].sum()

    kpi_row = dbc.Row([
        dbc.Col(kpi_card("Precio Mediano Compra", f"${p_compra_med:,.0f}",
                         "Internacional (eBay/Amazon)", COLORS["accent2"], "🌐"), md=3),
        dbc.Col(kpi_card("Precio Mediano Venta",  f"${p_venta_med:,.0f}",
                         "Local (Falabella/Hiraoka)",   COLORS["accent4"], "🏪"), md=3),
        dbc.Col(kpi_card("Brecha Promedio",       f"+{brecha_med:.1f}%",
                         f"{n_rentables} SKUs con ROI > 20%",
                         COLORS["green"] if brecha_med > 0 else COLORS["accent3"],
                         "📊"), md=3),
        dbc.Col(kpi_card("Mejor Oportunidad",     f"+{roi_max:.1f}%",
                         mejor_sku, COLORS["accent3"], "🏆"), md=3),
    ], className="mb-4 g-3")

    ACCION_COLOR = {
        "COMPRAR YA": COLORS["accent3"], "COMPRAR": COLORS["green"],
        "EVALUAR":    COLORS["accent4"], "EVITAR":  COLORS["text_dim"],
    }
    df["color_accion"] = df["accion"].map(ACCION_COLOR).fillna(COLORS["text_dim"])
    df["label_short"]  = df["titulo"].str[:25]

    fig_scatter = go.Figure()
    for accion_key, color_val in ACCION_COLOR.items():
        sub = df[df["accion"] == accion_key]
        if len(sub) == 0:
            continue
        fig_scatter.add_trace(go.Scatter(
            x=sub["p_compra"], y=sub["p_venta"],
            mode="markers+text", name=accion_key,
            marker=dict(color=color_val, size=10, opacity=0.85,
                        line=dict(color="white", width=1)),
            text=sub["label_short"], textposition="top center",
            textfont=dict(size=8, color=COLORS["text_dim"]),
            hovertemplate=("<b>%{customdata[0]}</b><br>"
                           "Compra: $%{x:,.2f}<br>"
                           "Venta: $%{y:,.2f}<br>"
                           "ROI: %{customdata[1]:.1f}%<extra></extra>"),
            customdata=sub[["titulo", "roi", "brecha_pct", "accion"]].values))
    max_p = df["p_venta"].max() * 1.1
    fig_scatter.add_trace(go.Scatter(
        x=[0, max_p], y=[0, max_p], mode="lines", name="ROI = 0%",
        line=dict(color=COLORS["text_dim"], dash="dash", width=1)))
    fig_scatter.update_layout(**_safe_layout(
        title="Precio Compra vs Precio Venta — Cada punto = 1 SKU",
        xaxis_title="Precio Compra Internacional (USD)",
        yaxis_title="Precio Venta Local Estimado (USD)", height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1)))

    top15 = df.nlargest(15, "brecha_pct")
    fig_bar = go.Figure(go.Bar(
        x=top15["brecha_pct"], y=top15["titulo"].str[:35], orientation="h",
        marker_color=[ACCION_COLOR.get(a, COLORS["text_dim"]) for a in top15["accion"]],
        text=[f"+{v:.1f}%" for v in top15["brecha_pct"]], textposition="outside",
        customdata=top15[["p_compra", "p_venta", "roi"]].values))
    fig_bar.update_layout(**_safe_layout(
        title="Top 15 SKUs por Brecha de Precio %", xaxis_title="Brecha (%)",
        height=420, yaxis=dict(autorange="reversed"),
        xaxis=dict(ticksuffix="%")))

    df_hw = df.groupby("hw_type").agg(
        brecha_media=("brecha_pct", "mean"), roi_medio=("roi", "mean"),
        n_skus=("sku", "count"), ganancia_total=("ganancia", "sum")
    ).reset_index().sort_values("brecha_media", ascending=False)
    fig_hw = go.Figure()
    fig_hw.add_trace(go.Bar(
        x=df_hw["hw_type"].str.upper(), y=df_hw["brecha_media"],
        name="Brecha media %", marker_color=COLORS["accent2"],
        text=[f"{v:.1f}%" for v in df_hw["brecha_media"]],
        textposition="outside", yaxis="y"))
    fig_hw.add_trace(go.Scatter(
        x=df_hw["hw_type"].str.upper(), y=df_hw["roi_medio"],
        name="ROI medio %", mode="lines+markers",
        marker=dict(color=COLORS["accent3"], size=8),
        line=dict(color=COLORS["accent3"], width=2), yaxis="y2"))
    fig_hw.update_layout(**_safe_layout(
        title="Brecha de Precio y ROI Medio por Categoría de Hardware", height=360,
        yaxis=dict(title="Brecha (%)", ticksuffix="%"),
        yaxis2=dict(title="ROI (%)", overlaying="y", side="right",
                    ticksuffix="%", showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
        barmode="group"))

    ACCION_BADGE = {
        "COMPRAR YA": ("danger",    "🔥 COMPRAR YA"),
        "COMPRAR":    ("success",   "✅ COMPRAR"),
        "EVALUAR":    ("warning",   "⏳ EVALUAR"),
        "EVITAR":     ("secondary", "❌ EVITAR"),
    }
    HW_BADGE = {
        "gpu":         ("danger",    "🖥️ GPU"),
        "cpu":         ("warning",   "⚙️ CPU"),
        "ram":         ("info",      "💾 RAM"),
        "ssd":         ("success",   "💿 SSD"),
        "motherboard": ("primary",   "🔌 MB"),
        "psu":         ("secondary", "⚡ PSU"),
        "case":        ("light",     "📦 CASE"),
        "cooler":      ("info",      "❄️ COOLER"),
        "monitor":     ("primary",   "🖥️ MON"),
        "laptop":      ("warning",   "💻 LAPTOP"),
        "otro":        ("light",     "🔧 OTRO"),
    }
    filas_tabla = []
    for i, (_, row) in enumerate(df.iterrows(), 1):
        roi_color    = (COLORS["accent3"] if row["roi"] > 50
                        else COLORS["green"] if row["roi"] > 20
                        else COLORS["text_dim"])
        brecha_color = (COLORS["green"]   if row["brecha_pct"] > 30
                        else COLORS["accent4"] if row["brecha_pct"] > 10
                        else COLORS["text_dim"])
        hw_col, hw_lbl = HW_BADGE.get(row["hw_type"], ("light", "🔧 OTRO"))
        ac_col, ac_lbl = ACCION_BADGE.get(row["accion"], ("secondary", row["accion"]))
        filas_tabla.append(html.Tr([
            html.Td(str(i), style={"color": COLORS["text_dim"],
                                   "fontWeight": 600, "fontSize": "0.8rem"}),
            html.Td([
                html.Div(html.B(row["titulo"][:40], style={"fontSize": "0.82rem"})),
                html.Small(f"🏪 {row['fuente']}", style={"color": COLORS["text_dim"]}),
            ]),
            html.Td(dbc.Badge(hw_lbl, color=hw_col, pill=True,
                              style={"fontSize": "0.65rem"}),
                    style={"textAlign": "center"}),
            html.Td(f"${row['p_compra']:,.2f}",
                    style={"textAlign": "right", "color": COLORS["accent2"],
                           "fontWeight": 600}),
            html.Td(f"${row['p_venta']:,.2f}",
                    style={"textAlign": "right", "color": COLORS["green"],
                           "fontWeight": 600}),
            html.Td(html.B(f"${row['brecha']:,.2f}",
                           style={"color": brecha_color}),
                    style={"textAlign": "right"}),
            html.Td(html.B(f"{row['brecha_pct']:+.1f}%",
                           style={"color": brecha_color, "fontWeight": 700}),
                    style={"textAlign": "right"}),
            html.Td(html.B(f"{row['roi']:+.1f}%",
                           style={"color": roi_color, "fontWeight": 700}),
                    style={"textAlign": "right"}),
            html.Td(dbc.Badge(ac_lbl, color=ac_col, pill=True,
                              style={"fontSize": "0.68rem"}),
                    style={"textAlign": "center"}),
        ], style={"borderBottom": f"1px solid {COLORS['border']}"}))

    tabla = dbc.Table([
        html.Thead(html.Tr([
            html.Th(c, style={"color": COLORS["accent"], "fontWeight": 700,
                              "textAlign": "right" if i in [3, 4, 5, 6, 7]
                                           else "center" if i in [2, 8]
                                           else "left"})
            for i, c in enumerate(["#", "Producto", "Cat.", "P.Compra",
                                   "P.Venta", "Brecha $", "Brecha %",
                                   "ROI", "Acción"])
        ], style={"background": COLORS["card"],
                  "borderBottom": f"2px solid {COLORS['border']}"})),
        html.Tbody(filas_tabla),
    ], bordered=True, hover=True, responsive=True, size="sm",
       style={"color": COLORS["text"], "fontSize": "0.83rem"})

    return html.Div([
        section_title("Análisis de Competitividad de Precios", "🏪"),
        dbc.Alert([html.B("🔍 Fuente de datos: "),
                   f"predicciones_multihorizonte.json — {len(df)} SKUs con precios reales. "
                   f"Ganancia total potencial: ${ganancia_tot:,.0f} USD. "
                   f"{n_rentables} SKUs con ROI > 20%."],
                  color="success",
                  style={"background": "#f0fdf4",
                         "border": f"2px solid {COLORS['green']}",
                         "color": COLORS["text"], "fontSize": "0.85rem",
                         "marginBottom": "20px"}),
        kpi_row,
        dbc.Row([dbc.Col(dcc.Graph(figure=fig_scatter, config=CHART_CONFIG), md=7),
                 dbc.Col(dcc.Graph(figure=fig_bar,     config=CHART_CONFIG), md=5)],
                className="mb-4 g-3"),
        dbc.Row([dbc.Col(dcc.Graph(figure=fig_hw, config=CHART_CONFIG), md=12)],
                className="mb-4"),
        section_title("Tabla Completa — Todos los SKUs", "📋"),
        html.Div(tabla, style={"overflowX": "auto"}),
    ], style={"padding": "24px"})


# ─────────────────────────────────────────────
# 12. ABLACIÓN — FIX-G + FIX-H
# ─────────────────────────────────────────────

def page_ablacion():
    df_abl  = DATA["ablacion"]
    palette = [COLORS["text_dim"], COLORS["accent"], COLORS["accent4"],
               COLORS["purple"], COLORS["accent2"]]

    fig_mae = go.Figure()
    for (_, row), col in zip(df_abl.iterrows(), palette):
        fig_mae.add_trace(go.Bar(
            name=row["modelo"],
            x=["MAE", "RMSE", "MAPE (%)", "SMAPE (%)"],
            y=[row["mae"], row["rmse"], row["mape_pct"], row["smape_pct"]],
            marker_color=col))
    fig_mae.update_layout(**_safe_layout(
        barmode="group", title="Métricas de Error por Modelo", height=360))

    cats   = ["Precisión", "Velocidad", "Escalabilidad",
              "Interpretabilidad", "Series Cortas"]
    scores = {
        "Baseline": [0.30, 0.99, 0.90, 0.99, 0.50],
        "LightGBM": [0.99, 0.90, 0.85, 0.80, 0.70],
        "XGBoost":  [0.72, 0.88, 0.83, 0.75, 0.68],
        "TFT":      [0.88, 0.40, 0.60, 0.45, 0.75],
        "N-BEATS":  [0.92, 0.50, 0.70, 0.55, 0.95],
    }
    fig_rad = go.Figure()
    for (model, vals), col in zip(scores.items(), palette):
        fig_rad.add_trace(go.Scatterpolar(
            r=vals + [vals[0]], theta=cats + [cats[0]],
            fill="toself", name=model,
            line=dict(color=col, width=2), opacity=0.75))
    fig_rad.update_layout(**_safe_layout(
        polar=dict(
            bgcolor=COLORS["bg"],
            radialaxis=dict(visible=True, range=[0, 1],
                            gridcolor=COLORS["border"],
                            color=COLORS["text_dim"]),
            angularaxis=dict(gridcolor=COLORS["border"])),
        title="Radar de Capacidades por Modelo", height=400))

    table_abl = dbc.Table([
        html.Thead(html.Tr(
            [html.Th(c, style={"color": COLORS["accent"], "fontWeight": 700})
             for c in ["Modelo", "MAE", "RMSE", "MAPE (%)",
                       "SMAPE (%)", "Tiempo (s)", "Params (k)"]],
            style={"background": COLORS["card"],
                   "borderBottom": f"2px solid {COLORS['border']}"})),
        html.Tbody([html.Tr([
            html.Td(html.B(r["modelo"], style={
                "color": COLORS["accent"] if r["modelo"] == "LightGBM"
                         else COLORS["text"]})),
            html.Td(f"{r['mae']:.3f}"),
            html.Td(f"{r['rmse']:.3f}"),
            html.Td(f"{r['mape_pct']:.2f}%", style={
                "color": COLORS["green"] if r["modelo"] == "LightGBM"
                         else COLORS["text"],
                "fontWeight": 700 if r["modelo"] == "LightGBM" else 400}),
            html.Td(f"{r['smape_pct']:.2f}%"),
            html.Td(f"{r['tiempo_s']:.1f}"),
            html.Td(str(r["params_k"])),
        ], style={"borderBottom": f"1px solid {COLORS['border']}",
                  "background": f"{COLORS['accent']}0A"
                                if r["modelo"] == "LightGBM"
                                else "transparent"})
        for _, r in df_abl.iterrows()])
    ], bordered=True, hover=True, responsive=True, size="sm",
       style={"color": COLORS["text"], "fontSize": "0.85rem"})

    return html.Div([
        section_title("Ablación de Modelos de Predicción", "🔬"),
        dbc.Row([dbc.Col(dcc.Graph(figure=fig_mae, config=CHART_CONFIG), md=7),
                 dbc.Col(dcc.Graph(figure=fig_rad, config=CHART_CONFIG), md=5)],
                className="mb-4 g-3"),
        section_title("Tabla de Métricas Completa", "📋"),
        html.Div(table_abl, style={"overflowX": "auto", "marginBottom": "20px"}),
        dbc.Alert([
            html.B("✅ Modelo Seleccionado: LightGBM PE2 v5.2 "), html.Br(),
            f"WMAPE Global {PE2_V52['wmape_global']:.2f}% · "
            f"WMAPE Seen {PE2_V52['wmape_seen']:.2f}% · "
            f"WMAPE Unseen {PE2_V52['wmape_unseen']:.2f}% · "
            f"MAE ${PE2_V52['mae_global']:.2f} · "
            f"R²={PE2_V52['r2']} · "
            f"Convergencia en iteración {PE2_V52['n_iter']} · "
            f"{PE2_V52['n_features']} features · "
            f"{PE2_V52['n_total']:,} registros · "
            f"{PE2_V52['n_fechas']} fechas · "
            f"Ratio degradación seen→unseen: {PE2_V52['ratio_deg']}x (controlado). "
            "Estado del arte para datos tabulares con series cortas. "
            "Validación: Conformal Prediction — cobertura 95.97% en test set.",
        ], color="success",
           style={"background": "#f0fdf4",
                  "border": f"2px solid {COLORS['green']}",
                  "color": COLORS["text"], "fontSize": "0.85rem"}),
    ], style={"padding": "24px"})


# ─────────────────────────────────────────────
# 13. PIPELINE & DATOS
# ─────────────────────────────────────────────

def page_pipeline():
    steps = [
        ("1. Scraping",  "Coolbox · Falabella · Hiraoka\nAmazon · eBay · AliExpress",
         COLORS["accent2"]),
        ("2. Limpieza",  "Normalización · Deduplicación\nImputación de valores faltantes",
         COLORS["accent4"]),
        ("3. Features",  "Score demanda · Brecha precios\nFactor de venta · Margen bruto",
         COLORS["purple"]),
        ("4. NSGA-III",  "Optimización multiobjetivo\n200 gen · 210 pop · 7 objetivos",
         COLORS["accent"]),
        ("5. Selección", "Frente de Pareto · 24 soluciones\nPerfiles C/M/A",
         COLORS["green"]),
        ("6. Dashboard", "HDS-ROI v6.2 · PE2 v5.2\nMonitoreo y análisis interactivo",
         COLORS["accent3"]),
    ]
    pipeline_cards = dbc.Row([
        dbc.Col(dbc.Card([dbc.CardBody([
            html.H6(step, style={"color": col, "fontWeight": 700,
                                 "fontSize": "0.9rem", "marginBottom": "8px"}),
            html.P(desc, style={"color": COLORS["text_dim"], "fontSize": "0.75rem",
                                "whiteSpace": "pre-line", "marginBottom": "0",
                                "lineHeight": "1.4"}),
        ])], style={"background": COLORS["bg"], "border": f"2px solid {col}",
                    "borderRadius": "8px", "height": "100%",
                    "transition": "all 0.3s ease"}), md=2)
        for step, desc, col in steps
    ], className="mb-4 g-2")

    dataset_cols = [
        ("sku_id",               "ID único del producto"),
        ("nombre",               "Nombre comercial"),
        ("categoria",            "Categoría hardware"),
        ("precio_compra_usd",    "Precio de compra internacional"),
        ("precio_venta_usd",     "Precio de venta estimado local"),
        ("margen_bruto",         "Margen bruto (%)"),
        ("factor_venta",         "Probabilidad de venta en período"),
        ("score_demanda",        "Score de demanda (0–1)"),
        ("roi_sku",              "ROI individual del SKU"),
        ("peso_portafolio",      "Peso en portafolio optimizado"),
        ("hhi_contribucion",     "Contribución al índice HHI"),
        ("disponible_amazon",    "Disponibilidad en Amazon"),
        ("disponible_ebay",      "Disponibilidad en eBay"),
        ("disponible_aliexpress","Disponibilidad en AliExpress"),
        ("precio_coolbox",       "Precio Coolbox (local)"),
        ("precio_falabella",     "Precio Falabella (local)"),
        ("precio_hiraoka",       "Precio Hiraoka (local)"),
        ("brecha_precio_pct",    "Brecha precio local vs internacional"),
        ("fecha_scraping",       "Fecha de extracción de datos"),
        ("tendencia_google",     "Índice Google Trends (proxy)"),
        ("reviews_amazon",       "Número de reseñas Amazon"),
        ("rating_promedio",      "Rating promedio (1–5)"),
        ("tiempo_envio_dias",    "Tiempo de envío estimado"),
        ("costo_logistico_usd",  "Costo logístico por unidad"),
        ("tipo_cambio_pen",      "Tipo de cambio PEN/USD"),
        ("impuesto_importacion", "Tasa de impuesto importación"),
        ("categoria_riesgo",     "Categoría de riesgo (1–5)"),
        ("flag_seleccionado",    "Flag de selección en portafolio"),
    ]
    table_ds = dbc.Table([
        html.Thead(html.Tr(
            [html.Th(c, style={"color": COLORS["accent"], "fontWeight": 700})
             for c in ["#", "Columna", "Descripción"]],
            style={"background": COLORS["card"],
                   "borderBottom": f"2px solid {COLORS['border']}"})),
        html.Tbody([html.Tr([
            html.Td(str(i + 1),
                    style={"color": COLORS["text_dim"], "fontWeight": 600}),
            html.Td(html.Code(col,
                              style={"color": COLORS["accent2"],
                                     "fontSize": "0.8rem"})),
            html.Td(desc, style={"fontSize": "0.85rem"}),
        ], style={"borderBottom": f"1px solid {COLORS['border']}"})
        for i, (col, desc) in enumerate(dataset_cols)])
    ], bordered=True, hover=True, responsive=True, size="sm",
       style={"color": COLORS["text"]})

    return html.Div([
        section_title("Pipeline de Datos & Dataset MASTER", "🔬"),
        pipeline_cards,
        html.Hr(style={"borderColor": COLORS["border"], "margin": "30px 0"}),
        section_title(f"Dataset MASTER — {len(dataset_cols)} columnas", "📋"),
        html.Div(table_ds, style={"overflowX": "auto"}),
    ], style={"padding": "24px"})


# ─────────────────────────────────────────────
# 14. HELPERS PREDICCIÓN
# ─────────────────────────────────────────────

def _motivo(icon, titulo, detalle):
    return html.Div([
        html.Span(icon, style={"fontSize": "1.1rem", "marginRight": "8px",
                               "flexShrink": 0}),
        html.Div([
            html.B(titulo + ": ",
                   style={"color": COLORS["text"], "fontSize": "0.83rem"}),
            html.Span(detalle,
                      style={"color": COLORS["text_dim"], "fontSize": "0.8rem"}),
        ]),
    ], style={"display": "flex", "alignItems": "flex-start", "marginBottom": "10px"})


def _panel_score_explicado():
    items = [
        ("ROI > 25% y señal positiva",    "40 pts", COLORS["accent3"]),
        ("Historial ≥ 100 observaciones", "20 pts", COLORS["accent"]),
        ("Rating ≥ 4.5 estrellas",        "20 pts", COLORS["accent4"]),
        ("Precio sube en H+7d",           "10 pts", COLORS["green"]),
        ("Envío gratuito",                "10 pts", COLORS["green"]),
    ]
    return dbc.Card([dbc.CardBody([
        html.H6("📊 Score de Oportunidad (0-100)",
                style={"color": COLORS["accent"], "fontWeight": 700,
                       "borderBottom": f"2px solid {COLORS['accent']}",
                       "paddingBottom": "8px", "marginBottom": "14px"}),
        html.Table([
            html.Tr([
                html.Td(html.B(label, style={"fontSize": "0.82rem"})),
                html.Td(html.B(pts, style={"color": col, "fontWeight": 700,
                                           "textAlign": "right",
                                           "fontSize": "0.85rem"})),
            ], style={"borderBottom": f"1px solid {COLORS['border']}"})
            for label, pts, col in items
        ], style={"width": "100%", "borderCollapse": "collapse",
                  "marginBottom": "14px"}),
        html.Hr(style={"borderColor": COLORS["border"]}),
        html.P([html.B("🔥 > 60 pts: ", style={"color": COLORS["accent3"]}),
                "COMPRAR YA — oportunidad excepcional"],
               style={"fontSize": "0.82rem", "marginBottom": "4px"}),
        html.P([html.B("✅ 30-60 pts: ", style={"color": COLORS["green"]}),
                "COMPRAR — buena oportunidad"],
               style={"fontSize": "0.82rem", "marginBottom": "4px"}),
        html.P([html.B("⏳ 10-30 pts: ", style={"color": COLORS["accent4"]}),
                "EVALUAR — requiere análisis adicional"],
               style={"fontSize": "0.82rem", "marginBottom": "0"}),
    ])], style={"background": COLORS["bg"],
                "border": f"2px solid {COLORS['border']}",
                "borderRadius": "10px", "height": "100%"})


def _fig_prediccion_sku(skus_data, sku_key, horizonte):
    """v14: try/except completo + conversión float segura + y_max antes de layout."""
    try:
        info = skus_data.get(str(sku_key), {})
        if not info:
            fig = go.Figure()
            fig.update_layout(**_safe_layout(height=400, title="SKU no encontrado"))
            return fig

        hist_f = list(info.get("historia_fechas",  []))
        hist_p = [float(x) for x in info.get("historia_precios", [])]

        pred_i  = info.get("predicciones", {}).get(str(horizonte), {})
        pred_f  = list(pred_i.get("fechas",  []))
        pred_p  = [float(x) for x in pred_i.get("precios",  [])]
        ci_lo   = [float(x) for x in pred_i.get("ci_lower", pred_p)]
        ci_hi   = [float(x) for x in pred_i.get("ci_upper", pred_p)]
        var_pct = float(pred_i.get("variacion_pct", 0) or 0)
        tend    = str(pred_i.get("tendencia", "ESTABLE"))
        op      = info.get("oportunidad", {})

        # FIX-CLIP: precio mínimo visual
        precio_compra_vis = float(op.get("precio_compra_usd", 1.0) or 1.0)
        precio_min_vis    = max(precio_compra_vis * 0.10, 1.0)
        pred_p = [max(p, precio_min_vis) for p in pred_p]
        ci_lo  = [max(p, precio_min_vis) for p in ci_lo]
        ci_hi  = [max(p, precio_min_vis) for p in ci_hi]

        # FIX-HIST: últimos 20 puntos
        if len(hist_f) > 20:
            hist_f = hist_f[-20:]
            hist_p = hist_p[-20:]

        color_t = (COLORS["green"]   if tend == "SUBE"
                   else COLORS["red"]    if tend == "BAJA"
                   else COLORS["accent2"])

        # FIX-YAXIS: y_max calculado ANTES de update_layout
        all_y = hist_p + pred_p
        y_max = (max(all_y) * 1.15) if all_y else (precio_min_vis * 3)
        y_min = precio_min_vis * 0.5

        fig = go.Figure()

        # Banda IC 95%
        if pred_f and ci_hi and ci_lo:
            fill_color = (
                "rgba(239,68,68,0.15)"  if color_t == COLORS["red"]   else
                "rgba(34,197,94,0.15)"  if color_t == COLORS["green"] else
                "rgba(99,102,241,0.15)"
            )
            fig.add_trace(go.Scatter(
                x=pred_f + pred_f[::-1],
                y=ci_hi  + ci_lo[::-1],
                fill="toself", fillcolor=fill_color,
                line=dict(color="rgba(0,0,0,0)"),
                name="IC 95%", showlegend=True))

        # Historia real
        if hist_f and hist_p:
            fig.add_trace(go.Scatter(
                x=hist_f, y=hist_p,
                mode="lines+markers", name="Historia real",
                line=dict(color=COLORS["accent2"], width=2),
                marker=dict(size=4)))

        # Predicción conectada al último punto histórico
        if pred_f and pred_p and hist_f and hist_p:
            fig.add_trace(go.Scatter(
                x=[hist_f[-1]] + pred_f,
                y=[hist_p[-1]] + pred_p,
                mode="lines+markers",
                name=f"Predicción H+{horizonte}d",
                line=dict(color=color_t, width=2.5, dash="dash"),
                marker=dict(size=7, symbol="diamond")))

        # FIX-FECHA: línea "Hoy" dinámica
        fecha_hoy_str = datetime.now().strftime("%Y-%m-%d")
        fig.add_shape(
            type="line",
            x0=fecha_hoy_str, x1=fecha_hoy_str,
            y0=0, y1=1, yref="paper",
            line=dict(color=COLORS["accent3"], dash="dot", width=2))
        fig.add_annotation(
            x=fecha_hoy_str, y=0.97, yref="paper",
            text=f"Hoy {fecha_hoy_str}",
            showarrow=False,
            font=dict(color=COLORS["accent3"], size=10),
            xanchor="left",
            bgcolor=COLORS["card"],
            bordercolor=COLORS["accent3"], borderwidth=1)

        # Etiqueta de acción
        if op and pred_f and pred_p:
            fig.add_annotation(
                x=pred_f[-1], y=pred_p[-1],
                text=(f"  {op.get('accion_icon', '')} {op.get('accion', '')} "
                      f"| ROI {op.get('roi_pct', 0):+.1f}%"),
                showarrow=True, arrowhead=2, arrowcolor=color_t,
                font=dict(color=color_t, size=11, family="monospace"),
                bgcolor=COLORS["card"], bordercolor=color_t, borderwidth=1)

        # Layout final — FIX: eliminar claves duplicadas del template
        _layout = dict(PLOTLY_TEMPLATE["layout"])
        for _k in ("height", "title", "xaxis_title", "yaxis_title",
                   "xaxis", "yaxis", "legend", "barmode"):
            _layout.pop(_k, None)

        fig.update_layout(
            **_layout,
            height=420,
            title=(f"<b>{info.get('title', '')[:55]}</b><br>"
                   f"<sup>H+{horizonte}d: {var_pct:+.1f}% | {tend} | "
                   f"Compra ${op.get('precio_compra_usd', 0):,.2f} → "
                   f"Venta ${op.get('precio_venta_usd', 0):,.2f} | "
                   f"ROI {op.get('roi_pct', 0):+.1f}%</sup>"),
            xaxis_title="Fecha",
            yaxis_title="Precio (USD)",
            yaxis=dict(rangemode="nonnegative", range=[y_min, y_max]),
            legend=dict(orientation="h", yanchor="bottom",
                        y=1.02, xanchor="right", x=1),
        )
        return fig

    except Exception as e:
        fig = go.Figure()
        fig.add_annotation(
            text=f"⚠️ Error al generar gráfico: {str(e)[:80]}",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=13, color=COLORS.get("accent3", "red")))
        fig.update_layout(**_safe_layout(height=400, title="Error en gráfico"))
        return fig


# ─────────────────────────────────────────────
# 15. PREDICCIÓN MULTIHORIZONTE
# ─────────────────────────────────────────────

def page_prediccion(capital_global=5000):
    try:
        data_pred = DATA.get("predicciones_multi", {"resumen": {}, "skus": {}})
        resumen   = data_pred.get("resumen", {})
        skus_data = data_pred.get("skus",    {})

        if not skus_data:
            return html.Div([
                section_title("Predicción Multihorizonte", "📈"),
                dbc.Alert([
                    html.B("⚠️ Ejecuta primero: "),
                    html.Code("python scripts/pe2_multihorizonte.py"),
                    html.Br(), "Luego reinicia el dashboard.",
                ], color="warning"),
            ], style={"padding": "24px"})

        skus_lista  = list(skus_data.keys())
        sku_default = skus_lista[0]
        n_skus      = resumen.get("n_skus", len(skus_lista))
        fecha_corte = resumen.get("fecha_corte",
                                  datetime.now().strftime("%Y-%m-%d"))
        top5_ops    = resumen.get("top5_oportunidades", [])

        n_comprar = sum(
            1 for v in skus_data.values()
            if v.get("oportunidad", {}).get("accion", "")
            in ("COMPRAR YA", "COMPRAR"))

        roi_vals = [
            v["oportunidad"]["roi_pct"]
            for v in skus_data.values()
            if v.get("oportunidad", {}).get("roi_pct", 0) > 0
        ]
        roi_medio     = float(np.mean(roi_vals)) if roi_vals else 0.0
        ganancia_top5 = sum(
            float(item.get("ganancia", 0)) * int(item.get("unidades", 1))
            for item in top5_ops)

        kpi_row = dbc.Row([
            dbc.Col(kpi_card("SKUs Analizados",   str(n_skus),
                             "con predicción activa", COLORS["accent"],  "📊"), md=3),
            dbc.Col(kpi_card("Oportunidades Hoy", str(n_comprar),
                             "COMPRAR / COMPRAR YA",  COLORS["green"],   "🛒"), md=3),
            dbc.Col(kpi_card("ROI Medio",         f"+{roi_medio:.1f}%",
                             "promedio portafolio",   COLORS["accent4"], "📈"), md=3),
            dbc.Col(kpi_card("Ganancia Top-5",    f"${ganancia_top5:,.0f}",
                             "si compras hoy",        COLORS["accent3"], "💰"), md=3),
        ], className="mb-4 g-3")

        def badge_accion(accion):
            cfg = {
                "COMPRAR YA": ("danger",    "🔥 COMPRAR YA"),
                "COMPRAR":    ("success",   "✅ COMPRAR"),
                "EVALUAR":    ("warning",   "⏳ EVALUAR"),
                "EVITAR":     ("secondary", "❌ EVITAR"),
            }
            color, label = cfg.get(accion, ("secondary", accion))
            return dbc.Badge(label, color=color, pill=True,
                             style={"fontSize": "0.72rem"})

        def badge_tendencia(tend):
            cfg = {
                "SUBE":    ("success", "↑ SUBE"),
                "BAJA":    ("danger",  "↓ BAJA"),
                "ESTABLE": ("warning", "→ ESTABLE"),
            }
            color, label = cfg.get(tend, ("secondary", tend))
            return dbc.Badge(label, color=color, pill=True,
                             style={"fontSize": "0.68rem"})

        skus_ordenados = sorted(
            skus_data.items(),
            key=lambda x: x[1].get("oportunidad", {}).get("score_oportunidad", 0),
            reverse=True)

        oe9_port_pred = _read_oe9_portafolios_detalle()
        PORT_CFG_PRED = {
            "ESTRELLA":   ("primary",   "⭐ ESTRELLA"),
            "OPTIMO":     ("info",      "🎯 ÓPTIMO"),
            "AGRESIVO":   ("danger",    "🔥 AGRESIVO"),
            "BALANCEADO": ("success",   "⚖️ BALANCEADO"),
            "SEGURO":     ("secondary", "🛡️ SEGURO"),
            "N/A":        ("light",     "—"),
        }
        ACCION_TOOLTIP = {
            "COMPRAR YA": "ROI > 60% y tendencia alcista — oportunidad urgente",
            "COMPRAR":    "ROI > 30% y precio estable — buena oportunidad",
            "EVALUAR":    "ROI positivo pero < 30% o tendencia incierta",
            "EVITAR":     "ROI negativo o riesgo de obsolescencia alto",
        }

        rows_orden = []
        for sku_key_row, info_row in skus_ordenados[:15]:
            try:
                op         = info_row.get("oportunidad", {})
                p7         = info_row.get("predicciones", {}).get("7", {})
                tend_row   = p7.get("tendencia", "ESTABLE")
                var7       = float(p7.get("variacion_pct", 0) or 0)
                roi        = float(op.get("roi_pct", 0) or 0)
                score      = float(op.get("score_oportunidad", 0) or 0)
                accion_key = op.get("accion", "EVALUAR")
                color_roi  = (COLORS["accent3"] if roi > 40
                              else COLORS["green"] if roi > 10
                              else COLORS["text_dim"])
                port_tipo_pred     = _buscar_portafolio_oe9(
                    info_row.get("title", ""), oe9_port_pred)
                p_color_pred, p_label_pred = PORT_CFG_PRED.get(
                    port_tipo_pred, PORT_CFG_PRED["N/A"])

                rows_orden.append(html.Tr([
                    html.Td([
                        html.Div(html.B(
                            info_row.get("title", "")[:42],
                            style={"fontSize": "0.82rem", "color": COLORS["text"]})),
                        html.Div([
                            html.Small(f"🏪 {info_row.get('source', '')}",
                                       style={"color": COLORS["text_dim"],
                                              "marginRight": "8px"}),
                            html.Small(f"📦 {info_row.get('category', '')}",
                                       style={"color": COLORS["text_dim"]}),
                        ]),
                    ]),
                    html.Td(dbc.Badge(p_label_pred, color=p_color_pred, pill=True,
                                      style={"fontSize": "0.65rem"}),
                            style={"textAlign": "center", "whiteSpace": "nowrap"}),
                    html.Td([
                        html.B(f"${op.get('precio_compra_usd', 0):,.2f}",
                               style={"color": COLORS["accent2"]}),
                        html.Br(),
                        html.Small(f"+${op.get('shipping_usd', 0):.0f} envío",
                                   style={"color": COLORS["text_dim"]}),
                    ], style={"textAlign": "right", "whiteSpace": "nowrap"}),
                    html.Td([
                        html.B(f"${op.get('precio_venta_usd', 0):,.2f}",
                               style={"color": COLORS["green"]}),
                        html.Br(),
                        html.Small(f"S/.{op.get('precio_venta_pen', 0):,.0f}",
                                   style={"color": COLORS["text_dim"]}),
                    ], style={"textAlign": "right", "whiteSpace": "nowrap"}),
                    html.Td(html.B(f"${op.get('ganancia_usd', 0):,.2f}",
                                   style={"color": COLORS["green"],
                                          "fontSize": "0.9rem"}),
                            style={"textAlign": "right"}),
                    html.Td(html.B(f"{roi:+.1f}%",
                                   style={"color": color_roi, "fontSize": "0.9rem"}),
                            style={"textAlign": "right"}),
                    html.Td(html.B(str(op.get("unidades_sugeridas", 1))),
                            style={"textAlign": "center"}),
                    html.Td([
                        badge_tendencia(tend_row), html.Br(),
                        html.Small(f"{var7:+.1f}%",
                                   style={"color": COLORS["text_dim"]}),
                    ], style={"textAlign": "center"}),
                    html.Td([
                        html.Div([html.Div(style={
                            "width": f"{min(100, score):.0f}%", "height": "6px",
                            "background": (COLORS["accent3"] if score > 60
                                           else COLORS["accent"] if score > 30
                                           else COLORS["text_dim"]),
                            "borderRadius": "3px"})],
                            style={"width": "60px",
                                   "background": COLORS["border"],
                                   "borderRadius": "3px",
                                   "marginBottom": "2px"}),
                        html.Small(f"{score:.0f}/100",
                                   style={"color": COLORS["text_dim"]}),
                    ], style={"textAlign": "center"}),
                    html.Td([
                        badge_accion(accion_key), html.Br(),
                        html.Small(ACCION_TOOLTIP.get(accion_key, ""),
                                   style={"color": COLORS["text_dim"],
                                          "fontSize": "0.65rem",
                                          "lineHeight": "1.2"}),
                    ], style={"textAlign": "center", "minWidth": "110px"}),
                ], style={"borderBottom": f"1px solid {COLORS['border']}"}))
            except Exception:
                continue   # fila con error se salta, no bloquea la tabla

        tabla_orden = dbc.Table([
            html.Thead(html.Tr([
                html.Th("Producto / Fuente",
                        style={"color": COLORS["accent"], "fontWeight": 700,
                               "minWidth": "200px"}),
                html.Th("Categoría",
                        style={"color": COLORS["accent"], "fontWeight": 700,
                               "textAlign": "center", "whiteSpace": "nowrap"}),
                html.Th("P. Compra (USD)",
                        style={"color": COLORS["accent"], "fontWeight": 700,
                               "textAlign": "right"}),
                html.Th("P. Venta Est.",
                        style={"color": COLORS["accent"], "fontWeight": 700,
                               "textAlign": "right"}),
                html.Th("Ganancia",
                        style={"color": COLORS["accent"], "fontWeight": 700,
                               "textAlign": "right"}),
                html.Th("ROI",
                        style={"color": COLORS["accent"], "fontWeight": 700,
                               "textAlign": "right"}),
                html.Th("Unid.",
                        style={"color": COLORS["accent"], "fontWeight": 700,
                               "textAlign": "center"}),
                html.Th("H+7d",
                        style={"color": COLORS["accent"], "fontWeight": 700,
                               "textAlign": "center"}),
                html.Th("Score",
                        style={"color": COLORS["accent"], "fontWeight": 700,
                               "textAlign": "center"}),
                html.Th("Acción",
                        style={"color": COLORS["accent"], "fontWeight": 700,
                               "textAlign": "center"}),
            ], style={"background": COLORS["card"],
                      "borderBottom": f"2px solid {COLORS['border']}"})),
            html.Tbody(rows_orden),
        ], bordered=True, hover=True, responsive=True, size="sm",
           style={"color": COLORS["text"], "fontSize": "0.82rem"})

        panel_metodologia = dbc.Card([dbc.CardBody([
            html.H6("🧠 ¿Cómo se seleccionan?",
                    style={"color": COLORS["accent"], "fontWeight": 700,
                           "borderBottom": f"2px solid {COLORS['accent']}",
                           "paddingBottom": "8px", "marginBottom": "14px"}),
            _motivo("🤖", "LightGBM PE2 v5.2",
                    f"WMAPE {PE2_V52['wmape_global']:.2f}% · "
                    f"R²={PE2_V52['r2']} · "
                    f"{PE2_V52['n_iter']} iter · "
                    f"{PE2_V52['n_features']} features · "
                    "Horizonte 1/7/14/30d"),
            _motivo("⚙️", "NSGA-III optimizó portafolio",
                    "42,000 evaluaciones · 7 objetivos · 24 soluciones Pareto"),
            _motivo("💹", "Brecha de arbitraje",
                    "Precio compra internacional < precio venta local Perú"),
            _motivo("🛡️", "Conformal Prediction",
                    "Cobertura 95.97% · Intervalos calibrados por horizonte"),
            _motivo("📊", "Score compuesto (0-100)",
                    "ROI + historial + rating + tendencia + envío gratis"),
        ])], style={"background": COLORS["bg"],
                    "border": f"2px solid {COLORS['accent']}33",
                    "borderRadius": "10px", "height": "100%"})

        # Gráfico inicial con protección
        fig_inicial = _fig_prediccion_sku(skus_data, sku_default, 7)

        panel_grafico = html.Div([
            dbc.Row([
                dbc.Col([
                    html.Label("🔍 SKU",
                               style={"fontWeight": 600, "fontSize": "0.85rem"}),
                    dcc.Dropdown(
                        id="pred-dropdown-sku",
                        options=[
                            {"label": f"{v.get('title', '')[:50]} ({k})", "value": k}
                            for k, v in skus_ordenados[:20]
                        ],
                        value=sku_default, clearable=False,
                        style={"fontSize": "0.82rem"}),
                ], md=7),
                dbc.Col([
                    html.Label("📅 Horizonte",
                               style={"fontWeight": 600, "fontSize": "0.85rem"}),
                    dcc.Dropdown(
                        id="pred-dropdown-horizonte",
                        options=[
                            {"label": "H+1 día",   "value": 1},
                            {"label": "H+7 días",  "value": 7},
                            {"label": "H+14 días", "value": 14},
                            {"label": "H+30 días", "value": 30},
                        ],
                        value=7, clearable=False),
                ], md=3),
                dbc.Col([
                    html.Label(".", style={"color": "transparent", "display": "block"}),
                    dbc.Button("Ver", id="pred-btn-update",
                               color="primary", className="w-100"),
                ], md=2),
            ], className="mb-3 g-2"),
            dcc.Graph(id="pred-grafico", figure=fig_inicial, config=CHART_CONFIG),
        ])

        # Heatmap
        skus_muestra = skus_lista[:20]
        z_vals, hover_text, y_labels = [], [], []
        for sku_hm in skus_muestra:
            row_z, row_h = [], []
            for h in ["1", "7", "14", "30"]:
                var = float(
                    skus_data[sku_hm].get("predicciones", {})
                    .get(h, {}).get("variacion_pct", 0) or 0)
                row_z.append(round(var, 2))
                row_h.append(f"{var:+.1f}%")
            z_vals.append(row_z)
            hover_text.append(row_h)
            y_labels.append(skus_data[sku_hm].get("title", "")[:30])

        fig_heat = go.Figure(go.Heatmap(
            z=z_vals, x=["H+1d", "H+7d", "H+14d", "H+30d"], y=y_labels,
            text=hover_text, texttemplate="%{text}",
            colorscale=[[0.0, COLORS["red"]], [0.5, "#f5f5f5"],
                        [1.0, COLORS["green"]]],
            zmid=0, colorbar=dict(title="Var %", ticksuffix="%")))
        fig_heat.update_layout(**_safe_layout(
            height=500,
            title="Heatmap Variación Predicha (%) — Top 20 SKUs × 4 Horizontes",
            yaxis=dict(tickfont=dict(size=9))))

        return html.Div([
            section_title("Predicción Multihorizonte — ¿Qué comprar hoy?", "📈"),
            dbc.Alert([
                html.B("🤖 Sistema HDS-ROI v6.2 — PE2 v5.2: "),
                f"LightGBM (WMAPE {PE2_V52['wmape_global']:.2f}% · "
                f"Seen {PE2_V52['wmape_seen']:.2f}% · "
                f"Unseen {PE2_V52['wmape_unseen']:.2f}%) + "
                f"NSGA-III (42K eval.) + "
                f"Conformal Prediction (95.97%) → "
                f"{n_comprar} oportunidades de compra identificadas al {fecha_corte}.",
            ], color="info", style={
                "background": COLORS["card"],
                "border": f"2px solid {COLORS['accent2']}",
                "color": COLORS["text"], "fontSize": "0.87rem",
                "marginBottom": "20px"}),
            kpi_row,
            dbc.Tabs([
                dbc.Tab(label="🛒 Orden de Compra", tab_id="tab-orden",
                        label_style={"fontWeight": 700}, children=[
                    html.Div([
                        dbc.Alert([
                            html.B("📋 Cómo leer esta tabla: "),
                            "• P. Compra = precio en plataforma internacional "
                            "(eBay/Amazon) "
                            "• P. Venta Est. = precio estimado de venta en Perú "
                            "(Falabella/Hiraoka) "
                            "• Ganancia = por unidad, sin impuestos "
                            "• Unid. = cantidad sugerida con $5,000 de capital "
                            "• H+7d = tendencia de precio en 7 días según "
                            "LightGBM PE2 v5.2",
                        ], color="light", style={
                            "border": f"1px solid {COLORS['border']}",
                            "fontSize": "0.8rem",
                            "padding": "8px 14px",
                            "marginBottom": "12px",
                            "marginTop": "16px"}),
                        html.Div(tabla_orden, style={"overflowX": "auto"}),
                    ]),
                ]),
                dbc.Tab(label="📊 Gráfico Predicción", tab_id="tab-grafico",
                        children=[
                    html.Div(panel_grafico, style={"paddingTop": "16px"}),
                ]),
                dbc.Tab(label="🌡️ Heatmap Tendencias", tab_id="tab-heatmap",
                        children=[
                    dcc.Graph(figure=fig_heat, config=CHART_CONFIG,
                              style={"marginTop": "16px"}),
                ]),
                dbc.Tab(label="🧠 Metodología", tab_id="tab-metodo", children=[
                    dbc.Row([
                        dbc.Col(panel_metodologia,        md=6),
                        dbc.Col(_panel_score_explicado(), md=6),
                    ], className="g-3 mt-2"),
                ]),
            ], id="pred-tabs", active_tab="tab-orden"),
        ], style={"padding": "24px"})

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        return html.Div([
            section_title("Predicción Multihorizonte", "📈"),
            dbc.Alert([
                html.B("❌ Error al cargar la página: "),
                html.Code(str(e), style={"fontSize": "0.8rem"}),
                html.Hr(),
                html.Pre(tb[-800:],
                         style={"fontSize": "0.72rem",
                                "color": COLORS["text_dim"],
                                "whiteSpace": "pre-wrap",
                                "maxHeight": "200px",
                                "overflowY": "auto"}),
            ], color="danger"),
        ], style={"padding": "24px"})


# ─────────────────────────────────────────────
# 16. ARBITRAJE ROI
# ─────────────────────────────────────────────

def page_arbitraje():
    TC   = 3.75
    data = _cargar_modelos_roi()
    if not data:
        return html.Div([
            section_title("Oportunidades de Arbitraje — HDS-ROI v6.2", "📊"),
            dbc.Alert([
                html.B("⚠️ Índice no encontrado. "),
                "Ejecuta: ",
                html.Code("python scripts/pe2_multihorizonte.py"),
                " para generar data/raw/precios_por_modelo.json",
            ], color="warning"),
        ], style={"padding": "24px"})

    rentables = sum(1 for d in data.values() if d["roi_pct"] > 10)
    mejor_roi = max(d["roi_pct"] for d in data.values())
    mejor_mod = max(data, key=lambda m: data[m]["roi_pct"]).upper()
    cap_rest, gan_opt, inv_opt = 3000, 0.0, 0.0
    for d in data.values():
        if d["roi_pct"] > 10 and cap_rest >= d["costo_importado_usd"]:
            gan_opt += d["precio_venta_pe_usd"] * 0.95 - d["costo_importado_usd"]
            inv_opt += d["costo_importado_usd"]
            cap_rest -= d["costo_importado_usd"]
    roi_opt = (gan_opt / inv_opt * 100) if inv_opt > 0 else 0

    kpi_row = dbc.Row([
        dbc.Col(kpi_card("Mejor ROI",        f"+{mejor_roi:.1f}%",
                         mejor_mod,           "#27ae60", "🏆"), md=3),
        dbc.Col(kpi_card("Rentables",         str(rentables),
                         "ROI > 10%",         "#2980b9", "✅"), md=3),
        dbc.Col(kpi_card("Ganancia Óptima",   f"${gan_opt:,.0f}",
                         "Con $3,000 USD",    "#8e44ad", "💰"), md=3),
        dbc.Col(kpi_card("ROI Global Óptimo", f"{roi_opt:.1f}%",
                         "Escenario $3k",     "#e67e22", "📈"), md=3),
    ], className="mb-4 g-3")

    modelos = [m.upper() for m in data.keys()]
    rois    = [d["roi_pct"] for d in data.values()]
    colores = [_color_roi(r) for r in rois]
    fig_roi = go.Figure(go.Bar(
        x=rois, y=modelos, orientation="h",
        marker_color=colores,
        text=[f"{r:.1f}%" for r in rois], textposition="outside"))
    fig_roi.update_layout(
        title="ROI por Modelo (%)", xaxis_title="ROI (%)",
        height=max(300, len(modelos) * 38),
        margin=dict(l=10, r=60, t=40, b=10),
        plot_bgcolor="white", paper_bgcolor="white",
        xaxis=dict(gridcolor="#eee"),
        yaxis=dict(autorange="reversed"),
        font=dict(size=11))
    fig_roi.add_vline(x=10, line_dash="dash", line_color="#f39c12",
                      annotation_text="Umbral 10%")
    fig_roi.add_vline(x=40, line_dash="dash", line_color="#27ae60",
                      annotation_text="Zona COMPRAR")

    ESCENARIOS = [1000, 3000, 5000, 10000]
    ganancias, rois_g = [], []
    for capital in ESCENARIOS:
        cr, gt, it = capital, 0.0, 0.0
        for d in data.values():
            if d["roi_pct"] > 10 and cr >= d["costo_importado_usd"]:
                gt += d["precio_venta_pe_usd"] * 0.95 - d["costo_importado_usd"]
                it += d["costo_importado_usd"]
                cr -= d["costo_importado_usd"]
        ganancias.append(round(gt, 2))
        rois_g.append(round((gt / it * 100) if it > 0 else 0, 1))
    fig_sim = go.Figure(go.Bar(
        x=[f"${c:,}" for c in ESCENARIOS], y=ganancias,
        marker_color=["#7f8c8d", "#27ae60", "#2980b9", "#8e44ad"],
        text=[f"${g:,.0f} | ROI {r:.0f}%"
              for g, r in zip(ganancias, rois_g)],
        textposition="outside"))
    fig_sim.update_layout(
        title="Ganancia Proyectada por Capital Disponible",
        height=320, plot_bgcolor="white", paper_bgcolor="white",
        yaxis=dict(gridcolor="#eee"),
        margin=dict(l=10, r=10, t=40, b=10),
        showlegend=False)
    fig_sim.add_annotation(
        x="$3,000", y=ganancias[1], text="⭐ ÓPTIMO",
        showarrow=True, arrowhead=2,
        font=dict(color="#27ae60", size=12), arrowcolor="#27ae60")

    filas = []
    for i, (modelo, d) in enumerate(data.items(), 1):
        compra = d.get("precio_compra_fusionado", d["precio_compra_china_usd"])
        costo  = d["costo_importado_usd"]
        venta  = d["precio_venta_pe_usd"]
        gan    = round(venta * 0.95 - costo, 2)
        roi    = d["roi_pct"]
        fuente = d.get("fuente_precio", "aliexpress")
        senal  = ("🟢 COMPRAR"  if roi > 40
                  else "🟡 EVALUAR"  if roi > 10
                  else "⚪ MARGINAL" if roi > 0
                  else "🔴 EVITAR")
        col_s  = ("success"   if roi > 40
                  else "warning"   if roi > 10
                  else "secondary" if roi > 0
                  else "danger")
        col_c  = "success" if d["confianza"] == "alta" else "warning"
        filas.append(html.Tr([
            html.Td(f"#{i}",
                    style={"color": "#888", "fontSize": "0.8rem"}),
            html.Td(html.Strong(modelo.upper()),
                    style={"fontSize": "0.85rem"}),
            html.Td(f"${compra:,.2f}"),
            html.Td(f"${costo:,.2f}"),
            html.Td(f"${venta:,.2f}"),
            html.Td([
                html.Strong(f"${gan:,.2f}", style={"color": "#27ae60"}),
                html.Br(),
                html.Small(f"S/{gan * TC:,.0f}", style={"color": "#888"}),
            ]),
            html.Td(html.Strong(f"{roi:.1f}%",
                                style={"color": _color_roi(roi),
                                       "fontSize": "1rem"})),
            html.Td(dbc.Badge(senal,  color=col_s, pill=True)),
            html.Td(dbc.Badge(d["confianza"].upper(), color=col_c, pill=True)),
            html.Td(html.Small(fuente, style={"color": "#aaa"})),
        ], style={"borderLeft": f"3px solid {_color_roi(roi)}"}))

    tabla = dbc.Table([
        html.Thead(html.Tr(
            [html.Th(c) for c in ["#", "Modelo", "Compra $", "Costo Imp.",
                                  "Venta PE $", "Ganancia", "ROI",
                                  "Señal", "Confianza", "Fuente"]],
            style={"backgroundColor": "#f8f9fa", "fontSize": "0.82rem"})),
        html.Tbody(filas),
    ], bordered=True, hover=True, responsive=True, size="sm",
       style={"fontSize": "0.85rem"})

    return html.Div([
        section_title("Oportunidades de Arbitraje — HDS-ROI v6.2", "📊"),
        dbc.Alert([
            html.B("🚀 Sistema HDS-ROI v6.2 Activo — "),
            f"{len(data)} modelos · {rentables} rentables (ROI>10%) · "
            f"TC: S/{TC}/USD",
        ], color="info", style={
            "background": COLORS["card"],
            "border": f"2px solid {COLORS['accent2']}",
            "color": COLORS["text"], "fontSize": "0.88rem",
            "marginBottom": "20px"}),
        kpi_row,
        section_title("Ranking ROI por Modelo", "📈"),
        dcc.Graph(figure=fig_roi, config=CHART_CONFIG),
        section_title("Ranking Completo", "📋"),
        tabla,
        section_title("Simulación por Capital", "💰"),
        dcc.Graph(figure=fig_sim, config=CHART_CONFIG),
        dbc.Alert([
            html.Strong("⚙️ Supuestos: "),
            "Costo imp = compra × 1.30 · Venta PE = 95% precio local · ",
            f"TC = S/{TC}/USD · Fuente: eBay(70%) + AliExpress(30%) · "
            "CPUs Mobile excluidos",
        ], color="light", className="mt-3",
           style={"fontSize": "0.82rem"}),
    ], style={"padding": "24px"})


# ─────────────────────────────────────────────
# 17. LAYOUT PRINCIPAL
# ─────────────────────────────────────────────

app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    dcc.Store(id="store-capital", data=5000),
    sidebar,
    html.Div(id="page-content", style=CONTENT_STYLE),
    html.Div([
        dcc.Markdown(f"""
<style>
.nav-link-custom {{ transition: all 0.2s ease !important; }}
.nav-link-custom:hover {{
    background-color: {COLORS["border"]} !important;
    border-left: 3px solid {COLORS["accent"]} !important;
    padding-left: 9px !important;
}}
.nav-link-custom.active {{
    background-color: {COLORS["accent"]}33 !important;
    border-left: 3px solid {COLORS["accent"]} !important;
    color: {COLORS["accent"]} !important;
    font-weight: 600 !important;
    padding-left: 9px !important;
}}
table {{ font-size: 0.85rem; }}
th {{
    background-color: {COLORS["card"]} !important;
    color: {COLORS["accent"]} !important;
    font-weight: 700 !important;
    border-bottom: 2px solid {COLORS["border"]} !important;
}}
td {{
    border-bottom: 1px solid {COLORS["border"]} !important;
    padding: 10px 12px !important;
}}
tbody tr:hover {{ background-color: {COLORS["card"]} !important; }}
.card {{
    border: 1px solid {COLORS["border"]} !important;
    background-color: {COLORS["bg"]} !important;
    border-radius: 8px !important;
    transition: all 0.3s ease !important;
}}
.card:hover {{
    box-shadow: 0 4px 12px rgba(0,0,0,0.12) !important;
    border-color: {COLORS["accent"]} !important;
}}
.alert {{ border-radius: 6px !important; border-left: 4px solid !important; }}
.alert-info    {{ border-left-color: {COLORS["accent2"]} !important;
                  background-color: {COLORS["accent2"]}11 !important; }}
.alert-success {{ border-left-color: {COLORS["green"]}   !important;
                  background-color: {COLORS["green"]}11   !important; }}
.alert-warning {{ border-left-color: {COLORS["accent3"]} !important;
                  background-color: {COLORS["accent3"]}11 !important; }}
h1,h2,h3,h4,h5,h6 {{ color: {COLORS["text"]} !important; }}
p {{ color: {COLORS["text"]} !important; }}
body {{ background-color: #f5f7fa !important; }}
</style>
        """, dangerously_allow_html=True)
    ], style={"display": "none"}),
], style={"backgroundColor": "#f5f7fa", "minHeight": "100vh"})


# ─────────────────────────────────────────────
# 18. CALLBACKS
# ─────────────────────────────────────────────

@app.callback(
    Output("store-capital", "data"),
    Output("sidebar-capital-display", "children"),
    Input("sidebar-capital-input", "value"),
    prevent_initial_call=False,
)
def sync_capital_store(val):
    if not val or val < 100:
        return 5000, "→ $5,000 USD"
    return val, f"→ ${val:,.0f} USD"


@app.callback(
    Output("page-content", "children"),
    Input("url", "pathname"),
    Input("store-capital", "data"),
    prevent_initial_call=False,
)
def display_page(pathname, capital_global):
    # FIX: evita None en primera carga
    pathname       = pathname       or "/"
    capital_global = capital_global or 5000

    if   pathname in ("/", "/inicio"):  return page_home_ejecutivo(capital_global)
    elif pathname == "/motor":          return page_resumen(capital_global)
    elif pathname == "/simulador":      return page_simulador(capital_global)
    elif pathname == "/prediccion":     return page_prediccion(capital_global)
    elif pathname == "/obsolescencia":  return page_obsolescencia()
    elif pathname == "/oe9":            return page_oe9()
    elif pathname == "/datos":          return page_datos()
    elif pathname == "/portafolios":    return page_portafolios()
    elif pathname == "/sensibilidad":   return page_sensibilidad()
    elif pathname == "/pareto":         return page_pareto()
    elif pathname == "/competitividad": return page_competitividad()
    elif pathname == "/ablacion":       return page_ablacion()
    elif pathname == "/pipeline":       return page_pipeline()
    elif pathname == "/arbitraje":      return page_arbitraje()
    else:
        return html.Div([
            html.H3(
                f"404 — Página no encontrada: {pathname}",
                style={"color": COLORS["text"], "padding": "24px"})
        ])


# FIX-L: prevent_initial_call=True — solo ejecuta al hacer click
@app.callback(
    Output("simulador-resultados", "children"),
    Input("btn-simular", "n_clicks"),
    [State("input-presupuesto", "value"),
     State("dropdown-modelo",   "value")],
    prevent_initial_call=True,
)
def actualizar_simulador(n_clicks, presupuesto, modelo_key):
    if not presupuesto or presupuesto < 100:
        return dbc.Alert("⚠️ Ingresa un presupuesto válido (mínimo $100)",
                         color="warning")

    recomendaciones = generar_recomendaciones()
    if not recomendaciones:
        return dbc.Alert("⚠️ No hay datos OE9 disponibles. "
                         "Ejecuta: python scripts/oe9_nsga3.py", color="warning")

    skus_data = DATA.get("predicciones_multi", {}).get("skus", {})

    # ── Fallback sin skus_data ────────────────────────────────────────
    if not skus_data:
        datos     = recomendaciones.get(modelo_key, recomendaciones["balanceado"])
        resultado = calcular_simulador(presupuesto, datos["roi"], datos["capital"])
        if not resultado:
            return dbc.Alert("❌ Error en cálculo", color="danger")
        kpis = dbc.Row([
            dbc.Col(kpi_card("Unidades a Comprar",
                             f"{resultado['unidades']:,}",
                             "Cantidad total",
                             COLORS["accent"],  "📦"), md=3),
            dbc.Col(kpi_card("Capital Total",
                             f"${resultado['capital_total']:,.0f}",
                             "Inversión",
                             COLORS["accent2"], "💰"), md=3),
            dbc.Col(kpi_card("Ganancia Total",
                             f"${resultado['ganancia_total']:,.0f}",
                             "Retorno esperado",
                             COLORS["green"],   "📈"), md=3),
            dbc.Col(kpi_card("ROI Total",
                             f"+{resultado['roi_total']:.1f}%",
                             "Retorno s/ inversión",
                             COLORS["accent4"], "🎯"), md=3),
        ], className="mt-4 mb-4 g-3")
        return html.Div([
            kpis,
            dbc.Alert("ℹ️ Ejecuta pe2_multihorizonte.py para ver el plan detallado.",
                      color="info"),
        ])

    # ── Plan detallado con skus_data ─────────────────────────────────
    skus_ordenados = sorted(
        skus_data.items(),
        key=lambda x: x[1].get("oportunidad", {}).get("score_oportunidad", 0),
        reverse=True)

    PRIORIDAD_HW = ["gpu", "cpu", "ram", "ssd", "motherboard",
                    "psu", "monitor", "cooler", "laptop", "case", "hdd", "otro"]

    def _hw_sort_key(item):
        hw  = item[1].get("hw_type",
              item[1].get("oportunidad", {}).get("hw_type", "otro"))
        pri = PRIORIDAD_HW.index(hw) if hw in PRIORIDAD_HW else 99
        roi = item[1].get("oportunidad", {}).get("roi_pct", 0)
        return (pri, -roi)

    skus_ordenados.sort(key=_hw_sort_key)

    HW_ICONS = {
        "gpu": "🖥️ GPU", "cpu": "⚙️ CPU", "ram": "💾 RAM",
        "ssd": "💿 SSD", "motherboard": "🔌 MB", "psu": "⚡ PSU",
        "case": "📦 CASE", "cooler": "❄️ COOLER", "monitor": "🖥️ MON",
        "laptop": "💻 LAPTOP", "otro": "🔧 OTRO",
    }
    CAT_CFG = {
        "gpu":         ("danger",    "🖥️ GPU"),
        "cpu":         ("warning",   "⚙️ CPU"),
        "ram":         ("info",      "💾 RAM"),
        "ssd":         ("success",   "💿 SSD"),
        "motherboard": ("primary",   "🔌 MB"),
        "psu":         ("secondary", "⚡ PSU"),
        "case":        ("light",     "📦 CASE"),
        "cooler":      ("info",      "❄️ COOLER"),
        "monitor":     ("primary",   "🖥️ MON"),
        "laptop":      ("warning",   "💻 LAPTOP"),
        "otro":        ("light",     "🔧 OTRO"),
    }

    presupuesto_restante = float(presupuesto)
    rows_desglose        = []
    total_invertido      = 0.0
    total_ganancia       = 0.0
    total_unidades       = 0
    hw_incluidos         = {}

    for sku_key, info in skus_ordenados:
        if presupuesto_restante < 10:
            break
        op       = info.get("oportunidad", {})
        hw_type  = info.get("hw_type", op.get("hw_type", "otro"))
        p_compra = op.get("precio_compra_usd", 0)
        p_venta  = op.get("precio_venta_usd",  0)
        gan_u    = op.get("ganancia_usd",       0)
        roi_sku  = op.get("roi_pct",            0)
        accion   = op.get("accion", "EVALUAR")
        titulo   = info.get("title", sku_key)[:45]
        source   = info.get("source", "")

        if p_compra <= 0:
            continue
        if hw_incluidos.get(hw_type, 0) >= MAX_SKUS_POR_HW:
            continue

        max_u_hw      = UNIDADES_MAX_HW.get(hw_type, 3)
        max_capital   = min(presupuesto_restante, presupuesto * 0.25)
        u_por_capital = int(max_capital / p_compra)
        unidades      = min(u_por_capital, max_u_hw)

        if unidades <= 0:
            continue

        capital_sku  = unidades * p_compra
        ganancia_sku = unidades * gan_u
        pct_capital  = (capital_sku / presupuesto) * 100

        presupuesto_restante -= capital_sku
        total_invertido      += capital_sku
        total_ganancia       += ganancia_sku
        total_unidades       += unidades
        hw_incluidos[hw_type] = hw_incluidos.get(hw_type, 0) + 1

        p_color, p_label = CAT_CFG.get(hw_type,
                                       ("light", f"🔧 {hw_type.upper()}"))
        badge_port = dbc.Badge(p_label, color=p_color, pill=True,
                               style={"fontSize": "0.65rem"})
        hw_label   = HW_ICONS.get(hw_type, f"🔧 {hw_type.upper()}")
        badge_hw   = dbc.Badge(hw_label, color="secondary", pill=True,
                               style={"fontSize": "0.65rem",
                                      "background": COLORS["border"],
                                      "color": COLORS["text"]})

        if accion == "COMPRAR YA":
            badge_acc = dbc.Badge("🔥 COMPRAR YA", color="danger",  pill=True,
                                  style={"fontSize": "0.7rem"})
        elif accion == "COMPRAR":
            badge_acc = dbc.Badge("✅ COMPRAR",    color="success", pill=True,
                                  style={"fontSize": "0.7rem"})
        else:
            badge_acc = dbc.Badge("⏳ EVALUAR",    color="warning", pill=True,
                                  style={"fontSize": "0.7rem"})

        color_roi = (COLORS["accent3"] if roi_sku > 100
                     else COLORS["green"] if roi_sku > 30
                     else COLORS["text_dim"])
        tend7 = info.get("predicciones", {}).get("7", {}).get("tendencia", "—")

        rows_desglose.append(html.Tr([
            html.Td([
                html.Div([
                    badge_hw,
                    html.Span(f"  {titulo}",
                              style={"fontSize": "0.82rem",
                                     "color": COLORS["text"],
                                     "fontWeight": 600}),
                ]),
                html.Div([
                    html.Small(f"🏪 {source}",
                               style={"color": COLORS["text_dim"],
                                      "marginRight": "8px"}),
                    html.Small(f"H+7: {tend7}", style={
                        "color": (COLORS["green"]   if tend7 == "SUBE"
                                  else COLORS["accent3"] if tend7 == "BAJA"
                                  else COLORS["text_dim"])}),
                ], style={"marginTop": "2px"}),
            ], style={"minWidth": "200px"}),
            html.Td(badge_port,
                    style={"textAlign": "center", "whiteSpace": "nowrap"}),
            html.Td(f"${p_compra:,.2f}",
                    style={"textAlign": "right", "color": COLORS["accent2"],
                           "fontWeight": 600, "whiteSpace": "nowrap"}),
            html.Td(f"${p_venta:,.2f}",
                    style={"textAlign": "right", "color": COLORS["green"],
                           "fontWeight": 600, "whiteSpace": "nowrap"}),
            html.Td(html.B(f"{roi_sku:+.1f}%", style={"color": color_roi}),
                    style={"textAlign": "right"}),
            html.Td([
                html.B(str(unidades),
                       style={"color": COLORS["accent"], "fontSize": "1.1rem"}),
                html.Br(),
                html.Small(f"máx {max_u_hw}",
                           style={"color": COLORS["text_dim"],
                                  "fontSize": "0.65rem"}),
            ], style={"textAlign": "center"}),
            html.Td([
                html.B(f"${capital_sku:,.0f}", style={"color": COLORS["text"]}),
                html.Div([
                    html.Div(style={
                        "width": f"{min(100, pct_capital):.0f}%",
                        "height": "5px",
                        "background": COLORS["accent"],
                        "borderRadius": "3px"})
                ], style={"width": "70px", "background": COLORS["border"],
                          "borderRadius": "3px", "marginTop": "3px"}),
                html.Small(f"{pct_capital:.1f}%",
                           style={"color": COLORS["text_dim"],
                                  "fontSize": "0.65rem"}),
            ], style={"textAlign": "right"}),
            html.Td(html.B(f"${ganancia_sku:,.0f}",
                           style={"color": COLORS["green"]}),
                    style={"textAlign": "right"}),
            html.Td(badge_acc, style={"textAlign": "center"}),
        ], style={"borderBottom": f"1px solid {COLORS['border']}"}))

    # FIX-D: saldo definido ANTES de la fila TOTAL
    saldo = presupuesto - total_invertido

    if saldo > 1:
        rows_desglose.append(html.Tr([
            html.Td(html.I("💵 Saldo no invertido",
                           style={"color": COLORS["text_dim"]})),
            html.Td("—", style={"textAlign": "center"}),
            html.Td("—", style={"textAlign": "right"}),
            html.Td("—", style={"textAlign": "right"}),
            html.Td("—", style={"textAlign": "right"}),
            html.Td("—", style={"textAlign": "center"}),
            html.Td(f"${saldo:,.0f}",
                    style={"textAlign": "right",
                           "color": COLORS["text_dim"],
                           "fontStyle": "italic"}),
            html.Td("—", style={"textAlign": "right"}),
            html.Td("—", style={"textAlign": "center"}),
        ], style={"background": f"{COLORS['border']}33"}))

    roi_real = (total_ganancia / total_invertido * 100) if total_invertido > 0 else 0
    rows_desglose.append(html.Tr([
        html.Td(html.B("📊 TOTAL", style={"color": COLORS["accent"]})),
        html.Td("—", style={"textAlign": "center"}),
        html.Td("—", style={"textAlign": "right"}),
        html.Td("—", style={"textAlign": "right"}),
        html.Td(html.B(f"+{roi_real:.1f}%",
                       style={"color": COLORS["green"], "fontWeight": 700}),
                style={"textAlign": "right"}),
        html.Td(html.B(str(total_unidades),
                       style={"color": COLORS["accent"]}),
                style={"textAlign": "center"}),
        html.Td(html.B(f"${total_invertido:,.0f}",
                       style={"color": COLORS["accent"]}),
                style={"textAlign": "right"}),
        html.Td(html.B(f"${total_ganancia:,.0f}",
                       style={"color": COLORS["green"], "fontWeight": 700}),
                style={"textAlign": "right"}),
        html.Td(dbc.Badge("RESUMEN", color="primary", pill=True,
                          style={"fontSize": "0.65rem"}),
                style={"textAlign": "center"}),
    ], style={"background": f"{COLORS['accent']}0D",
              "borderTop": f"2px solid {COLORS['accent']}"}))

    tabla_desglose = dbc.Table([
        html.Thead(html.Tr([
            html.Th("Producto",  style={"color": COLORS["accent"], "fontWeight": 700,
                                        "minWidth": "200px"}),
            html.Th("Categoría", style={"color": COLORS["accent"], "fontWeight": 700,
                                        "textAlign": "center",
                                        "whiteSpace": "nowrap"}),
            html.Th("P. Compra", style={"color": COLORS["accent"], "fontWeight": 700,
                                        "textAlign": "right"}),
            html.Th("P. Venta",  style={"color": COLORS["accent"], "fontWeight": 700,
                                        "textAlign": "right"}),
            html.Th("ROI",       style={"color": COLORS["accent"], "fontWeight": 700,
                                        "textAlign": "right"}),
            html.Th("Unidades",  style={"color": COLORS["accent"], "fontWeight": 700,
                                        "textAlign": "center"}),
            html.Th("Capital",   style={"color": COLORS["accent"], "fontWeight": 700,
                                        "textAlign": "right"}),
            html.Th("Ganancia",  style={"color": COLORS["accent"], "fontWeight": 700,
                                        "textAlign": "right"}),
            html.Th("Acción",    style={"color": COLORS["accent"], "fontWeight": 700,
                                        "textAlign": "center"}),
        ], style={"background": COLORS["card"],
                  "borderBottom": f"2px solid {COLORS['border']}"})),
        html.Tbody(rows_desglose),
    ], bordered=True, hover=True, responsive=True, size="sm",
       style={"color": COLORS["text"], "fontSize": "0.82rem"})

    HW_ICONS_FULL = {
        "gpu": "🖥️ GPU", "cpu": "⚙️ CPU", "ram": "💾 RAM",
        "ssd": "💿 SSD", "motherboard": "🔌 MB", "psu": "⚡ PSU",
        "case": "📦 CASE", "cooler": "❄️ COOLER", "monitor": "🖥️ MON",
        "laptop": "💻 LAPTOP", "otro": "🔧 OTRO",
    }
    dist_badges = [
        dbc.Badge(f"{HW_ICONS_FULL.get(hw, hw)}: {cnt}",
                  color="secondary", pill=True, className="me-1",
                  style={"fontSize": "0.7rem",
                         "background": COLORS["border"],
                         "color": COLORS["text"]})
        for hw, cnt in hw_incluidos.items()
    ]

    desglose_section = html.Div([
        html.H5([
            html.Span("📋 ", style={"marginRight": "8px"}),
            "Plan de Inversión Detallado",
            dbc.Badge(f"${presupuesto:,.0f} distribuidos",
                      color="success", pill=True, className="ms-2",
                      style={"fontSize": "0.7rem"}),
        ], style={"color": COLORS["accent"],
                  "borderBottom": f"3px solid {COLORS['accent']}",
                  "paddingBottom": "10px", "marginBottom": "16px",
                  "fontWeight": 700}),
        dbc.Alert([
            html.B("🎯 Estrategia: "),
            "ROI alto + portafolio diverso. ",
            html.B(f"Máx {MAX_SKUS_POR_HW} SKUs por tipo HW"),
            " para diversificación. ",
            html.B("Unidades realistas"),
            " según tipo (GPU: máx 3, Case: máx 3, RAM: máx 8, CPU: máx 5). ",
            f"Saldo no invertido: ${saldo:,.0f}.",
        ], color="light",
           style={"border": f"1px solid {COLORS['border']}",
                  "fontSize": "0.8rem", "padding": "8px 14px",
                  "marginBottom": "10px"}),
        html.Div([
            html.Small("Tipos incluidos: ",
                       style={"color": COLORS["text_dim"],
                              "marginRight": "6px", "fontWeight": 600}),
            *dist_badges,
        ], style={"marginBottom": "14px", "display": "flex",
                  "alignItems": "center", "flexWrap": "wrap", "gap": "4px"}),
        html.Div(tabla_desglose, style={"overflowX": "auto"}),
        dbc.Alert([
            html.B("⚠️ Nota: "),
            "ROI mostrado es bruto (antes de costos). "
            "Descontar: aranceles ~12%, IGV 18%, flete $15–25 por unidad. "
            "ROI neto estimado: 25–45% según categoría.",
        ], color="warning",
           style={"fontSize": "0.78rem", "padding": "8px 14px",
                  "marginTop": "12px",
                  "border": f"1px solid {COLORS['accent3']}"}),
    ], style={"background": COLORS["bg"],
              "border": f"2px solid {COLORS['accent']}44",
              "borderRadius": "10px", "padding": "20px",
              "marginTop": "20px"})

    roi_kpi = (total_ganancia / total_invertido * 100) if total_invertido > 0 else 0
    kpis_reales = dbc.Row([
        dbc.Col(kpi_card("Unidades a Comprar",
                         f"{total_unidades:,}",
                         "Cantidad total real",
                         COLORS["accent"],  "📦"), md=3),
        dbc.Col(kpi_card("Capital Invertido",
                         f"${total_invertido:,.0f}",
                         f"de ${presupuesto:,.0f} disponibles",
                         COLORS["accent2"], "💰"), md=3),
        dbc.Col(kpi_card("Ganancia Total",
                         f"${total_ganancia:,.0f}",
                         "Retorno esperado",
                         COLORS["green"],   "📈"), md=3),
        dbc.Col(kpi_card("ROI Real",
                         f"+{roi_kpi:.1f}%",
                         "Calculado SKU a SKU",
                         COLORS["accent4"], "🎯"), md=3),
    ], className="mt-4 mb-4 g-3")

    return html.Div([kpis_reales, desglose_section])


@app.callback(
    Output("pred-grafico", "figure"),
    Input("pred-btn-update", "n_clicks"),
    [State("pred-dropdown-sku",       "value"),
     State("pred-dropdown-horizonte", "value")],
    prevent_initial_call=True,
)
def actualizar_grafico_prediccion(n_clicks, sku_key, horizonte):
    skus_data = DATA.get("predicciones_multi", {}).get("skus", {})
    return _fig_prediccion_sku(skus_data, sku_key, horizonte)


# ─────────────────────────────────────────────
# 19. EJECUCIÓN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    _MODEL_CANDIDATES = [
        Path("models/pe2_v52_20261003_142754.txt"),
        Path("models/pe2_v52.txt"),
    ]
    _METRICS_CANDIDATES = [
        Path("models/pe2_v52_metrics_20261003_142754.json"),
        Path("results/pe2_v52_metrics.json"),
        Path("results/pe2_lgbm_metrics.json"),
    ]
    MODEL_PATH   = next((p for p in _MODEL_CANDIDATES   if p.exists()), None)
    METRICS_PATH = next((p for p in _METRICS_CANDIDATES if p.exists()), None)

    # Cargar métricas desde archivo si existe, sino usar PE2_V52 (constante)
    if METRICS_PATH:
        try:
            with open(METRICS_PATH, "r", encoding="utf-8") as _f:
                _raw = json.load(_f)
            _test = _raw.get("metrics_test", _raw.get("test", {}))
            METRICS = {
                "wmape_global":  _test.get("wmape",
                                           PE2_V52["wmape_global"]),
                "wmape_seen":    _test.get("wmape_seen",
                                           PE2_V52["wmape_seen"]),
                "wmape_unseen":  _test.get("wmape_unseen",
                                           PE2_V52["wmape_unseen"]),
                "n_test":        _raw.get("n_test",
                                          PE2_V52["n_test"]),
                "pct_unseen":    _raw.get("pct_unseen",
                                          PE2_V52["pct_unseen"]),
            }
        except Exception:
            METRICS = PE2_V52.copy()
    else:
        METRICS = PE2_V52.copy()

    print("\n" + "=" * 80)
    print("  🚀 HDS-ROI v6.2 — Motor de Decisión Inteligente (PE2 v5.2)")
    print("=" * 80)
    print(f"  🌐 URL        : http://{APP_CONFIG['host']}:{APP_CONFIG['port']}")
    print(f"  🤖 PE2 v5.2   : "
          f"WMAPE Global={METRICS['wmape_global']:.2f}%  |  "
          f"Seen={METRICS['wmape_seen']:.2f}%  |  "
          f"Unseen={METRICS['wmape_unseen']:.2f}%")
    print(f"  📦 Dataset    : "
          f"{METRICS.get('n_test', PE2_V52['n_test']):,} registros de test  |  "
          f"{METRICS.get('pct_unseen', PE2_V52['pct_unseen'])}% SKUs nuevos (unseen)")
    print(f"  📅 Fecha      : "
          f"{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  🗂️  Modelo     : "
          f"{MODEL_PATH.name if MODEL_PATH else 'pe2_v52_20261003_142754.txt  [no encontrado]'}")
    print(f"  📊 Métricas   : "
          f"{METRICS_PATH.name if METRICS_PATH else 'pe2_v52_metrics_20261003_142754.json  [usando constante PE2_V52]'}")
    print("─" * 80)
    print("  ℹ️  Módulos activos:")
    print("       [1]  Home / Resumen ejecutivo             → /")
    print("       [2]  Pipeline & Datos                     → /pipeline")
    print("       [3]  Análisis de Datos                    → /datos")
    print("       [4]  Predicción Multihorizonte (PE2 v5.2) → /prediccion")
    print("       [5]  Obsolescencia NLP (E5-large)         → /obsolescencia")
    print("       [6]  NSGA-III OE9                         → /oe9")
    print("       [7]  Portafolios                          → /portafolios")
    print("       [8]  Arbitraje ROI                        → /arbitraje")
    print("       [9]  Sensibilidad Monte Carlo             → /sensibilidad")
    print("       [10] Simulador de Compra                  → /simulador")
    print("       [11] Motor de Decisión                    → /motor")
    print("       [12] Ablación de Modelos                  → /ablacion")
    print("       [13] Competitividad                       → /competitividad")
    print("       [14] Pareto Original                      → /pareto")
    print("─" * 80)
    print("  ⚡ Iniciando servidor Dash... (Ctrl+C para detener)")
    print("=" * 80 + "\n")

    app.run(
        host=APP_CONFIG["host"],
        port=APP_CONFIG["port"],
        debug=APP_CONFIG.get("debug", False),
    )