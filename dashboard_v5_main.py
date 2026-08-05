# =============================================================================
# HDS-ROI v6.0 — Dashboard Principal (Tema Blanco)
# Autor: Proyecto de Tesis
# Fecha: 2026-07-30
# Stack: Dash 2.x · Plotly · Pandas · NumPy
# Ejecución: python dashboard_v5_main.py  →  http://127.0.0.1:8050
# =============================================================================

import os
import warnings
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

import dash
from dash import dcc, html, Input, Output, State, callback_context
import dash_bootstrap_components as dbc

# Importar configuración y datos
from dashboard_config import (
    COLORS, PLOTLY_TEMPLATE, CHART_CONFIG, PALETTE_CATEGORICAL,
    SIDEBAR_STYLE, CONTENT_STYLE, TYPOGRAPHY, ICONS, APP_CONFIG
)
from dashboard_data import DATA

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────
# 0. CONFIGURACIÓN INICIAL
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
    """Tarjeta KPI profesional."""
    color = color or COLORS["accent"]
    
    if size == "lg":
        height = "140px"
        title_size = "0.85rem"
        value_size = "2.2rem"
    else:
        height = "120px"
        title_size = "0.75rem"
        value_size = "1.8rem"
    
    return dbc.Card([
        dbc.CardBody([
            html.Div([
                html.Span(icon, style={
                    "fontSize": "2rem",
                    "marginRight": "12px",
                    "opacity": 0.8,
                }),
                html.Div([
                    html.P(title, className="mb-1", style={
                        "color": COLORS["text_dim"],
                        "fontSize": title_size,
                        "textTransform": "uppercase",
                        "letterSpacing": "0.05em",
                        "fontWeight": 600,
                    }),
                    html.H4(value, className="mb-1", style={
                        "color": color,
                        "fontSize": value_size,
                        "fontWeight": 700,
                    }),
                    html.P(subtitle, className="mb-0", style={
                        "color": COLORS["text_dim"],
                        "fontSize": "0.7rem",
                    }),
                ], style={"flex": 1})
            ], style={
                "display": "flex",
                "alignItems": "center",
                "height": "100%",
            })
        ], style={"padding": "16px"})
    ], style={
        "background": COLORS["bg"],
        "border": f"2px solid {COLORS['border']}",
        "borderRadius": "10px",
        "height": height,
        "transition": "all 0.3s ease",
        "cursor": "pointer",
    }, className="shadow-sm")

def section_title(text, icon=""):
    """Título de sección con estilo."""
    return html.H5(
        [html.Span(icon + " ", style={"marginRight": "8px", "color": COLORS["accent"]}), text],
        style={
            "color": COLORS["accent"],
            "borderBottom": f"3px solid {COLORS['accent']}",
            "paddingBottom": "10px",
            "marginBottom": "20px",
            "fontWeight": 700,
            "fontSize": "1.1rem",
        }
    )

def nav_link(label, href, icon=""):
    """Enlace de navegación en sidebar."""
    return dbc.NavLink(
        [html.Span(icon, style={"marginRight": "10px", "fontSize": "1.1rem"}), label],
        href=href,
        active="exact",
        style={
            "color": COLORS["text"],
            "borderRadius": "6px",
            "marginBottom": "6px",
            "fontSize": "0.9rem",
            "padding": "8px 12px",
            "transition": "all 0.2s ease",
        },
        className="nav-link-custom",
    )

# ─────────────────────────────────────────────
# 2. FUNCIONES AUXILIARES (MOTOR DE DECISIÓN)
# ─────────────────────────────────────────────

def generar_recomendaciones():
    """Motor de decisión: 3 opciones de inversión."""
    df_oe9 = DATA["oe9_pareto"]
    
    if len(df_oe9) == 0:
        return None
    
    # Mejor ROI absoluto
    mejor_roi = df_oe9.nlargest(1, "roi_pct").iloc[0]
    
    # Mejor balance (ROI normalizado / riesgo normalizado)
    df_oe9_copy = df_oe9.copy()
    df_oe9_copy["score_balance"] = (df_oe9_copy["roi_pct"] / df_oe9_copy["roi_pct"].max()) / (df_oe9_copy["rj_portafolio"] / df_oe9_copy["rj_portafolio"].max() + 0.01)
    mejor_balance = df_oe9_copy.nlargest(1, "score_balance").iloc[0]
    
    # Mejor eficiencia (ROI / Capital)
    df_oe9_copy["eficiencia"] = df_oe9_copy["roi_pct"] / (df_oe9_copy["capital_usd"] / 1000)
    mejor_eficiencia = df_oe9_copy.nlargest(1, "eficiencia").iloc[0]
    
    return {
        "agresivo": {
            "tipo": mejor_roi["tipo"],
            "roi": mejor_roi["roi_pct"],
            "rj": mejor_roi["rj_portafolio"],
            "capital": mejor_roi["capital_usd"],
            "ganancia": mejor_roi["ganancia_usd"],
            "perfil": "🔥 MÁXIMO ROI (Agresivo)",
            "para": "Inversionistas con alta tolerancia al riesgo"
        },
        "balanceado": {
            "tipo": mejor_balance["tipo"],
            "roi": mejor_balance["roi_pct"],
            "rj": mejor_balance["rj_portafolio"],
            "capital": mejor_balance["capital_usd"],
            "ganancia": mejor_balance["ganancia_usd"],
            "perfil": "⚖️ MEJOR BALANCE (Recomendado)",
            "para": "Mayoría de inversionistas"
        },
        "eficiente": {
            "tipo": mejor_eficiencia["tipo"],
            "roi": mejor_eficiencia["roi_pct"],
            "rj": mejor_eficiencia["rj_portafolio"],
            "capital": mejor_eficiencia["capital_usd"],
            "ganancia": mejor_eficiencia["ganancia_usd"],
            "perfil": "💎 MÁXIMA EFICIENCIA",
            "para": "Inversionistas con presupuesto limitado"
        }
    }

def calcular_simulador(presupuesto, roi_pct, capital_unitario):
    """Simula compra con presupuesto flexible."""
    if presupuesto < 1000 or capital_unitario <= 0:
        return None
    
    unidades = int(presupuesto / capital_unitario)
    capital_total = unidades * capital_unitario
    ganancia_unitaria = capital_unitario * (roi_pct / 100)
    ganancia_total = unidades * ganancia_unitaria
    roi_total = (ganancia_total / capital_total * 100) if capital_total > 0 else 0
    
    return {
        "unidades": unidades,
        "capital_total": capital_total,
        "ganancia_unitaria": ganancia_unitaria,
        "ganancia_total": ganancia_total,
        "roi_total": roi_total,
    }

# ─────────────────────────────────────────────
# 3. SIDEBAR
# ─────────────────────────────────────────────

