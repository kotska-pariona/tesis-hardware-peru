# pages/motor_decision.py - Motor de Decisión (Página Principal)

import dash
from dash import html, dcc, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

from config_v6 import COLORS, CARD_STYLE, CONTENT_STYLE
from components_v6 import (
    crear_header, crear_kpi_card, crear_tabla_simple,
    crear_seccion, crear_badge, crear_alerta
)
from utils_v6 import (
    get_top_modelos, get_mejor_roi, get_mejor_balance,
    get_mejor_eficiencia, formatear_moneda, formatear_porcentaje,
    clasificar_riesgo
)

# Registrar página
dash.register_page(__name__, path="/")

# ============ LAYOUT ============

layout = html.Div([
    # ---- ENCABEZADO ----
    crear_header(
        "🎯 Motor de Decisión",
        "Recomendación inteligente de modelos para compra"
    ),
    
    # ---- ALERTAS ----
    html.Div([
        crear_alerta(
            "info",
            "📊 Análisis Basado en 24 Soluciones Pareto",
            "Estos datos provienen del análisis NSGA-III con 200 generaciones y 200 individuos por generación."
        ),
    ]),
    
    # ---- FILA 1: KPIs PRINCIPALES ----
    dbc.Row([
        dbc.Col([
            crear_kpi_card(
                "🔥 MEJOR ROI ABSOLUTO",
                f"+{get_mejor_roi()['roi']}%",
                "📈",
                subtitulo=f"Modelo: {get_mejor_roi()['modelo']}"
            ),
        ], md=4),
        dbc.Col([
            crear_kpi_card(
                "⚖️ MEJOR BALANCE",
                f"+{get_mejor_balance()['roi']}%",
                "⚙️",
                subtitulo=f"Riesgo: {get_mejor_balance()['riesgo']}"
            ),
        ], md=4),
        dbc.Col([
            crear_kpi_card(
                "💎 MEJOR EFICIENCIA",
                f"{(get_mejor_eficiencia()['roi'] / (get_mejor_eficiencia()['capital'] + 1)):.2f}x",
                "💰",
                subtitulo=f"ROI/Capital"
            ),
        ], md=4),
    ], style={"marginBottom": "30px"}),
    
    # ---- FILA 2: TABLA TOP 5 ----
    html.Div([
        crear_seccion(
            "📊 TOP 5 MODELOS CON DECISIÓN",
            id="tabla-top5-container",
            icono="📋"
        ),
    ], style={"marginBottom": "30px"}),
    
    # ---- FILA 3: GRÁFICOS ----
    dbc.Row([
        dbc.Col([
            dcc.Graph(id="scatter-roi-riesgo"),
        ], md=6),
        dbc.Col([
            dcc.Graph(id="pie-distribucion"),
        ], md=6),
    ], style={"marginBottom": "30px"}),
    
    # ---- FILA 4: DETALLES ----
    dbc.Row([
        dbc.Col([
            html.Div([
                html.H6("📌 DETALLES MEJOR ROI", style={"fontWeight": "700", "marginBottom": "15px"}),
                html.Div(id="detalles-mejor-roi"),
            ], style=CARD_STYLE),
        ], md=4),
        dbc.Col([
            html.Div([
                html.H6("📌 DETALLES MEJOR BALANCE", style={"fontWeight": "700", "marginBottom": "15px"}),
                html.Div(id="detalles-mejor-balance"),
            ], style=CARD_STYLE),
        ], md=4),
        dbc.Col([
            html.Div([
                html.H6("📌 DETALLES MEJOR EFICIENCIA", style={"fontWeight": "700", "marginBottom": "15px"}),
                html.Div(id="detalles-mejor-eficiencia"),
            ], style=CARD_STYLE),
        ], md=4),
    ]),
], style=CONTENT_STYLE)

# ============ CALLBACKS ============

