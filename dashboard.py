# =============================================================================
# HDS-ROI v4.0 — Dashboard de Optimización de Portafolio Dropshipping (Hardware PC)
# Autor: Proyecto de Tesis
# Fecha: 2026-07-30
# Stack: Dash 2.x · Plotly · Pandas · NumPy
# Ejecución: python dashboard.py  →  http://127.0.0.1:8050
# =============================================================================

import os
import json
import warnings
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

import dash
from dash import dcc, html, Input, Output, State, callback_context
import dash_bootstrap_components as dbc

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────
# 0. CONFIGURACIÓN GLOBAL
# ─────────────────────────────────────────────
COLORS = {
    "bg":        "#0d1117",
    "card":      "#161b22",
    "border":    "#30363d",
    "accent":    "#00d4aa",
    "accent2":   "#58a6ff",
    "accent3":   "#f78166",
    "accent4":   "#e3b341",
    "text":      "#c9d1d9",
    "text_dim":  "#8b949e",
    "green":     "#3fb950",
    "red":       "#f85149",
    "purple":    "#bc8cff",
}

PLOTLY_TEMPLATE = dict(
    layout=dict(
        paper_bgcolor=COLORS["bg"],
        plot_bgcolor=COLORS["card"],
        font=dict(color=COLORS["text"], family="Inter, sans-serif", size=12),
        xaxis=dict(gridcolor=COLORS["border"], zerolinecolor=COLORS["border"]),
        yaxis=dict(gridcolor=COLORS["border"], zerolinecolor=COLORS["border"]),
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=COLORS["border"]),
        margin=dict(l=40, r=20, t=40, b=40),
    )
)

# ─────────────────────────────────────────────
# 1. CARGA DE DATOS (con fallback sintético)
# ─────────────────────────────────────────────

def load_pareto():
    """Carga frente de Pareto NSGA-III o genera datos sintéticos."""
    path = "results/pareto_front.csv"
    if os.path.exists(path):
        return pd.read_csv(path)
    np.random.seed(42)
    n = 75
    roi    = np.random.uniform(0.30, 1.20, n)
    riesgo = np.random.uniform(2.0,  8.0,  n)
    div    = np.random.uniform(0.40, 0.95, n)
    hhi    = np.random.uniform(0.10, 0.60, n)
    inv    = np.random.uniform(2000, 8000, n)
    return pd.DataFrame({
        "roi": roi, "riesgo": riesgo,
        "diversificacion": div, "hhi": hhi,
        "inversion_usd": inv,
        "perfil": np.random.choice(["Conservador","Moderado","Agresivo"], n)
    })

def load_portafolios():
    """Carga portafolios seleccionados o genera perfiles representativos."""
    path = "results/portafolios_seleccionados.csv"
    if os.path.exists(path):
        return pd.read_csv(path)
    data = {
        "perfil":       ["Conservador", "Moderado",  "Agresivo"],
        "roi_pct":      [28.5,           69.0,        112.3],
        "riesgo":       [2.8,            5.0,          7.6],
        "inversion":    [2100,           4737,         7800],
        "n_skus":       [4,              7,            11],
        "hhi":          [0.18,           0.31,         0.48],
        "diversif":     [0.88,           0.72,         0.55],
        "margen_bruto": [0.32,           0.41,         0.53],
    }
    return pd.DataFrame(data)

def load_skus():
    """Carga SKUs del portafolio equilibrado o genera datos representativos."""
    path = "results/skus_portafolio.csv"
    if os.path.exists(path):
        return pd.read_csv(path)
    data = {
        "sku": [
            "GPU RTX 4060", "CPU Ryzen 5 7600", "RAM DDR5 32GB",
            "SSD NVMe 1TB", "Motherboard B650", "PSU 750W 80+Gold",
            "Case ATX Mid-Tower"
        ],
        "categoria":    ["GPU","CPU","RAM","Almacenamiento","Motherboard","PSU","Case"],
        "precio_usd":   [320, 210, 95, 75, 160, 85, 70],
        "margen_pct":   [0.38, 0.42, 0.35, 0.40, 0.45, 0.30, 0.28],
        "score_demanda":[0.87, 0.91, 0.78, 0.82, 0.74, 0.65, 0.60],
        "factor_venta": [0.72, 0.80, 0.65, 0.70, 0.60, 0.55, 0.50],
        "roi_sku":      [0.82, 0.95, 0.68, 0.74, 0.71, 0.52, 0.45],
        "peso_portafolio":[0.22,0.19,0.14,0.13,0.13,0.10,0.09],
    }
    return pd.DataFrame(data)