sidebar = html.Div([
    # Logo
    html.Div([
        html.H4("HDS-ROI", style={
            "color": COLORS["accent"],
            "fontWeight": 800,
            "letterSpacing": "0.08em",
            "marginBottom": "4px",
            "fontSize": "1.4rem",
        }),
        html.P("v6.0 · Dropshipping Hardware", style={
            "color": COLORS["text_dim"],
            "fontSize": "0.7rem",
            "marginBottom": "0",
            "letterSpacing": "0.05em",
        }),
    ], style={
        "padding": "16px 12px 12px",
        "borderBottom": f"2px solid {COLORS['border']}",
        "marginBottom": "12px",
    }),

    # Navegación
    dbc.Nav([
        nav_link("🎯 Motor de Decisión", "/", ICONS["home"]),
        nav_link("💰 Simulador", "/simulador", "💰"),
        nav_link("OE9 NSGA-III", "/oe9", ICONS["pareto"]),
        nav_link("Análisis de Datos", "/datos", ICONS["data"]),
        nav_link("Portafolios", "/portafolios", ICONS["portfolio"]),
        nav_link("Sensibilidad", "/sensibilidad", ICONS["sensitivity"]),
        nav_link("Pareto Original", "/pareto", ICONS["chart"]),
        nav_link("Competitividad", "/competitividad", ICONS["competitive"]),
        nav_link("Ablación Modelos", "/ablacion", ICONS["ablation"]),
        nav_link("Pipeline & Datos", "/pipeline", ICONS["pipeline"]),
    ], vertical=True, pills=True, style={
        "padding": "8px 0",
        "flexDirection": "column",
    }),

    # Footer
    html.Div([
        html.Hr(style={"borderColor": COLORS["border"], "margin": "12px 0"}),
        html.P("📅 30 Jul 2026", style={
            "color": COLORS["text_dim"],
            "fontSize": "0.7rem",
            "marginBottom": "4px",
        }),
        html.P("🟢 Sistema Operativo", style={
            "color": COLORS["green"],
            "fontSize": "0.7rem",
            "marginBottom": "0",
            "fontWeight": 600,
        }),
    ], style={
        "padding": "12px 0",
        "borderTop": f"1px solid {COLORS['border']}",
        "marginTop": "auto",
    }),
], style={
    **SIDEBAR_STYLE,
    "display": "flex",
    "flexDirection": "column",
    "background": COLORS["card"],
})

# ─────────────────────────────────────────────
# 4. PÁGINA: MOTOR DE DECISIÓN v6.0
# ─────────────────────────────────────────────

def page_resumen():
    """Motor de Decisión v6.0."""
    recomendaciones = generar_recomendaciones()
    
    if not recomendaciones:
        return html.Div([
            section_title("🎯 Motor de Decisión v6.0", ICONS["home"]),
            dbc.Alert("⚠️ No hay datos disponibles", color="warning", style={"margin": "20px"}),
        ], style={"padding": "24px"})
    
    # Tarjetas de recomendación
    def tarjeta_recomendacion(clave, datos):
        color_map = {
            "agresivo": COLORS["accent3"],
            "balanceado": COLORS["accent"],
            "eficiente": COLORS["accent4"]
        }
        color = color_map.get(clave, COLORS["text"])
        
        return dbc.Card([
            dbc.CardBody([
                html.H5(datos["perfil"], style={"color": color, "fontWeight": 700, "marginBottom": "15px"}),
                html.Div([
                    html.Div([
                        html.P("Modelo", style={"fontSize": "0.75rem", "color": COLORS["text_dim"], "marginBottom": "2px"}),
                        html.H6(datos["tipo"], style={"color": COLORS["text"], "fontWeight": 600}),
                    ], style={"marginBottom": "12px"}),
                    html.Div([
                        html.P("ROI", style={"fontSize": "0.75rem", "color": COLORS["text_dim"], "marginBottom": "2px"}),
                        html.H6(f"+{datos['roi']:.1f}%", style={"color": COLORS["green"], "fontWeight": 700}),
                    ], style={"marginBottom": "12px"}),
                    html.Div([
                        html.P("Capital", style={"fontSize": "0.75rem", "color": COLORS["text_dim"], "marginBottom": "2px"}),
                        html.H6(f"${datos['capital']:,.0f}", style={"color": COLORS["text"], "fontWeight": 600}),
                    ], style={"marginBottom": "12px"}),
                    html.Div([
                        html.P("Ganancia", style={"fontSize": "0.75rem", "color": COLORS["text_dim"], "marginBottom": "2px"}),
                        html.H6(f"${datos['ganancia']:,.0f}", style={"color": COLORS["green"], "fontWeight": 600}),
                    ], style={"marginBottom": "12px"}),
                    html.Div([
                        html.P("Riesgo (r_j)", style={"fontSize": "0.75rem", "color": COLORS["text_dim"], "marginBottom": "2px"}),
                        html.H6(f"{datos['rj']:.4f}", style={"color": COLORS["text"], "fontWeight": 600}),
                    ], style={"marginBottom": "12px"}),
                    html.Hr(style={"margin": "12px 0", "borderColor": COLORS["border"]}),
                    html.P(datos["para"], style={"fontSize": "0.8rem", "color": COLORS["text_dim"], "fontStyle": "italic", "marginBottom": "0"}),
                ]),
            ], style={"padding": "16px"})
        ], style={"background": COLORS["bg"], "border": f"2px solid {color}", "borderRadius": "10px"})
    
    # KPIs principales
    kpi_row = dbc.Row([
        dbc.Col(kpi_card("🔥 MEJOR ROI", f"+{recomendaciones['agresivo']['roi']:.1f}%",
                         "Perfil Agresivo", COLORS["accent3"], "📈", "lg"), md=3),
        dbc.Col(kpi_card("⚖️ MEJOR BALANCE", f"+{recomendaciones['balanceado']['roi']:.1f}%",
                         "Recomendado", COLORS["accent"], "⚙️", "lg"), md=3),
        dbc.Col(kpi_card("💎 MEJOR EFICIENCIA", f"{(recomendaciones['eficiente']['roi'] / (recomendaciones['eficiente']['capital']/1000)):.2f}x",
                         "ROI/Capital", COLORS["accent4"], "💰", "lg"), md=3),
        dbc.Col(kpi_card("24 Soluciones", "Pareto",
                         "NSGA-III", COLORS["purple"], "📊", "lg"), md=3),
    ], className="mb-4 g-3")
    
    return html.Div([
        section_title("🎯 Motor de Decisión v6.0", ICONS["home"]),
        
        dbc.Alert([
            html.B("✨ NUEVO: "),
            "Motor de Decisión Inteligente — 3 opciones de inversión basadas en 24 soluciones Pareto"
        ], color="info", style={
            "background": COLORS["card"],
            "border": f"2px solid {COLORS['accent2']}",
            "color": COLORS["text"],
            "fontSize": "0.9rem",
            "marginBottom": "20px",
        }),
        
        kpi_row,
        
        dbc.Row([
            dbc.Col(tarjeta_recomendacion("agresivo", recomendaciones["agresivo"]), md=4),
            dbc.Col(tarjeta_recomendacion("balanceado", recomendaciones["balanceado"]), md=4),
            dbc.Col(tarjeta_recomendacion("eficiente", recomendaciones["eficiente"]), md=4),
        ], className="mb-4 g-3"),
        
        section_title("Próximos Pasos", ICONS["chart"]),
        dbc.Row([
            dbc.Col(dbc.Card([
                dbc.CardBody([
                    html.H6("1️⃣ Selecciona Perfil", style={"fontWeight": 700, "marginBottom": "10px"}),
                    html.P("Elige entre Agresivo, Balanceado o Eficiente según tu tolerancia al riesgo.",
                           style={"fontSize": "0.85rem", "marginBottom": "0"}),
                ])
            ], style={"background": COLORS["bg"], "border": f"1px solid {COLORS['border']}", "borderRadius": "8px"}), md=4),
            dbc.Col(dbc.Card([
                dbc.CardBody([
                    html.H6("2️⃣ Usa el Simulador", style={"fontWeight": 700, "marginBottom": "10px"}),
                    html.P("Ingresa tu presupuesto y visualiza ganancias potenciales.",
                           style={"fontSize": "0.85rem", "marginBottom": "0"}),
                ])
            ], style={"background": COLORS["bg"], "border": f"1px solid {COLORS['border']}", "borderRadius": "8px"}), md=4),
            dbc.Col(dbc.Card([
                dbc.CardBody([
                    html.H6("3️⃣ Ejecuta Compra", style={"fontWeight": 700, "marginBottom": "10px"}),
                    html.P("Revisa análisis de riesgo y procede con confianza.",
                           style={"fontSize": "0.85rem", "marginBottom": "0"}),
                ])
            ], style={"background": COLORS["bg"], "border": f"1px solid {COLORS['border']}", "borderRadius": "8px"}), md=4),
        ], className="g-3"),
    ], style={"padding": "24px"})