@callback(
    Output("tabla-top5-container", "children"),
    Input("tabla-top5-container", "id")
)
def actualizar_tabla_top5(_):
    modelos = get_top_modelos()[:5]
    
    datos = []
    for modelo in modelos:
        datos.append({
            "Modelo": modelo["modelo"],
            "ROI (%)": f"+{modelo['roi']}%",
            "Capital ($)": f"${modelo['capital']:,}",
            "Ganancia ($)": f"${modelo['ganancia']:,}",
            "Riesgo (r_j)": f"{modelo['r_j']:.4f}",
            "Nivel": clasificar_riesgo(modelo["r_j"]),
            "Decisión": "✅ COMPRAR" if modelo["roi"] > 50 else "⚠️ REVISAR",
        })
    
    df = pd.DataFrame(datos)
    
    return html.Div([
        dbc.Table.from_dataframe(
            df,
            striped=True,
            bordered=True,
            hover=True,
            responsive=True,
            style={"fontSize": "12px"}
        ),
    ])

@callback(
    Output("scatter-roi-riesgo", "figure"),
    Input("scatter-roi-riesgo", "id")
)
def actualizar_scatter(_):
    modelos = get_top_modelos()
    
    df = pd.DataFrame(modelos)
    
    fig = px.scatter(
        df,
        x="r_j",
        y="roi",
        size="capital",
        color="riesgo",
        hover_name="modelo",
        hover_data={
            "roi": ":.1f",
            "r_j": ":.4f",
            "capital": ":$,.0f",
            "ganancia": ":$,.0f",
            "riesgo": True,
        },
        title="ROI vs Riesgo (Tamaño = Capital Invertido)",
        labels={
            "r_j": "Riesgo de Obsolescencia (r_j)",
            "roi": "ROI (%)",
        },
        color_discrete_map={
            "BAJO": COLORS["accent2"],
            "MEDIO": COLORS["warning"],
            "ALTO": COLORS["danger"],
        },
    )
    
    fig.update_layout(
        template="plotly_white",
        hovermode="closest",
        height=400,
        font={"size": 11},
    )
    
    return fig

@callback(
    Output("pie-distribucion", "figure"),
    Input("pie-distribucion", "id")
)
def actualizar_pie(_):
    modelos = get_top_modelos()
    
    distribucion = {}
    for modelo in modelos:
        riesgo = modelo["riesgo"]
        distribucion[riesgo] = distribucion.get(riesgo, 0) + 1
    
    fig = go.Figure(data=[go.Pie(
        labels=list(distribucion.keys()),
        values=list(distribucion.values()),
        marker=dict(
            colors=[
                COLORS["accent2"] if "BAJO" in k else (
                    COLORS["warning"] if "MEDIO" in k else COLORS["danger"]
                )
                for k in distribucion.keys()
            ]
        ),
        textposition="inside",
        textinfo="label+percent",
    )])
    
    fig.update_layout(
        title="Distribución de Modelos por Nivel de Riesgo",
        template="plotly_white",
        height=400,
    )
    
    return fig

@callback(
    Output("detalles-mejor-roi", "children"),
    Input("detalles-mejor-roi", "id")
)
def actualizar_detalles_roi(_):
    mejor = get_mejor_roi()
    
    return html.Div([
        html.Div([
            html.Span("Modelo:", style={"fontWeight": "600"}),
            html.Span(mejor["modelo"], style={"marginLeft": "10px"}),
        ], style={"marginBottom": "8px"}),
        html.Div([
            html.Span("ROI:", style={"fontWeight": "600"}),
            html.Span(f"+{mejor['roi']}%", style={"marginLeft": "10px", "color": COLORS["accent2"]}),
        ], style={"marginBottom": "8px"}),
        html.Div([
            html.Span("Capital:", style={"fontWeight": "600"}),
            html.Span(f"${mejor['capital']:,}", style={"marginLeft": "10px"}),
        ], style={"marginBottom": "8px"}),
        html.Div([
            html.Span("Ganancia:", style={"fontWeight": "600"}),
            html.Span(f"${mejor['ganancia']:,}", style={"marginLeft": "10px"}),
        ], style={"marginBottom": "8px"}),
        html.Div([
            html.Span("Riesgo:", style={"fontWeight": "600"}),
            html.Span(mejor["riesgo"], style={"marginLeft": "10px"}),
        ], style={"marginBottom": "8px"}),
        html.Hr(style={"margin": "10px 0"}),
        html.P(
            "Para inversionistas con alta tolerancia al riesgo",
            style={"fontSize": "11px", "color": COLORS["text_light"], "fontStyle": "italic"}
        ),
    ])