def load_montecarlo():
    """Carga resultados de Monte Carlo o genera simulación."""
    path = "results/montecarlo.csv"
    if os.path.exists(path):
        return pd.read_csv(path)
    np.random.seed(7)
    n = 2000
    factor_venta  = np.random.normal(0.72, 0.12, n)
    margen        = np.random.normal(0.41, 0.06, n)
    precio_compra = np.random.normal(1.00, 0.05, n)
    roi_sim = (factor_venta * margen) / precio_compra
    return pd.DataFrame({
        "iteracion":    np.arange(n),
        "factor_venta": factor_venta,
        "margen":       margen,
        "precio_compra":precio_compra,
        "roi_simulado": roi_sim,
    })

def load_precios():
    """Carga datos de competitividad de precios."""
    sources = {
        "data/precios_amazon.csv":   "Amazon",
        "data/precios_ebay.csv":     "eBay",
        "data/precios_aliexpress.csv":"AliExpress",
        "data/precios_coolbox.csv":  "Coolbox",
        "data/precios_falabella.csv":"Falabella",
        "data/precios_hiraoka.csv":  "Hiraoka",
    }
    frames = []
    for fpath, fuente in sources.items():
        if os.path.exists(fpath):
            df = pd.read_csv(fpath)
            df["fuente"] = fuente
            frames.append(df)
    if frames:
        return pd.concat(frames, ignore_index=True)
    # Sintético
    np.random.seed(99)
    productos = ["GPU RTX 4060","CPU Ryzen 5 7600","RAM DDR5 32GB",
                 "SSD NVMe 1TB","Motherboard B650"]
    fuentes   = ["Amazon","eBay","AliExpress","Coolbox","Falabella","Hiraoka"]
    rows = []
    base = {"GPU RTX 4060":320,"CPU Ryzen 5 7600":210,"RAM DDR5 32GB":95,
            "SSD NVMe 1TB":75,"Motherboard B650":160}
    for p in productos:
        for f in fuentes:
            factor = np.random.uniform(0.90, 1.25)
            rows.append({
                "producto": p, "fuente": f,
                "precio_usd": round(base[p] * factor, 2),
                "disponible": np.random.choice([True, False], p=[0.8, 0.2]),
                "descuento_pct": round(np.random.uniform(0, 0.15), 3),
            })
    return pd.DataFrame(rows)

def load_ablacion():
    """Carga métricas de ablación de modelos."""
    path = "results/ablacion_modelos.csv"
    if os.path.exists(path):
        return pd.read_csv(path)
    data = {
        "modelo":   ["Baseline (Media)","LightGBM","XGBoost","TFT","N-BEATS"],
        "mae":      [0.312, 0.198, 0.204, 0.171, 0.163],
        "rmse":     [0.421, 0.267, 0.275, 0.231, 0.219],
        "mape_pct": [31.2,  19.8,  20.4,  17.1,  16.3],
        "smape_pct":[28.5,  18.2,  18.9,  15.8,  15.1],
        "tiempo_s": [0.1,   2.3,   2.8,   45.2,  38.7],
        "params_k": [0,     12,    15,    180,   95],
    }
    return pd.DataFrame(data)

# Cargar todos los datasets al inicio
df_pareto    = load_pareto()
df_portf     = load_portafolios()
df_skus      = load_skus()
df_mc        = load_montecarlo()
df_precios   = load_precios()
df_ablacion  = load_ablacion()

# ─────────────────────────────────────────────
# 2. COMPONENTES UI REUTILIZABLES
# ─────────────────────────────────────────────

def kpi_card(title, value, subtitle="", color=None, icon="📊"):
    color = color or COLORS["accent"]
    return dbc.Card([
        dbc.CardBody([
            html.Div([
                html.Span(icon, style={"fontSize":"1.6rem"}),
                html.Div([
                    html.P(title, className="mb-0",
                           style={"color": COLORS["text_dim"], "fontSize":"0.75rem",
                                  "textTransform":"uppercase", "letterSpacing":"0.08em"}),
                    html.H4(value, className="mb-0 fw-bold",
                            style={"color": color, "fontSize":"1.5rem"}),
                    html.P(subtitle, className="mb-0",
                           style={"color": COLORS["text_dim"], "fontSize":"0.72rem"}),
                ], style={"marginLeft":"10px"})
            ], style={"display":"flex","alignItems":"center"})
        ])
    ], style={"background": COLORS["card"], "border": f"1px solid {COLORS['border']}",
              "borderRadius":"10px", "height":"100%"})

def section_title(text, icon=""):
    return html.H5(
        [html.Span(icon + " ", style={"marginRight":"6px"}), text],
        style={"color": COLORS["accent"], "borderBottom": f"1px solid {COLORS['border']}",
               "paddingBottom":"8px", "marginBottom":"16px", "fontWeight":"600"}
    )

def nav_link(label, href, icon=""):
    return dbc.NavLink(
        [html.Span(icon, style={"marginRight":"8px"}), label],
        href=href, active="exact",
        style={"color": COLORS["text"], "borderRadius":"6px",
               "marginBottom":"4px", "fontSize":"0.88rem"},
    )