# ─────────────────────────────────────────────
# 5. PÁGINA: SIMULADOR
# ─────────────────────────────────────────────

def page_simulador():
    """Simulador interactivo de compra."""
    return html.Div([
        section_title("💰 Simulador de Compra", "💰"),
        
        dbc.Alert([
            html.B("📊 Calcula ganancia total con tu presupuesto disponible")
        ], color="info", style={
            "background": COLORS["card"],
            "border": f"2px solid {COLORS['accent2']}",
            "color": COLORS["text"],
            "fontSize": "0.9rem",
            "marginBottom": "20px",
        }),
        
        dbc.Row([
            dbc.Col([
                html.Label("💵 Presupuesto Disponible ($)", style={"fontWeight": 600, "marginBottom": "8px"}),
                dcc.Input(
                    id="input-presupuesto",
                    type="number",
                    placeholder="Ej: 100000",
                    value=100000,
                    min=1000,
                    step=1000,
                    style={
                        "width": "100%",
                        "padding": "10px",
                        "borderRadius": "6px",
                        "border": f"1px solid {COLORS['border']}",
                        "fontSize": "0.9rem",
                    }
                ),
            ], md=4),
            dbc.Col([
                html.Label("🎯 Modelo a Simular", style={"fontWeight": 600, "marginBottom": "8px"}),
                dcc.Dropdown(
                    id="dropdown-modelo",
                    options=[
                        {"label": "🔥 Agresivo (Máximo ROI)", "value": "agresivo"},
                        {"label": "⚖️ Balanceado (Recomendado)", "value": "balanceado"},
                        {"label": "💎 Eficiente", "value": "eficiente"},
                    ],
                    value="balanceado",
                    style={"width": "100%"},
                ),
            ], md=4),
            dbc.Col([
                html.Label("🔄 Actualizar", style={"fontWeight": 600, "marginBottom": "8px"}),
                dbc.Button(
                    "Calcular",
                    id="btn-simular",
                    color="primary",
                    className="w-100",
                    style={"height": "38px"}
                ),
            ], md=4),
        ], className="mb-4 g-3"),
        
        html.Div(id="simulador-resultados"),
    ], style={"padding": "24px"})

# ─────────────────────────────────────────────
# 6. PÁGINAS EXISTENTES (OE9, DATOS, etc.)
# ─────────────────────────────────────────────

def page_oe9():
    """Página de resultados OE9 NSGA-III."""
    df_oe9 = DATA["oe9_pareto"]
    resumen = DATA["oe9_resumen"]
    
    if len(df_oe9) == 0:
        return html.Div([
            section_title("OE9 NSGA-III", ICONS["pareto"]),
            dbc.Alert("⚠️ No hay datos OE9 disponibles. Ejecuta: python scripts/oe9_nsga3.py",
                     color="warning", style={"margin": "20px"}),
        ], style={"padding": "24px"})
    
    # Scatter ROI vs r_j
    fig_scatter1 = px.scatter(
        df_oe9,
        x="roi_pct",
        y="rj_portafolio",
        color="tipo",
        size="n_skus",
        hover_data=["capital_usd", "ganancia_usd"],
        color_discrete_map={
            "ESTRELLA": COLORS["accent"],
            "OPTIMO": COLORS["accent4"],
            "AGRESIVO": COLORS["accent3"],
            "BALANCEADO": COLORS["purple"],
            "SEGURO": COLORS["green"],
        },
        title="Frente de Pareto OE9 — ROI vs r_j (Obsolescencia)",
        labels={"roi_pct": "ROI (%)", "rj_portafolio": "r_j Obsolescencia"},
    )
    fig_scatter1.update_layout(**PLOTLY_TEMPLATE["layout"], height=380)
    
    # Scatter Capital vs Ganancia
    fig_scatter2 = px.scatter(
        df_oe9,
        x="capital_usd",
        y="ganancia_usd",
        color="roi_pct",
        size="n_skus",
        color_continuous_scale=["#e0e0e0", COLORS["accent"]],
        title="Capital Invertido vs Ganancia Estimada",
        labels={"capital_usd": "Capital (USD)", "ganancia_usd": "Ganancia (USD)"},
    )
    fig_scatter2.update_layout(**PLOTLY_TEMPLATE["layout"], height=380)
    
    # Distribución por tipo
    tipo_counts = df_oe9["tipo"].value_counts()
    fig_pie = px.pie(
        values=tipo_counts.values,
        names=tipo_counts.index,
        title="Distribución de Portafolios por Tipo",
        color_discrete_map={
            "ESTRELLA": COLORS["accent"],
            "OPTIMO": COLORS["accent4"],
            "AGRESIVO": COLORS["accent3"],
            "BALANCEADO": COLORS["purple"],
            "SEGURO": COLORS["green"],
        },
    )
    fig_pie.update_layout(**PLOTLY_TEMPLATE["layout"], height=380)
    
    # Top 10 por ROI
    top10 = df_oe9.nlargest(10, "roi_pct")[["tipo", "roi_pct", "rj_portafolio", "n_skus", "capital_usd", "ganancia_usd"]]
    
    table_top10 = dbc.Table([
        html.Thead(html.Tr([
            html.Th("Tipo", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("ROI (%)", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("r_j", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("SKUs", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("Capital ($)", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("Ganancia ($)", style={"color": COLORS["accent"], "fontWeight": 700}),
        ], style={"background": COLORS["card"], "borderBottom": f"2px solid {COLORS['border']}"})),
        html.Tbody([
            html.Tr([
                html.Td(html.B(row["tipo"], style={"color": {
                    "ESTRELLA": COLORS["accent"],
                    "OPTIMO": COLORS["accent4"],
                    "AGRESIVO": COLORS["accent3"],
                    "BALANCEADO": COLORS["purple"],
                    "SEGURO": COLORS["green"],
                }.get(row["tipo"], COLORS["text"])})),
                html.Td(f"{row['roi_pct']:.1f}%", style={"color": COLORS["green"], "fontWeight": 600}),
                html.Td(f"{row['rj_portafolio']:.4f}"),
                html.Td(str(int(row["n_skus"]))),
                html.Td(f"${row['capital_usd']:,.0f}"),
                html.Td(f"${row['ganancia_usd']:,.0f}", style={"color": COLORS["green"], "fontWeight": 600}),
            ], style={"borderBottom": f"1px solid {COLORS['border']}"})
            for _, row in top10.iterrows()
        ])
    ], bordered=True, hover=True, responsive=True, size="sm",
       style={"color": COLORS["text"], "fontSize": "0.85rem"})
    
    return html.Div([
        section_title("OE9 NSGA-III — 24 Soluciones Pareto", ICONS["pareto"]),
        
        dbc.Alert([
            html.B("⚙️ Configuración NSGA-III: "),
            "Generaciones: 200 · Población: 210 · Evaluaciones: 42,000 · ",
            "Soluciones no-dominadas: 24 · Objetivos: 7"
        ], color="info", style={
            "background": COLORS["card"],
            "border": f"2px solid {COLORS['accent2']}",
            "color": COLORS["text"],
            "fontSize": "0.85rem",
            "marginBottom": "20px",
        }),
        
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig_scatter1, config=CHART_CONFIG), md=6),
            dbc.Col(dcc.Graph(figure=fig_scatter2, config=CHART_CONFIG), md=6),
        ], className="mb-4 g-3"),
        
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig_pie, config=CHART_CONFIG), md=6),
            dbc.Col([
                section_title("Top 10 por ROI", ICONS["chart"]),
                html.Div(table_top10, style={"overflowX": "auto"}),
            ], md=6),
        ], className="g-3"),
    ], style={"padding": "24px"})