@callback(
    Output("detalles-mejor-balance", "children"),
    Input("detalles-mejor-balance", "id")
)
def actualizar_detalles_balance(_):
    mejor = get_mejor_balance()
    
    return html.Div([
        html.Div([
            html.Span("Modelo:", style={"fontWeight": "600"}),
            html.Span(mejor["modelo"], style={"marginLeft": "10px"}),
        ], style={"marginBottom": "8px"}),
        html.Div([
            html.Span("ROI:", style={"fontWeight": "600"}),
            html.Span(f"+{mejor['roi']}%", style={"marginLeft": "10px", "color": COLORS["accent2"]}),
        ], style={"marginBottom": "8px"}),
        html.Div([
            html.Span("Capital:", style={"fontWeight": "600"}),
            html.Span(f"${mejor['capital']:,}", style={"marginLeft": "10px"}),
        ], style={"marginBottom": "8px"}),
        html.Div([
            html.Span("Ganancia:", style={"fontWeight": "600"}),
            html.Span(f"${mejor['ganancia']:,}", style={"marginLeft": "10px"}),
        ], style={"marginBottom": "8px"}),
        html.Div([
            html.Span("Riesgo:", style={"fontWeight": "600"}),
            html.Span(mejor["riesgo"], style={"marginLeft": "10px"}),
        ], style={"marginBottom": "8px"}),
        html.Hr(style={"margin": "10px 0"}),
        html.P(
            "Recomendado para la mayoría de inversionistas",
            style={"fontSize": "11px", "color": COLORS["text_light"], "fontStyle": "italic"}
        ),
    ])

@callback(
    Output("detalles-mejor-eficiencia", "children"),
    Input("detalles-mejor-eficiencia", "id")
)
def actualizar_detalles_eficiencia(_):
    mejor = get_mejor_eficiencia()
    
    return html.Div([
        html.Div([
            html.Span("Modelo:", style={"fontWeight": "600"}),
            html.Span(mejor["modelo"], style={"marginLeft": "10px"}),
        ], style={"marginBottom": "8px"}),
        html.Div([
            html.Span("ROI:", style={"fontWeight": "600"}),
            html.Span(f"+{mejor['roi']}%", style={"marginLeft": "10px", "color": COLORS["accent2"]}),
        ], style={"marginBottom": "8px"}),
        html.Div([
            html.Span("Capital:", style={"fontWeight": "600"}),
            html.Span(f"${mejor['capital']:,}", style={"marginLeft": "10px"}),
        ], style={"marginBottom": "8px"}),
        html.Div([
            html.Span("Ganancia:", style={"fontWeight": "600"}),
            html.Span(f"${mejor['ganancia']:,}", style={"marginLeft": "10px"}),
        ], style={"marginBottom": "8px"}),
        html.Div([
            html.Span("Riesgo:", style={"fontWeight": "600"}),
            html.Span(mejor["riesgo"], style={"marginLeft": "10px"}),
        ], style={"marginBottom": "8px"}),
        html.Hr(style={"margin": "10px 0"}),
        html.P(
            "Mejor relación ROI/Capital invertido",
            style={"fontSize": "11px", "color": COLORS["text_light"], "fontStyle": "italic"}
        ),
    ])