# ─────────────────────────────────────────────
# 3. SIDEBAR
# ─────────────────────────────────────────────

sidebar = html.Div([
    html.Div([
        html.H4("HDS-ROI", style={"color": COLORS["accent"], "fontWeight":"800",
                                   "letterSpacing":"0.05em", "marginBottom":"2px"}),
        html.P("v4.0 · Dropshipping Hardware",
               style={"color": COLORS["text_dim"], "fontSize":"0.72rem", "marginBottom":"0"}),
    ], style={"padding":"20px 16px 12px", "borderBottom": f"1px solid {COLORS['border']}"}),

    dbc.Nav([
        nav_link("Resumen Ejecutivo",  "/",             "🏠"),
        nav_link("Portafolios",        "/portafolios",  "📦"),
        nav_link("Sensibilidad",       "/sensibilidad", "🎲"),
        nav_link("Pareto NSGA-III",    "/pareto",       "🧬"),
        nav_link("Competitividad",     "/competitividad","💹"),
        nav_link("Ablación Modelos",   "/ablacion",     "🔬"),
        nav_link("Pipeline & Datos",   "/pipeline",     "🔧"),
    ], vertical=True, pills=True,
       style={"padding":"12px 8px", "flexDirection":"column"}),

    html.Div([
        html.P("📅 30 Jul 2026",
               style={"color": COLORS["text_dim"], "fontSize":"0.70rem", "marginBottom":"2px"}),
        html.P("🟢 Sistema Operativo",
               style={"color": COLORS["green"], "fontSize":"0.70rem"}),
    ], style={"padding":"12px 16px", "borderTop": f"1px solid {COLORS['border']}",
              "position":"absolute", "bottom":"0", "width":"100%"}),
], style={
    "width": "220px", "minHeight": "100vh", "background": COLORS["card"],
    "borderRight": f"1px solid {COLORS['border']}", "position": "fixed",
    "top": "0", "left": "0", "overflowY": "auto", "zIndex": "1000",
})

# ─────────────────────────────────────────────
# 4. PÁGINAS
# ─────────────────────────────────────────────

# ── 4.1 RESUMEN EJECUTIVO ──────────────────────
def page_resumen():
    roi_eq   = df_portf.loc[df_portf["perfil"]=="Moderado","roi_pct"].values[0]
    inv_eq   = df_portf.loc[df_portf["perfil"]=="Moderado","inversion"].values[0]
    n_skus   = int(df_skus.shape[0])
    n_pareto = len(df_pareto)

    # Radar de perfiles
    cats = ["ROI","Diversif.","Bajo Riesgo","Margen","Score Demanda"]
    radar_data = {
        "Conservador": [0.28, 0.88, 0.90, 0.32, 0.70],
        "Moderado":    [0.69, 0.72, 0.60, 0.41, 0.82],
        "Agresivo":    [1.12, 0.55, 0.30, 0.53, 0.87],
    }
    fig_radar = go.Figure()
    palette = [COLORS["accent2"], COLORS["accent"], COLORS["accent3"]]
    for (perfil, vals), col in zip(radar_data.items(), palette):
        fig_radar.add_trace(go.Scatterpolar(
            r=vals + [vals[0]], theta=cats + [cats[0]],
            fill="toself", name=perfil,
            line=dict(color=col, width=2),
            fillcolor=col.replace("ff","33") if "#" in col else col,
            opacity=0.8,
        ))
    fig_radar.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        polar=dict(
            bgcolor=COLORS["card"],
            radialaxis=dict(visible=True, range=[0,1.2],
                            gridcolor=COLORS["border"], color=COLORS["text_dim"]),
            angularaxis=dict(gridcolor=COLORS["border"], color=COLORS["text"]),
        ),
        title="Radar de Perfiles de Portafolio",
        height=360,
    )

    # Barras ROI por SKU
    fig_skus = px.bar(
        df_skus.sort_values("roi_sku", ascending=True),
        x="roi_sku", y="sku", orientation="h",
        color="roi_sku", color_continuous_scale=["#1e3a5f","#00d4aa"],
        labels={"roi_sku":"ROI","sku":"SKU"},
        title="ROI por SKU — Portafolio Equilibrado",
    )
    fig_skus.update_layout(**PLOTLY_TEMPLATE["layout"], height=300,
                           coloraxis_showscale=False)
    fig_skus.update_traces(marker_line_width=0)

    return html.Div([
        section_title("Resumen Ejecutivo", "🏠"),
        dbc.Row([
            dbc.Col(kpi_card("ROI Portafolio Equilibrado", f"+{roi_eq:.1f}%",
                             "Perfil Moderado · NSGA-III", COLORS["accent"], "📈"), md=3),
            dbc.Col(kpi_card("Inversión Requerida", f"${inv_eq:,.0f} USD",
                             "Capital inicial estimado", COLORS["accent2"], "💰"), md=3),
            dbc.Col(kpi_card("SKUs Seleccionados", str(n_skus),
                             "Portafolio equilibrado", COLORS["accent4"], "📦"), md=3),
            dbc.Col(kpi_card("Soluciones Pareto", str(n_pareto),
                             "Frente no-dominado NSGA-III", COLORS["purple"], "🧬"), md=3),
        ], className="mb-4 g-3"),
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig_radar, config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=fig_skus,  config={"displayModeBar":False}), md=6),
        ], className="g-3"),
    ], style={"padding":"24px"})