def page_datos():
    """Página de análisis detallado de datos."""
    data_quality = DATA["data_quality"]
    df_features = DATA["feature_matrix"]
    
    n_rows = data_quality["n_rows"]
    n_cols = data_quality["n_cols"]
    n_missing = data_quality["n_missing"]
    pct_missing = data_quality["pct_missing"]
    status = data_quality["status"]
    missing_by_col = data_quality["missing_by_col"]
    dtype_counts = data_quality["dtype_counts"]
    
    # KPIs de datos
    kpi_row1 = dbc.Row([
        dbc.Col(kpi_card("Total de Registros", str(n_rows),
                         "SKUs en catálogo", COLORS["accent"], ICONS["chart"]), md=3),
        dbc.Col(kpi_card("Total de Columnas", str(n_cols),
                         "Features disponibles", COLORS["accent2"], ICONS["data"]), md=3),
        dbc.Col(kpi_card("Valores Faltantes", str(n_missing),
                         f"{pct_missing:.1f}% del total", COLORS["accent3"], "⚠️"), md=3),
        dbc.Col(kpi_card("Estado de Limpieza", status,
                         "Imputación completada", COLORS["green"], ICONS["success"]), md=3),
    ], className="mb-4 g-3")
    
    # Gráfico: Top 10 columnas con valores faltantes
    if len(missing_by_col) > 0:
        top_missing = missing_by_col.head(10)
        fig_missing = px.bar(
            x=top_missing.values,
            y=top_missing.index,
            orientation="h",
            color=top_missing.values,
            color_continuous_scale=["#e0e0e0", COLORS["accent3"]],
            title="Top 10 Columnas con Valores Faltantes",
            labels={"x": "Cantidad de NaN", "y": "Columna"},
        )
        fig_missing.update_layout(**PLOTLY_TEMPLATE["layout"], height=320, coloraxis_showscale=False)
    else:
        fig_missing = go.Figure()
        fig_missing.add_annotation(text="✅ Sin valores faltantes", xref="paper", yref="paper",
                                   x=0.5, y=0.5, showarrow=False, font=dict(size=16, color=COLORS["green"]))
        fig_missing.update_layout(**PLOTLY_TEMPLATE["layout"], height=320)
    
    # Gráfico: Distribución de tipos de datos
    fig_dtypes = px.pie(
        values=dtype_counts.values,
        names=[str(x) for x in dtype_counts.index],
        title="Distribución de Tipos de Datos",
        color_discrete_sequence=PALETTE_CATEGORICAL,
    )
    fig_dtypes.update_layout(**PLOTLY_TEMPLATE["layout"], height=320)
    fig_dtypes.update_traces(textposition="inside", textinfo="percent+label")
    
    # Tabla: Primeras 15 columnas
    cols_info = []
    for col in df_features.columns[:15]:
        n_nan = df_features[col].isnull().sum()
        pct_nan = (n_nan / len(df_features)) * 100
        dtype = str(df_features[col].dtype)
        
        cols_info.append({
            "Columna": col,
            "Tipo": dtype,
            "NaN": n_nan,
            "% NaN": f"{pct_nan:.1f}%",
            "Valores Únicos": df_features[col].nunique(),
        })
    
    df_cols_info = pd.DataFrame(cols_info)
    
    table_cols = dbc.Table([
        html.Thead(html.Tr([
            html.Th("#", style={"color": COLORS["accent"], "fontWeight": 700, "width": "5%"}),
            html.Th("Columna", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("Tipo", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("NaN", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("% NaN", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("Únicos", style={"color": COLORS["accent"], "fontWeight": 700}),
        ], style={"background": COLORS["card"], "borderBottom": f"2px solid {COLORS['border']}"})),
        html.Tbody([
            html.Tr([
                html.Td(str(i+1), style={"color": COLORS["text_dim"], "fontWeight": 600}),
                html.Td(html.Code(row["Columna"], style={"color": COLORS["accent2"], "fontSize": "0.8rem"})),
                html.Td(row["Tipo"], style={"fontSize": "0.8rem"}),
                html.Td(str(row["NaN"]), style={"color": COLORS["text_dim"]}),
                html.Td(row["% NaN"], style={"color": COLORS["accent3"] if float(row["% NaN"].rstrip("%")) > 0 else COLORS["green"], "fontWeight": 600}),
                html.Td(str(row["Valores Únicos"])),
            ], style={"borderBottom": f"1px solid {COLORS['border']}"})
            for i, (_, row) in enumerate(df_cols_info.iterrows())
        ])
    ], bordered=True, hover=True, responsive=True, size="sm",
       style={"color": COLORS["text"], "fontSize": "0.85rem"})
    
    # Resumen de limpieza
    alert_limpieza = dbc.Alert([
        html.B("✅ Estado de Limpieza: "),
        html.Br(),
        html.Ul([
            html.Li(f"Registros recolectados: {n_rows} SKUs"),
            html.Li(f"Columnas disponibles: {n_cols} features"),
            html.Li(f"Valores faltantes: {n_missing} ({pct_missing:.1f}%)"),
            html.Li("Imputación: Completada (medianas)"),
            html.Li("Normalización: Aplicada"),
            html.Li("Deduplicación: Completada"),
            html.Li("Estado: ✅ Listo para análisis"),
        ], style={"marginBottom": "0", "marginLeft": "20px"}),
    ], color="success", style={
        "background": "#f0fdf4",
        "border": f"2px solid {COLORS['green']}",
        "color": COLORS["text"],
        "fontSize": "0.9rem",
    })
    
    return html.Div([
        section_title("Análisis de Datos — Recolección, Limpieza y Status", ICONS["data"]),
        
        kpi_row1,
        
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig_missing, config=CHART_CONFIG), md=6),
            dbc.Col(dcc.Graph(figure=fig_dtypes, config=CHART_CONFIG), md=6),
        ], className="mb-4 g-3"),
        
        section_title("Primeras 15 Columnas del Dataset", ICONS["chart"]),
        html.Div(table_cols, style={"overflowX": "auto", "marginBottom": "20px"}),
        
        section_title("Resumen de Limpieza", ICONS["success"]),
        alert_limpieza,
    ], style={"padding": "24px"})

def page_portafolios():
    """Página de análisis de portafolios."""
    df_portf = DATA["portafolios"]
    df_skus = DATA["skus"]
    
    # Gráfico comparativo de métricas
    fig_bar = go.Figure()
    
    metricas_display = ["roi_pct", "riesgo", "inversion", "n_skus"]
    labels_display = ["ROI (%)", "Riesgo", "Inversión (÷100)", "# SKUs (×5)"]
    palette = [COLORS["accent2"], COLORS["accent"], COLORS["accent3"]]
    
    for (_, row), col in zip(df_portf.iterrows(), palette):
        valores = [
            row["roi_pct"],
            row["riesgo"] * 10,
            row["inversion"] / 100,
            row["n_skus"] * 5,
        ]
        fig_bar.add_trace(go.Bar(
            name=row["perfil"],
            x=labels_display,
            y=valores,
            marker_color=col,
            text=[f"{v:.1f}" for v in valores],
            textposition="outside",
        ))
    
    fig_bar.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        barmode="group",
        title="Comparativa de Perfiles (valores normalizados)",
        height=350,
    )
    
    # Tabla comparativa
    table_portf = dbc.Table([
        html.Thead(html.Tr([
            html.Th("Perfil", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("ROI", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("Riesgo", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("Inversión", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("# SKUs", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("HHI", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("Diversif.", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("Margen", style={"color": COLORS["accent"], "fontWeight": 700}),
        ], style={"background": COLORS["card"], "borderBottom": f"2px solid {COLORS['border']}"})),
        html.Tbody([
            html.Tr([
                html.Td(html.B(row["perfil"], style={"color": col})),
                html.Td(f"+{row['roi_pct']:.1f}%", style={"color": COLORS["green"], "fontWeight": 600}),
                html.Td(f"{row['riesgo']:.1f}"),
                html.Td(f"${row['inversion']:,.0f}"),
                html.Td(str(int(row["n_skus"])), style={"textAlign": "center"}),
                html.Td(f"{row['hhi']:.2f}"),
                html.Td(f"{row['diversif']:.2f}"),
                html.Td(f"{row['margen_bruto']:.0%}"),
            ], style={"borderBottom": f"1px solid {COLORS['border']}"})
            for (_, row), col in zip(df_portf.iterrows(), palette)
        ])
    ], bordered=True, hover=True, responsive=True, size="sm",
       style={"color": COLORS["text"], "fontSize": "0.85rem"})
    
    # Composición SKUs
    fig_pie = px.pie(
        df_skus,
        values="peso_portafolio",
        names="sku",
        title="Composición del Portafolio Equilibrado",
        color_discrete_sequence=PALETTE_CATEGORICAL,
    )
    fig_pie.update_layout(**PLOTLY_TEMPLATE["layout"], height=350)
    fig_pie.update_traces(textposition="inside", textinfo="percent+label")
    
    return html.Div([
        section_title("Análisis de Portafolios", ICONS["portfolio"]),
        
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig_bar, config=CHART_CONFIG), md=8),
            dbc.Col(dcc.Graph(figure=fig_pie, config=CHART_CONFIG), md=4),
        ], className="mb-4 g-3"),
        
        section_title("Tabla Comparativa de Perfiles", ICONS["chart"]),
        html.Div(table_portf, style={"overflowX": "auto"}),
    ], style={"padding": "24px"})

def page_sensibilidad():
    """Página de análisis de sensibilidad y Monte Carlo."""
    df_mc = DATA["montecarlo"]
    
    # Distribución Monte Carlo
    fig_hist = go.Figure()
    fig_hist.add_trace(go.Histogram(
        x=df_mc["roi_simulado"],
        nbinsx=60,
        marker_color=COLORS["accent"],
        opacity=0.85,
        name="ROI Simulado",
    ))
    
    p5 = np.percentile(df_mc["roi_simulado"], 5)
    p50 = np.percentile(df_mc["roi_simulado"], 50)
    p95 = np.percentile(df_mc["roi_simulado"], 95)
    
    for val, label, col in [(p5, "P5", COLORS["red"]), (p50, "P50", COLORS["accent4"]), (p95, "P95", COLORS["green"])]:
        fig_hist.add_vline(
            x=val,
            line_dash="dash",
            line_color=col,
            annotation_text=f"{label}: {val:.2f}",
            annotation_font_color=col,
            annotation_position="top",
        )
    
    fig_hist.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title="Distribución ROI — Monte Carlo (n=2,000 iteraciones)",
        xaxis_title="ROI Simulado",
        yaxis_title="Frecuencia",
        height=340,
    )
    
    # Tornado chart
    variables = ["Factor de Venta", "Margen Bruto", "Precio Compra",
                 "Score Demanda", "Tipo de Cambio", "Costo Logístico"]
    impacto_neg = [-0.18, -0.12, -0.09, -0.07, -0.05, -0.04]
    impacto_pos = [0.21, 0.14, 0.10, 0.08, 0.06, 0.05]
    
    fig_tornado = go.Figure()
    fig_tornado.add_trace(go.Bar(
        y=variables,
        x=impacto_neg,
        orientation="h",
        marker_color=COLORS["red"],
        name="Impacto Negativo (-1σ)",
    ))
    fig_tornado.add_trace(go.Bar(
        y=variables,
        x=impacto_pos,
        orientation="h",
        marker_color=COLORS["green"],
        name="Impacto Positivo (+1σ)",
    ))
    fig_tornado.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        barmode="overlay",
        title="Tornado Chart — Análisis de Sensibilidad",
        xaxis_title="Δ ROI",
        height=340,
    )
    
    # Scatter factor_venta vs roi
    fig_scatter = px.scatter(
        df_mc.sample(500, random_state=1),
        x="factor_venta",
        y="roi_simulado",
        color="margen",
        color_continuous_scale=["#e0e0e0", COLORS["accent"]],
        labels={"factor_venta": "Factor de Venta", "roi_simulado": "ROI Simulado"},
        title="Factor de Venta vs ROI (muestra n=500)",
        opacity=0.7,
    )
    fig_scatter.update_layout(**PLOTLY_TEMPLATE["layout"], height=340)
    
    # Tabla de estadísticas
    stats_mc = [
        ("Media ROI", f"{df_mc['roi_simulado'].mean():.3f}", COLORS["accent"]),
        ("Desv. Est.", f"{df_mc['roi_simulado'].std():.3f}", COLORS["text"]),
        ("P5", f"{p5:.3f}", COLORS["red"]),
        ("P50 (Mediana)", f"{p50:.3f}", COLORS["accent4"]),
        ("P95", f"{p95:.3f}", COLORS["green"]),
        ("Prob. ROI > 0", f"{(df_mc['roi_simulado'] > 0).mean():.1%}", COLORS["green"]),
    ]
    
    table_stats = html.Table([
        html.Tr([
            html.Td(html.B(label), style={"padding": "8px", "borderBottom": f"1px solid {COLORS['border']}"}),
            html.Td(valor, style={"padding": "8px", "color": col, "fontWeight": 600, "borderBottom": f"1px solid {COLORS['border']}", "textAlign": "right"}),
        ])
        for label, valor, col in stats_mc
    ], style={"width": "100%", "color": COLORS["text"], "fontSize": "0.9rem", "borderCollapse": "collapse"})
    
    return html.Div([
        section_title("Análisis de Sensibilidad & Monte Carlo", ICONS["sensitivity"]),
        
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig_hist, config=CHART_CONFIG), md=6),
            dbc.Col(dcc.Graph(figure=fig_tornado, config=CHART_CONFIG), md=6),
        ], className="mb-4 g-3"),
        
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig_scatter, config=CHART_CONFIG), md=8),
            dbc.Col([
                section_title("Estadísticas MC", ICONS["chart"]),
                html.Div(table_stats, style={"padding": "12px"}),
            ], md=4),
        ], className="g-3"),
    ], style={"padding": "24px"})