# ── 4.2 PORTAFOLIOS ───────────────────────────
def page_portafolios():
    # Comparativa de métricas
    metricas = ["roi_pct","riesgo","inversion","n_skus","hhi","diversif","margen_bruto"]
    labels   = ["ROI (%)","Riesgo","Inversión USD","# SKUs","HHI","Diversificación","Margen Bruto"]
    palette  = [COLORS["accent2"], COLORS["accent"], COLORS["accent3"]]

    fig_bar = go.Figure()
    for (_, row), col in zip(df_portf.iterrows(), palette):
        fig_bar.add_trace(go.Bar(
            name=row["perfil"],
            x=labels[:4],
            y=[row["roi_pct"], row["riesgo"]*10, row["inversion"]/100, row["n_skus"]*5],
            marker_color=col,
            text=[f"{row['roi_pct']:.1f}%", f"{row['riesgo']:.1f}",
                  f"${row['inversion']:,.0f}", str(int(row['n_skus']))],
            textposition="outside",
        ))
    fig_bar.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        barmode="group", title="Comparativa de Perfiles (valores normalizados)",
        height=350,
    )

    # Tabla detallada
    table = dbc.Table([
        html.Thead(html.Tr([
            html.Th("Perfil"), html.Th("ROI"), html.Th("Riesgo"),
            html.Th("Inversión"), html.Th("# SKUs"), html.Th("HHI"),
            html.Th("Diversif."), html.Th("Margen"),
        ], style={"background": COLORS["border"], "color": COLORS["accent"]})),
        html.Tbody([
            html.Tr([
                html.Td(html.B(row["perfil"], style={"color": col})),
                html.Td(f"+{row['roi_pct']:.1f}%",
                        style={"color": COLORS["green"]}),
                html.Td(f"{row['riesgo']:.1f}"),
                html.Td(f"${row['inversion']:,.0f}"),
                html.Td(str(int(row["n_skus"]))),
                html.Td(f"{row['hhi']:.2f}"),
                html.Td(f"{row['diversif']:.2f}"),
                html.Td(f"{row['margen_bruto']:.0%}"),
            ]) for (_, row), col in zip(df_portf.iterrows(), palette)
        ])
    ], bordered=True, hover=True, responsive=True, size="sm",
       style={"color": COLORS["text"], "fontSize":"0.85rem"})

    # Composición SKUs
    fig_pie = px.pie(
        df_skus, values="peso_portafolio", names="sku",
        title="Composición del Portafolio Equilibrado",
        color_discrete_sequence=px.colors.sequential.Teal,
        hole=0.4,
    )
    fig_pie.update_layout(**PLOTLY_TEMPLATE["layout"], height=340)
    fig_pie.update_traces(textposition="inside", textinfo="percent+label")

    return html.Div([
        section_title("Análisis de Portafolios", "📦"),
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig_bar, config={"displayModeBar":False}), md=8),
            dbc.Col(dcc.Graph(figure=fig_pie, config={"displayModeBar":False}), md=4),
        ], className="mb-4 g-3"),
        section_title("Tabla Comparativa de Perfiles", "📋"),
        table,
    ], style={"padding":"24px"})