def page_pareto():
    """Página del frente de Pareto NSGA-III original (4 objetivos)."""
    df_pareto = DATA["pareto"]
    
    if len(df_pareto) == 0:
        return html.Div([
            section_title("Frente de Pareto NSGA-III", ICONS["pareto"]),
            dbc.Alert("⚠️ No hay datos de Pareto disponibles.",
                     color="warning", style={"margin": "20px"}),
        ], style={"padding": "24px"})
    
    # Visualización 3D
    fig3d = px.scatter_3d(
        df_pareto,
        x="roi",
        y="riesgo",
        z="diversificacion",
        color="hhi",
        size="inversion_usd",
        color_continuous_scale=["#e0e0e0", COLORS["accent"]],
        labels={"roi": "ROI", "riesgo": "Riesgo", "diversificacion": "Diversificación", "hhi": "HHI"},
        title="Frente de Pareto NSGA-III — 4 Objetivos (3D proyección)",
        hover_data=["inversion_usd"],
    )
    fig3d.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        scene=dict(
            xaxis=dict(backgroundcolor=COLORS["bg"], gridcolor=COLORS["border"], title="ROI"),
            yaxis=dict(backgroundcolor=COLORS["bg"], gridcolor=COLORS["border"], title="Riesgo"),
            zaxis=dict(backgroundcolor=COLORS["bg"], gridcolor=COLORS["border"], title="Diversificación"),
        ),
        height=500,
    )
    
    # Visualización 2D
    fig2d = px.scatter(
        df_pareto,
        x="roi",
        y="riesgo",
        color="diversificacion",
        size="inversion_usd",
        color_continuous_scale=["#e0e0e0", COLORS["accent"]],
        labels={"roi": "ROI", "riesgo": "Riesgo", "diversificacion": "Diversificación"},
        title="Frente de Pareto — ROI vs Riesgo (2D)",
    )
    fig2d.update_layout(**PLOTLY_TEMPLATE["layout"], height=380)
    
    return html.Div([
        section_title("Frente de Pareto — NSGA-III Original", ICONS["pareto"]),
        
        dbc.Alert([
            html.B("⚙️ Configuración NSGA-III Original: "),
            "Generaciones: 150 · Población: 200 · Evaluaciones: 30,000 · ",
            "Soluciones no-dominadas: 75 · Objetivos: 4"
        ], color="info", style={
            "background": COLORS["card"],
            "border": f"2px solid {COLORS['accent2']}",
            "color": COLORS["text"],
            "fontSize": "0.85rem",
            "marginBottom": "20px",
        }),
        
        dcc.Graph(figure=fig3d, config=CHART_CONFIG),
        
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig2d, config=CHART_CONFIG), md=12),
        ], className="mt-3"),
    ], style={"padding": "24px"})

def page_competitividad():
    """Página de análisis de competitividad de precios."""
    df_precios = DATA["precios"]
    
    if len(df_precios) == 0:
        return html.Div([
            section_title("Análisis de Competitividad", ICONS["competitive"]),
            dbc.Alert("⚠️ No hay datos de precios disponibles.",
                     color="warning", style={"margin": "20px"}),
        ], style={"padding": "24px"})
    
    # Box plot precios por fuente
    fig_box = px.box(
        df_precios,
        x="fuente",
        y="precio_usd",
        color="fuente",
        color_discrete_sequence=PALETTE_CATEGORICAL,
        title="Distribución de Precios por Fuente",
        labels={"fuente": "Fuente", "precio_usd": "Precio (USD)"},
    )
    fig_box.update_layout(**PLOTLY_TEMPLATE["layout"], height=360, showlegend=False)
    
    # Heatmap brecha de precios
    if "producto" in df_precios.columns:
        pivot = df_precios.pivot_table(
            values="precio_usd",
            index="producto",
            columns="fuente",
            aggfunc="mean"
        ).fillna(0)
        
        fig_heat = px.imshow(
            pivot,
            color_continuous_scale=["#e0e0e0", COLORS["accent3"], COLORS["accent"]],
            title="Heatmap de Precios Promedio (USD) por Producto y Fuente",
            labels={"color": "Precio USD"},
            aspect="auto",
        )
        fig_heat.update_layout(**PLOTLY_TEMPLATE["layout"], height=360)
    else:
        fig_heat = go.Figure()
        fig_heat.update_layout(**PLOTLY_TEMPLATE["layout"],
                               title="Sin datos de producto disponibles", height=360)
    
    # Cálculo de brecha
    int_src = ["Amazon", "eBay", "AliExpress"]
    loc_src = ["Coolbox", "Falabella", "Hiraoka"]
    
    if "fuente" in df_precios.columns:
        precio_int = df_precios[df_precios["fuente"].isin(int_src)]["precio_usd"].median()
        precio_loc = df_precios[df_precios["fuente"].isin(loc_src)]["precio_usd"].median()
        brecha = (precio_loc - precio_int) / precio_int * 100 if precio_int > 0 else 0
    else:
        precio_int, precio_loc, brecha = 185, 204, 10.1
    
    return html.Div([
        section_title("Análisis de Competitividad de Precios", ICONS["competitive"]),
        
        dbc.Row([
            dbc.Col(kpi_card("Precio Mediano Internacional",
                             f"${precio_int:.0f} USD",
                             "Amazon · eBay · AliExpress",
                             COLORS["accent2"], "🌐"), md=4),
            dbc.Col(kpi_card("Precio Mediano Local",
                             f"${precio_loc:.0f} USD",
                             "Coolbox · Falabella · Hiraoka",
                             COLORS["accent4"], "🏪"), md=4),
            dbc.Col(kpi_card("Brecha de Precio",
                             f"+{brecha:.1f}%",
                             "Local vs Internacional",
                             COLORS["accent3"] if brecha > 0 else COLORS["green"], "📊"), md=4),
        ], className="mb-4 g-3"),
        
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig_box, config=CHART_CONFIG), md=6),
            dbc.Col(dcc.Graph(figure=fig_heat, config=CHART_CONFIG), md=6),
        ], className="g-3"),
    ], style={"padding": "24px"})