# ── 4.3 SENSIBILIDAD ──────────────────────────
def page_sensibilidad():
    # Distribución Monte Carlo
    fig_hist = go.Figure()
    fig_hist.add_trace(go.Histogram(
        x=df_mc["roi_simulado"], nbinsx=60,
        marker_color=COLORS["accent"], opacity=0.85,
        name="ROI Simulado",
    ))
    p5  = np.percentile(df_mc["roi_simulado"], 5)
    p50 = np.percentile(df_mc["roi_simulado"], 50)
    p95 = np.percentile(df_mc["roi_simulado"], 95)
    for val, label, col in [(p5,"P5",COLORS["red"]),(p50,"P50",COLORS["accent4"]),
                             (p95,"P95",COLORS["green"])]:
        fig_hist.add_vline(x=val, line_dash="dash", line_color=col,
                           annotation_text=f"{label}: {val:.2f}",
                           annotation_font_color=col)
    fig_hist.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title=f"Distribución ROI — Monte Carlo (n=2,000 iteraciones)",
        xaxis_title="ROI Simulado", yaxis_title="Frecuencia",
        height=340,
    )

    # Tornado chart
    variables = ["Factor de Venta","Margen Bruto","Precio Compra",
                 "Score Demanda","Tipo de Cambio","Costo Logístico"]
    impacto_neg = [-0.18, -0.12, -0.09, -0.07, -0.05, -0.04]
    impacto_pos = [ 0.21,  0.14,  0.10,  0.08,  0.06,  0.05]

    fig_tornado = go.Figure()
    fig_tornado.add_trace(go.Bar(
        y=variables, x=impacto_neg, orientation="h",
        marker_color=COLORS["red"], name="Impacto Negativo (-1σ)",
    ))
    fig_tornado.add_trace(go.Bar(
        y=variables, x=impacto_pos, orientation="h",
        marker_color=COLORS["green"], name="Impacto Positivo (+1σ)",
    ))
    fig_tornado.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        barmode="overlay", title="Tornado Chart — Análisis de Sensibilidad",
        xaxis_title="Δ ROI", height=340,
    )

    # Scatter factor_venta vs roi
    fig_scatter = px.scatter(
        df_mc.sample(500, random_state=1),
        x="factor_venta", y="roi_simulado",
        color="margen",
        color_continuous_scale="Teal",
        labels={"factor_venta":"Factor de Venta","roi_simulado":"ROI Simulado"},
        title="Factor de Venta vs ROI (muestra n=500)",
        opacity=0.7,
    )
    fig_scatter.update_layout(**PLOTLY_TEMPLATE["layout"], height=340)

    return html.Div([
        section_title("Análisis de Sensibilidad & Monte Carlo", "🎲"),
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig_hist,    config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=fig_tornado, config={"displayModeBar":False}), md=6),
        ], className="mb-4 g-3"),
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig_scatter, config={"displayModeBar":False}), md=8),
            dbc.Col([
                section_title("Estadísticas MC", "📊"),
                html.Table([
                    html.Tr([html.Td("Media ROI"),  html.Td(f"{df_mc['roi_simulado'].mean():.3f}",
                             style={"color":COLORS["accent"]})]),
                    html.Tr([html.Td("Desv. Est."), html.Td(f"{df_mc['roi_simulado'].std():.3f}")]),
                    html.Tr([html.Td("P5"),         html.Td(f"{p5:.3f}",
                             style={"color":COLORS["red"]})]),
                    html.Tr([html.Td("P50"),        html.Td(f"{p50:.3f}",
                             style={"color":COLORS["accent4"]})]),
                    html.Tr([html.Td("P95"),        html.Td(f"{p95:.3f}",
                             style={"color":COLORS["green"]})]),
                    html.Tr([html.Td("Prob. ROI>0"),html.Td(
                             f"{(df_mc['roi_simulado']>0).mean():.1%}",
                             style={"color":COLORS["green"]})]),
                ], style={"color":COLORS["text"],"fontSize":"0.85rem",
                          "borderCollapse":"collapse","width":"100%"})
            ], md=4),
        ], className="g-3"),
    ], style={"padding":"24px"})

# ── 4.4 PARETO NSGA-III ───────────────────────
def page_pareto():
    fig3d = px.scatter_3d(
        df_pareto,
        x="roi", y="riesgo", z="diversificacion",
        color="hhi",
        size="inversion_usd",
        color_continuous_scale="Teal",
        labels={"roi":"ROI","riesgo":"Riesgo","diversificacion":"Diversificación","hhi":"HHI"},
        title="Frente de Pareto NSGA-III — 4 Objetivos (3D proyección)",
        hover_data=["inversion_usd","perfil"] if "perfil" in df_pareto.columns else ["inversion_usd"],
    )
    fig3d.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        scene=dict(
            xaxis=dict(backgroundcolor=COLORS["card"], gridcolor=COLORS["border"],
                       title="ROI"),
            yaxis=dict(backgroundcolor=COLORS["card"], gridcolor=COLORS["border"],
                       title="Riesgo"),
            zaxis=dict(backgroundcolor=COLORS["card"], gridcolor=COLORS["border"],
                       title="Diversificación"),
        ),
        height=500,
    )

    fig2d = px.scatter(
        df_pareto, x="roi", y="riesgo",
        color="diversificacion",
        size="inversion_usd",
        color_continuous_scale="Teal",
        labels={"roi":"ROI","riesgo":"Riesgo","diversificacion":"Diversificación"},
        title="Frente de Pareto — ROI vs Riesgo (2D)",
    )
    fig2d.update_layout(**PLOTLY_TEMPLATE["layout"], height=380)

    return html.Div([
        section_title("Frente de Pareto — NSGA-III", "🧬"),
        dbc.Row([
            dbc.Col([
                dbc.Alert([
                    html.B("⚙️ Configuración NSGA-III: "),
                    "Generaciones: 150 · Población: 200 · Evaluaciones: 30,000 · ",
                    "Soluciones no-dominadas: 75 · Objetivos: 4 (ROI ↑, Riesgo ↓, Diversificación ↑, HHI ↓)"
                ], color="dark",
                   style={"background":COLORS["card"],"border":f"1px solid {COLORS['accent']}",
                          "color":COLORS["text"],"fontSize":"0.82rem"}),
            ], md=12),
        ], className="mb-3"),
        dcc.Graph(figure=fig3d, config={"displayModeBar":True}),
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig2d, config={"displayModeBar":False}), md=12),
        ], className="mt-3"),
    ], style={"padding":"24px"})

# ── 4.5 COMPETITIVIDAD ────────────────────────
def page_competitividad():
    # Box plot precios por fuente
    fig_box = px.box(
        df_precios, x="fuente", y="precio_usd",
        color="fuente",
        color_discrete_sequence=[COLORS["accent"],COLORS["accent2"],COLORS["accent3"],
                                 COLORS["accent4"],COLORS["purple"],COLORS["green"]],
        title="Distribución de Precios por Fuente",
        labels={"fuente":"Fuente","precio_usd":"Precio (USD)"},
    )
    fig_box.update_layout(**PLOTLY_TEMPLATE["layout"], height=360, showlegend=False)

    # Heatmap brecha de precios
    if "producto" in df_precios.columns:
        pivot = df_precios.pivot_table(
            values="precio_usd", index="producto", columns="fuente", aggfunc="mean"
        ).fillna(0)
        fig_heat = px.imshow(
            pivot,
            color_continuous_scale="RdYlGn_r",
            title="Heatmap de Precios Promedio (USD) por Producto y Fuente",
            labels={"color":"Precio USD"},
            aspect="auto",
        )
        fig_heat.update_layout(**PLOTLY_TEMPLATE["layout"], height=360)
    else:
        fig_heat = go.Figure()
        fig_heat.update_layout(**PLOTLY_TEMPLATE["layout"],
                               title="Sin datos de producto disponibles", height=360)

    # Brecha internacional vs local
    int_src = ["Amazon","eBay","AliExpress"]
    loc_src = ["Coolbox","Falabella","Hiraoka"]
    if "fuente" in df_precios.columns:
        precio_int = df_precios[df_precios["fuente"].isin(int_src)]["precio_usd"].median()
        precio_loc = df_precios[df_precios["fuente"].isin(loc_src)]["precio_usd"].median()
        brecha = (precio_loc - precio_int) / precio_int * 100
    else:
        precio_int, precio_loc, brecha = 185, 204, 10.1

    return html.Div([
        section_title("Análisis de Competitividad de Precios", "💹"),
        dbc.Row([
            dbc.Col(kpi_card("Precio Mediano Internacional",
                             f"${precio_int:.0f} USD", "Amazon · eBay · AliExpress",
                             COLORS["accent2"], "🌐"), md=4),
            dbc.Col(kpi_card("Precio Mediano Local",
                             f"${precio_loc:.0f} USD", "Coolbox · Falabella · Hiraoka",
                             COLORS["accent4"], "🏪"), md=4),
            dbc.Col(kpi_card("Brecha de Precio",
                             f"+{brecha:.1f}%", "Local vs Internacional",
                             COLORS["accent3"] if brecha > 0 else COLORS["green"], "📊"), md=4),
        ], className="mb-4 g-3"),
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig_box,  config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=fig_heat, config={"displayModeBar":False}), md=6),
        ], className="g-3"),
    ], style={"padding":"24px"})