def page_ablacion():
    """Página de ablación de modelos de predicción."""
    df_ablacion = DATA["ablacion"]
    
    # Gráfico de métricas
    fig_mae = go.Figure()
    palette = [COLORS["text_dim"], COLORS["accent2"], COLORS["accent4"],
               COLORS["purple"], COLORS["accent"]]
    
    for (_, row), col in zip(df_ablacion.iterrows(), palette):
        fig_mae.add_trace(go.Bar(
            name=row["modelo"],
            x=["MAE", "RMSE", "MAPE (%)", "SMAPE (%)"],
            y=[row["mae"], row["rmse"], row["mape_pct"] / 100, row["smape_pct"] / 100],
            marker_color=col,
        ))
    
    fig_mae.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        barmode="group",
        title="Métricas de Error por Modelo",
        height=360,
    )
    
    # Radar de modelos
    cats_abl = ["Precisión", "Velocidad", "Escalabilidad", "Interpretabilidad", "Series Cortas"]
    scores = {
        "Baseline": [0.30, 0.99, 0.90, 0.99, 0.50],
        "LightGBM": [0.75, 0.90, 0.85, 0.80, 0.70],
        "XGBoost": [0.72, 0.88, 0.83, 0.75, 0.68],
        "TFT": [0.88, 0.40, 0.60, 0.45, 0.75],
        "N-BEATS": [0.92, 0.50, 0.70, 0.55, 0.95],
    }
    
    fig_rad = go.Figure()
    for (model, vals), col in zip(scores.items(), palette):
        fig_rad.add_trace(go.Scatterpolar(
            r=vals + [vals[0]],
            theta=cats_abl + [cats_abl[0]],
            fill="toself",
            name=model,
            line=dict(color=col, width=2),
            opacity=0.75,
        ))
    
    fig_rad.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        polar=dict(
            bgcolor=COLORS["bg"],
            radialaxis=dict(visible=True, range=[0, 1],
                            gridcolor=COLORS["border"], color=COLORS["text_dim"]),
            angularaxis=dict(gridcolor=COLORS["border"]),
        ),
        title="Radar de Capacidades por Modelo",
        height=400,
    )
    
    # Tabla de métricas
    table_ablacion = dbc.Table([
        html.Thead(html.Tr([
            html.Th("Modelo", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("MAE", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("RMSE", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("MAPE (%)", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("SMAPE (%)", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("Tiempo (s)", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("Parámetros (k)", style={"color": COLORS["accent"], "fontWeight": 700}),
        ], style={"background": COLORS["card"], "borderBottom": f"2px solid {COLORS['border']}"})),
        html.Tbody([
            html.Tr([
                html.Td(html.B(row["modelo"],
                        style={"color": COLORS["accent"] if row["modelo"] == "N-BEATS" else COLORS["text"]})),
                html.Td(f"{row['mae']:.3f}"),
                html.Td(f"{row['rmse']:.3f}"),
                html.Td(f"{row['mape_pct']:.1f}%"),
                html.Td(f"{row['smape_pct']:.1f}%"),
                html.Td(f"{row['tiempo_s']:.1f}"),
                html.Td(f"{row['params_k']}"),
            ], style={"borderBottom": f"1px solid {COLORS['border']}"})
            for _, row in df_ablacion.iterrows()
        ])
    ], bordered=True, hover=True, responsive=True, size="sm",
       style={"color": COLORS["text"], "fontSize": "0.85rem"})
    
    return html.Div([
        section_title("Ablación de Modelos de Predicción", ICONS["ablation"]),
        
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig_mae, config=CHART_CONFIG), md=7),
            dbc.Col(dcc.Graph(figure=fig_rad, config=CHART_CONFIG), md=5),
        ], className="mb-4 g-3"),
        
        section_title("Tabla de Métricas Completa", ICONS["chart"]),
        html.Div(table_ablacion, style={"overflowX": "auto", "marginBottom": "20px"}),
        
        dbc.Alert([
            html.B("✅ Modelo Seleccionado: N-BEATS "),
            html.Br(),
            "(neuralforecast · ICLR 2020) — Mejor MAPE/SMAPE con series cortas (30–60 obs). ",
            "Validación: Conformal Prediction para intervalos de confianza calibrados."
        ], color="success", style={
            "background": "#f0fdf4",
            "border": f"2px solid {COLORS['green']}",
            "color": COLORS["text"],
            "fontSize": "0.85rem",
        }),
    ], style={"padding": "24px"})

def page_pipeline():
    """Página de pipeline de datos y dataset master."""
    
    # Pasos del pipeline
    pipeline_steps = [
        ("1. Scraping", "Coolbox · Falabella · Hiraoka\nAmazon · eBay · AliExpress",
         COLORS["accent2"]),
        ("2. Limpieza", "Normalización · Deduplicación\nImputación de valores faltantes",
         COLORS["accent4"]),
        ("3. Features", "Score demanda · Brecha precios\nFactor de venta · Margen bruto",
         COLORS["purple"]),
        ("4. NSGA-III", "Optimización multiobjetivo\n200 gen · 210 pop · 7 objetivos",
         COLORS["accent"]),
        ("5. Selección", "Frente de Pareto · 24 soluciones\nPerfiles C/M/A",
         COLORS["green"]),
        ("6. Dashboard", "HDS-ROI v6.0\nMonitoreo y análisis interactivo",
         COLORS["accent3"]),
    ]
    
    pipeline_cards = dbc.Row([
        dbc.Col(dbc.Card([
            dbc.CardBody([
                html.H6(step, style={"color": col, "fontWeight": 700, "fontSize": "0.9rem", "marginBottom": "8px"}),
                html.P(desc, style={"color": COLORS["text_dim"], "fontSize": "0.75rem",
                                    "whiteSpace": "pre-line", "marginBottom": "0", "lineHeight": "1.4"}),
            ])
        ], style={"background": COLORS["bg"], "border": f"2px solid {col}",
                  "borderRadius": "8px", "height": "100%", "transition": "all 0.3s ease"}), md=2)
        for step, desc, col in pipeline_steps
    ], className="mb-4 g-2")
    
    # Dataset columns
    dataset_cols = [
        ("sku_id", "ID único del producto"),
        ("nombre", "Nombre comercial"),
        ("categoria", "Categoría hardware"),
        ("precio_compra_usd", "Precio de compra internacional"),
        ("precio_venta_usd", "Precio de venta estimado local"),
        ("margen_bruto", "Margen bruto (%)"),
        ("factor_venta", "Probabilidad de venta en período"),
        ("score_demanda", "Score de demanda (0–1)"),
        ("roi_sku", "ROI individual del SKU"),
        ("peso_portafolio", "Peso en portafolio optimizado"),
        ("hhi_contribucion", "Contribución al índice HHI"),
        ("disponible_amazon", "Disponibilidad en Amazon"),
        ("disponible_ebay", "Disponibilidad en eBay"),
        ("disponible_aliexpress", "Disponibilidad en AliExpress"),
        ("precio_coolbox", "Precio Coolbox (local)"),
        ("precio_falabella", "Precio Falabella (local)"),
        ("precio_hiraoka", "Precio Hiraoka (local)"),
        ("brecha_precio_pct", "Brecha precio local vs internacional"),
        ("fecha_scraping", "Fecha de extracción de datos"),
        ("tendencia_google", "Índice Google Trends (proxy)"),
        ("reviews_amazon", "Número de reseñas Amazon"),
        ("rating_promedio", "Rating promedio (1–5)"),
        ("tiempo_envio_dias", "Tiempo de envío estimado"),
        ("costo_logistico_usd", "Costo logístico por unidad"),
        ("tipo_cambio_pen", "Tipo de cambio PEN/USD"),
        ("impuesto_importacion", "Tasa de impuesto importación"),
        ("categoria_riesgo", "Categoría de riesgo (1–5)"),
        ("flag_seleccionado", "Flag de selección en portafolio"),
    ]
    
    table_ds = dbc.Table([
        html.Thead(html.Tr([
            html.Th("#", style={"color": COLORS["accent"], "fontWeight": 700, "width": "5%"}),
            html.Th("Columna", style={"color": COLORS["accent"], "fontWeight": 700}),
            html.Th("Descripción", style={"color": COLORS["accent"], "fontWeight": 700}),
        ], style={"background": COLORS["card"], "borderBottom": f"2px solid {COLORS['border']}"})),
        html.Tbody([
            html.Tr([
                html.Td(str(i+1), style={"color": COLORS["text_dim"], "fontWeight": 600}),
                html.Td(html.Code(col, style={"color": COLORS["accent2"], "fontSize": "0.8rem"})),
                html.Td(desc, style={"fontSize": "0.85rem"}),
            ], style={"borderBottom": f"1px solid {COLORS['border']}"})
            for i, (col, desc) in enumerate(dataset_cols)
        ])
    ], bordered=True, hover=True, responsive=True, size="sm",
       style={"color": COLORS["text"]})
    
    return html.Div([
        section_title("Pipeline de Datos & Dataset MASTER", ICONS["pipeline"]),
        
        pipeline_cards,
        
        html.Hr(style={"borderColor": COLORS["border"], "margin": "30px 0"}),
        
        section_title(f"Dataset MASTER — {len(dataset_cols)} columnas", ICONS["data"]),
        html.Div(table_ds, style={"overflowX": "auto"}),
    ], style={"padding": "24px"})

# ─────────────────────────────────────────────
# 7. LAYOUT PRINCIPAL
# ─────────────────────────────────────────────

app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    
    sidebar,
    
    html.Div(id="page-content", style=CONTENT_STYLE),
    
    # CSS personalizado
    html.Div([
        dcc.Markdown(f"""
        <style>
        .nav-link-custom {{
            transition: all 0.2s ease !important;
        }}
        
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
        
        table {{
            font-size: 0.85rem;
        }}
        
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
        
        tbody tr:hover {{
            background-color: {COLORS["card"]} !important;
        }}
        
        .card {{
            border: 1px solid {COLORS["border"]} !important;
            background-color: {COLORS["bg"]} !important;
            border-radius: 8px !important;
            transition: all 0.3s ease !important;
        }}
        
        .card:hover {{
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12) !important;
            border-color: {COLORS["accent"]} !important;
        }}
        
        .alert {{
            border-radius: 6px !important;
            border-left: 4px solid !important;
        }}
        
        .alert-info {{
            border-left-color: {COLORS["accent2"]} !important;
            background-color: {COLORS["accent2"]}11 !important;
        }}
        
        .alert-success {{
            border-left-color: {COLORS["green"]} !important;
            background-color: {COLORS["green"]}11 !important;
        }}
        
        .alert-warning {{
            border-left-color: {COLORS["accent3"]} !important;
            background-color: {COLORS["accent3"]}11 !important;
        }}
        
        h1, h2, h3, h4, h5, h6 {{
            color: {COLORS["text"]} !important;
        }}
        
        p {{
            color: {COLORS["text"]} !important;
        }}
        
        body {{
            background-color: #f5f7fa !important;
        }}
        </style>
        """, dangerously_allow_html=True)
    ], style={"display": "none"}),
], style={"backgroundColor": "#f5f7fa", "minHeight": "100vh"})