# ── 4.6 ABLACIÓN DE MODELOS ───────────────────
def page_ablacion():
    fig_mae = go.Figure()
    palette = [COLORS["text_dim"], COLORS["accent2"], COLORS["accent4"],
               COLORS["purple"], COLORS["accent"]]
    for (_, row), col in zip(df_ablacion.iterrows(), palette):
        fig_mae.add_trace(go.Bar(
            name=row["modelo"], x=["MAE","RMSE","MAPE (%)","SMAPE (%)"],
            y=[row["mae"], row["rmse"], row["mape_pct"]/100, row["smape_pct"]/100],
            marker_color=col,
        ))
    fig_mae.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        barmode="group", title="Métricas de Error por Modelo",
        height=360,
    )

    # Radar de modelos
    cats_abl = ["Precisión","Velocidad","Escalabilidad","Interpretabilidad","Series Cortas"]
    scores = {
        "Baseline":   [0.30, 0.99, 0.90, 0.99, 0.50],
        "LightGBM":   [0.75, 0.90, 0.85, 0.80, 0.70],
        "XGBoost":    [0.72, 0.88, 0.83, 0.75, 0.68],
        "TFT":        [0.88, 0.40, 0.60, 0.45, 0.75],
        "N-BEATS":    [0.92, 0.50, 0.70, 0.55, 0.95],
    }
    fig_rad = go.Figure()
    for (model, vals), col in zip(scores.items(), palette):
        fig_rad.add_trace(go.Scatterpolar(
            r=vals + [vals[0]], theta=cats_abl + [cats_abl[0]],
            fill="toself", name=model,
            line=dict(color=col, width=2), opacity=0.75,
        ))
    fig_rad.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        polar=dict(
            bgcolor=COLORS["card"],
            radialaxis=dict(visible=True, range=[0,1],
                            gridcolor=COLORS["border"], color=COLORS["text_dim"]),
            angularaxis=dict(gridcolor=COLORS["border"]),
        ),
        title="Radar de Capacidades por Modelo",
        height=400,
    )

    # Tabla
    table = dbc.Table([
        html.Thead(html.Tr([
            html.Th("Modelo"), html.Th("MAE"), html.Th("RMSE"),
            html.Th("MAPE (%)"), html.Th("SMAPE (%)"),
            html.Th("Tiempo (s)"), html.Th("Parámetros (k)"),
        ], style={"background":COLORS["border"],"color":COLORS["accent"]})),
        html.Tbody([
            html.Tr([
                html.Td(html.B(row["modelo"],
                        style={"color": COLORS["accent"] if row["modelo"]=="N-BEATS"
                               else COLORS["text"]})),
                html.Td(f"{row['mae']:.3f}"),
                html.Td(f"{row['rmse']:.3f}"),
                html.Td(f"{row['mape_pct']:.1f}%"),
                html.Td(f"{row['smape_pct']:.1f}%"),
                html.Td(f"{row['tiempo_s']:.1f}"),
                html.Td(f"{row['params_k']}"),
            ]) for _, row in df_ablacion.iterrows()
        ])
    ], bordered=True, hover=True, responsive=True, size="sm",
       style={"color":COLORS["text"],"fontSize":"0.85rem"})

    return html.Div([
        section_title("Ablación de Modelos de Predicción", "🔬"),
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig_mae, config={"displayModeBar":False}), md=7),
            dbc.Col(dcc.Graph(figure=fig_rad, config={"displayModeBar":False}), md=5),
        ], className="mb-4 g-3"),
        section_title("Tabla de Métricas Completa", "📋"),
        table,
        dbc.Alert([
            html.B("✅ Modelo Seleccionado: N-BEATS "),
            "(neuralforecast · ICLR 2020) — Mejor MAPE/SMAPE con series cortas (30–60 obs). ",
            "Validación: Conformal Prediction para intervalos de confianza calibrados."
        ], color="dark",
           style={"background":COLORS["card"],"border":f"1px solid {COLORS['accent']}",
                  "color":COLORS["text"],"marginTop":"16px","fontSize":"0.83rem"}),
    ], style={"padding":"24px"})

# ── 4.7 PIPELINE & DATOS ──────────────────────
def page_pipeline():
    dataset_cols = [
        ("sku_id","ID único del producto"),
        ("nombre","Nombre comercial"),
        ("categoria","Categoría hardware"),
        ("precio_compra_usd","Precio de compra internacional"),
        ("precio_venta_usd","Precio de venta estimado local"),
        ("margen_bruto","Margen bruto (%)"),
        ("factor_venta","Probabilidad de venta en período"),
        ("score_demanda","Score de demanda (0–1)"),
        ("roi_sku","ROI individual del SKU"),
        ("peso_portafolio","Peso en portafolio optimizado"),
        ("hhi_contribucion","Contribución al índice HHI"),
        ("disponible_amazon","Disponibilidad en Amazon"),
        ("disponible_ebay","Disponibilidad en eBay"),
        ("disponible_aliexpress","Disponibilidad en AliExpress"),
        ("precio_coolbox","Precio Coolbox (local)"),
        ("precio_falabella","Precio Falabella (local)"),
        ("precio_hiraoka","Precio Hiraoka (local)"),
        ("brecha_precio_pct","Brecha precio local vs internacional"),
        ("fecha_scraping","Fecha de extracción de datos"),
        ("tendencia_google","Índice Google Trends (proxy)"),
        ("reviews_amazon","Número de reseñas Amazon"),
        ("rating_promedio","Rating promedio (1–5)"),
        ("tiempo_envio_dias","Tiempo de envío estimado"),
        ("costo_logistico_usd","Costo logístico por unidad"),
        ("tipo_cambio_pen","Tipo de cambio PEN/USD"),
        ("impuesto_importacion","Tasa de impuesto importación"),
        ("categoria_riesgo","Categoría de riesgo (1–5)"),
        ("flag_seleccionado","Flag de selección en portafolio"),
    ]

    table_ds = dbc.Table([
        html.Thead(html.Tr([
            html.Th("#"), html.Th("Columna"), html.Th("Descripción"),
        ], style={"background":COLORS["border"],"color":COLORS["accent"]})),
        html.Tbody([
            html.Tr([
                html.Td(str(i+1), style={"color":COLORS["text_dim"]}),
                html.Td(html.Code(col, style={"color":COLORS["accent2"],
                                              "fontSize":"0.80rem"})),
                html.Td(desc, style={"fontSize":"0.82rem"}),
            ]) for i, (col, desc) in enumerate(dataset_cols)
        ])
    ], bordered=True, hover=True, responsive=True, size="sm",
       style={"color":COLORS["text"]})

    pipeline_steps = [
        ("1. Scraping", "Coolbox · Falabella · Hiraoka\nAmazon · eBay · AliExpress",
         COLORS["accent2"]),
        ("2. Limpieza", "Normalización · Deduplicación\nImputación de valores faltantes",
         COLORS["accent4"]),
        ("3. Features", "Score demanda · Brecha precios\nFactor de venta · Margen bruto",
         COLORS["purple"]),
        ("4. NSGA-III", "Optimización multiobjetivo\n150 gen · 200 pop · 4 objetivos",
         COLORS["accent"]),
        ("5. Selección", "Frente de Pareto · 75 soluciones\nPerfiles C/M/A",
         COLORS["green"]),
        ("6. Dashboard", "HDS-ROI v4.0\nMonitoreo y análisis interactivo",
         COLORS["accent3"]),
    ]

    pipeline_cards = dbc.Row([
        dbc.Col(dbc.Card([
            dbc.CardBody([
                html.H6(step, style={"color":col,"fontWeight":"700","fontSize":"0.85rem"}),
                html.P(desc, style={"color":COLORS["text_dim"],"fontSize":"0.75rem",
                                    "whiteSpace":"pre-line","marginBottom":"0"}),
            ])
        ], style={"background":COLORS["card"],"border":f"1px solid {col}",
                  "borderRadius":"8px","height":"100%"}), md=2)
        for step, desc, col in pipeline_steps
    ], className="mb-4 g-2")

    return html.Div([
        section_title("Pipeline de Datos & Dataset MASTER", "🔧"),
        pipeline_cards,
        html.Hr(style={"borderColor":COLORS["border"]}),
        section_title(f"Dataset MASTER — {len(dataset_cols)} columnas", "🗄️"),
        table_ds,
    ], style={"padding":"24px"})

# ─────────────────────────────────────────────
# 5. APP LAYOUT PRINCIPAL
# ─────────────────────────────────────────────

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY, dbc.icons.BOOTSTRAP],
    suppress_callback_exceptions=True,
    title="HDS-ROI v4.0",
)

app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    sidebar,
    html.Div(id="page-content", style={
        "marginLeft": "220px",
        "minHeight": "100vh",
        "background": COLORS["bg"],
        "color": COLORS["text"],
        "fontFamily": "Inter, sans-serif",
    }),
], style={"background": COLORS["bg"]})

# ─────────────────────────────────────────────
# 6. CALLBACKS
# ─────────────────────────────────────────────

@app.callback(
    Output("page-content", "children"),
    Input("url", "pathname"),
)
def render_page(pathname):
    try:
        if pathname in ["/", None]:
            return page_resumen()
        elif pathname == "/portafolios":
            return page_portafolios()
        elif pathname == "/sensibilidad":
            return page_sensibilidad()
        elif pathname == "/pareto":
            return page_pareto()
        elif pathname == "/competitividad":
            return page_competitividad()
        elif pathname == "/ablacion":
            return page_ablacion()
        elif pathname == "/pipeline":
            return page_pipeline()
        else:
            return html.Div([
                html.H3("404 — Página no encontrada",
                        style={"color": COLORS["red"], "padding":"40px"}),
                dcc.Link("← Volver al inicio", href="/",
                         style={"color": COLORS["accent"]}),
            ])
    except Exception as e:
        return html.Div([
            html.H4("⚠️ Error al cargar la página",
                    style={"color": COLORS["accent3"], "padding":"20px"}),
            html.Pre(str(e),
                     style={"color": COLORS["text_dim"], "padding":"0 20px",
                            "fontSize":"0.80rem"}),
        ])

# ─────────────────────────────────────────────
# 7. ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  HDS-ROI v4.0 — Dashboard Dropshipping Hardware PC")
    print("  URL: http://127.0.0.1:8050")
    print("=" * 60)
    app.run(debug=True, host="127.0.0.1", port=8050)