# ─────────────────────────────────────────────
# 8. CALLBACKS - ENRUTAMIENTO
# ─────────────────────────────────────────────

@app.callback(
    Output("page-content", "children"),
    Input("url", "pathname"),
)
def display_page(pathname):
    """Enrutamiento de páginas."""
    if pathname == "/":
        return page_resumen()
    elif pathname == "/simulador":
        return page_simulador()
    elif pathname == "/oe9":
        return page_oe9()
    elif pathname == "/datos":
        return page_datos()
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
            html.H3("404 — Página no encontrada", style={"color": COLORS["text"], "padding": "24px"}),
            html.P("La página que buscas no existe.", style={"color": COLORS["text_dim"], "padding": "0 24px"}),
        ])

# ─────────────────────────────────────────────
# 9. CALLBACK - SIMULADOR
# ─────────────────────────────────────────────

@app.callback(
    Output("simulador-resultados", "children"),
    Input("btn-simular", "n_clicks"),
    [State("input-presupuesto", "value"), State("dropdown-modelo", "value")],
    prevent_initial_call=False,
)
def actualizar_simulador(n_clicks, presupuesto, modelo_key):
    """Actualiza resultados del simulador."""
    if not presupuesto or presupuesto < 1000:
        return dbc.Alert("⚠️ Presupuesto mínimo: $1,000", color="warning")
    
    recomendaciones = generar_recomendaciones()
    
    if not recomendaciones:
        return dbc.Alert("⚠️ No hay datos disponibles", color="warning")
    
    datos = recomendaciones.get(modelo_key, recomendaciones["balanceado"])
    
    resultado = calcular_simulador(presupuesto, datos["roi"], datos["capital"])
    
    if not resultado:
        return dbc.Alert("❌ Error en cálculo", color="danger")
    
    return dbc.Row([
        dbc.Col(kpi_card("Unidades a Comprar", f"{resultado['unidades']:,}",
                         "Cantidad", COLORS["accent"], "📦"), md=3),
        dbc.Col(kpi_card("Capital Total", f"${resultado['capital_total']:,.0f}",
                         "Inversión", COLORS["accent2"], "💰"), md=3),
        dbc.Col(kpi_card("Ganancia Total", f"${resultado['ganancia_total']:,.0f}",
                         "Retorno esperado", COLORS["green"], "📈"), md=3),
        dbc.Col(kpi_card("ROI Total", f"+{resultado['roi_total']:.1f}%",
                         "Retorno sobre inversión", COLORS["accent4"], "🎯"), md=3),
    ], className="mt-4 g-3")

# ─────────────────────────────────────────────
# 10. EJECUCIÓN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*80)
    print("  🚀 HDS-ROI v6.0 — Motor de Decisión Inteligente")
    print("="*80)
    print(f"  🌐 URL: http://{APP_CONFIG['host']}:{APP_CONFIG['port']}")
    print(f"  🎯 NUEVO: Motor de Decisión + Simulador Interactivo")
    print(f"  📊 Tema: Blanco Profesional")
    print(f"  📈 Páginas: 11 (Motor + Simulador + 9 análisis)")
    print(f"  ⚙️  Datos: {len(DATA['oe9_pareto'])} soluciones Pareto · {len(DATA['feature_matrix'])} SKUs")
    print(f"  ✅ Estado: Sistema Operativo")
    print("="*80)
    print("  Presiona Ctrl+C para detener\n")
    
    app.run(
        debug=APP_CONFIG["debug"],
        host=APP_CONFIG["host"],
        port=APP_CONFIG["port"],
        threaded=True,
    )

