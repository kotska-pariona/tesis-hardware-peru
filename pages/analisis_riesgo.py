# pages/analisis_riesgo.py - Análisis de Riesgo y Obsolescencia

import dash
from dash import html, dcc, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from config_v6 import COLORS, CARD_STYLE, CONTENT_STYLE
from components_v6 import (
    crear_header, crear_seccion, crear_alerta,
    crear_estadistica_fila, crear_badge
)
from utils_v6 import (
    get_top_modelos, generar_matriz_riesgo,
    clasificar_riesgo
)

dash.register_page(__name__, path="/riesgo")

layout = html.Div([
    crear_header(
        "⚠️ Análisis de Riesgo",
        "Matriz de Obsolescencia (r_j) vs ROI"
    ),
    
    crear_alerta(
        "warning",
        "📈 Métrica r_j (Riesgo de Obsolescencia)",
        "Valores cercanos a 1.0 indican alto riesgo de obsolescencia. Valores cercanos a 0.0 indican modelos estables."
    ),
    
    # ---- FILA 1: INFORMACIÓN ----
    dbc.Row([
        dbc.Col([
            html.Div([
                html.H6("🟢 RIESGO BAJO", style={"fontWeight": "700", "marginBottom": "10px"}),
                html.P("r_j: 0.0 - 0.3", style={"fontSize": "12px", "marginBottom": "5px"}),
                html.P("Modelos estables y confiables", style={"fontSize": "11px", "color": COLORS["text_light"]}),
            ], style=CARD_STYLE),
        ], md=4),
        dbc.Col([
            html.Div([
                html.H6("🟡 RIESGO MEDIO", style={"fontWeight": "700", "marginBottom": "10px"}),
                html.P("r_j: 0.3 - 0.7", style={"fontSize": "12px", "marginBottom": "5px"}),
                html.P("Riesgo moderado, requiere monitoreo", style={"fontSize": "11px", "color": COLORS["text_light"]}),
            ], style=CARD_STYLE),
        ], md=4),
        dbc.Col([
            html.Div([
                html.H6("🔴 RIESGO ALTO", style={"fontWeight": "700", "marginBottom": "10px"}),
                html.P("r_j: 0.7 - 1.0", style={"fontSize": "12px", "marginBottom": "5px"}),
                html.P("Alto riesgo de obsolescencia", style={"fontSize": "11px", "color": COLORS["text_light"]}),
            ], style=CARD_STYLE),
        ], md=4),
    ], style={"marginBottom": "30px"}),
    
    # ---- FILA 2: GRÁFICOS ----
    dbc.Row([
        dbc.Col([
            dcc.Graph(id="scatter-riesgo-roi"),
        ], md=6),
        dbc.Col([
            dcc.Graph(id="histogram-rj"),
        ], md=6),
    ], style={"marginBottom": "30px"}),
    
    # ---- FILA 3: TABLA MATRIZ RIESGO ----
    html.Div([
        crear_seccion(
            "📊 MATRIZ DE RIESGO DETALLADA",
            id="tabla-riesgo-container",
            icono="📋"
        ),
    ], style={"marginBottom": "30px"}),
    
    # ---- FILA 4: RECOMENDACIONES ----
    html.Div([
        crear_seccion(
            "💡 RECOMENDACIONES POR NIVEL DE RIESGO",
            id="recomendaciones-riesgo-container",
            icono="🎯"
        ),
    ]),
], style=CONTENT_STYLE)

@callback(
    Output("scatter-riesgo-roi", "figure"),
    Input("scatter-riesgo-roi", "id")
)
def actualizar_scatter_riesgo(_):
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
        title="Matriz de Riesgo: r_j vs ROI",
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
    
    # Agregar líneas de referencia
    fig.add_vline(x=0.3, line_dash="dash", line_color=COLORS["text_light"], annotation_text="Límite Bajo-Medio")
    fig.add_vline(x=0.7, line_dash="dash", line_color=COLORS["text_light"], annotation_text="Límite Medio-Alto")
    
    fig.update_layout(
        template="plotly_white",
        height=400,
        hovermode="closest",
    )
    
    return fig

@callback(
    Output("histogram-rj", "figure"),
    Input("histogram-rj", "id")
)
def actualizar_histogram_rj(_):
    modelos = get_top_modelos()
    df = pd.DataFrame(modelos)
    
    fig = px.histogram(
        df,
        x="r_j",
        nbins=10,
        color="riesgo",
        title="Distribución de Riesgo (r_j)",
        labels={"r_j": "Riesgo de Obsolescencia (r_j)"},
        color_discrete_map={
            "BAJO": COLORS["accent2"],
            "MEDIO": COLORS["warning"],
            "ALTO": COLORS["danger"],
        },
    )
    
    fig.update_layout(
        template="plotly_white",
        height=400,
        hovermode="x unified",
    )
    
    return fig

@callback(
    Output("tabla-riesgo-container", "children"),
    Input("tabla-riesgo-container", "id")
)
def actualizar_tabla_riesgo(_):
    df = generar_matriz_riesgo()
    
    df_display = df.copy()
    df_display["ROI (%)"] = df_display["ROI (%)"].apply(lambda x: f"+{x:.1f}%")
    df_display["r_j"] = df_display["r_j"].apply(lambda x: f"{x:.4f}")
    df_display["Capital ($)"] = df_display["Capital ($)"].apply(lambda x: f"${x:,}")
    
    return html.Div([
        dbc.Table.from_dataframe(
            df_display,
            striped=True,
            bordered=True,
            hover=True,
            responsive=True,
            style={"fontSize": "12px"}
        ),
    ])

@callback(
    Output("recomendaciones-riesgo-container", "children"),
    Input("recomendaciones-riesgo-container", "id")
)
def actualizar_recomendaciones_riesgo(_):
    modelos = get_top_modelos()
    
    bajo = [m for m in modelos if m["riesgo"] == "BAJO"]
    medio = [m for m in modelos if m["riesgo"] == "MEDIO"]
    alto = [m for m in modelos if m["riesgo"] == "ALTO"]
    
    return html.Div([
        dbc.Row([
            dbc.Col([
                html.Div([
                    html.H6("🟢 RIESGO BAJO", style={"fontWeight": "700", "marginBottom": "10px"}),
                    html.Ul([
                        html.Li(f"{m['modelo']}: +{m['roi']}% ROI", style={"fontSize": "12px", "marginBottom": "5px"})
                        for m in bajo
                    ]),
                    html.Hr(style={"margin": "10px 0"}),
                    html.P(
                        "✅ Recomendado para inversiones conservadoras",
                        style={"fontSize": "11px", "color": COLORS["accent2"], "fontWeight": "600"}
                    ),
                ], style=CARD_STYLE),
            ], md=4),
            dbc.Col([
                html.Div([
                    html.H6("🟡 RIESGO MEDIO", style={"fontWeight": "700", "marginBottom": "10px"}),
                    html.Ul([
                        html.Li(f"{m['modelo']}: +{m['roi']}% ROI", style={"fontSize": "12px", "marginBottom": "5px"})
                        for m in medio
                    ]),
                    html.Hr(style={"margin": "10px 0"}),
                    html.P(
                        "⚠️ Requiere monitoreo constante",
                        style={"fontSize": "11px", "color": COLORS["warning"], "fontWeight": "600"}
                    ),
                ], style=CARD_STYLE),
            ], md=4),
            dbc.Col([
                html.Div([
                    html.H6("🔴 RIESGO ALTO", style={"fontWeight": "700", "marginBottom": "10px"}),
                    html.Ul([
                        html.Li(f"{m['modelo']}: +{m['roi']}% ROI", style={"fontSize": "12px", "marginBottom": "5px"})
                        for m in alto
                    ]),
                    html.Hr(style={"margin": "10px 0"}),
                    html.P(
                        "🔴 Solo para inversionistas agresivos",
                        style={"fontSize": "11px", "color": COLORS["danger"], "fontWeight": "600"}
                    ),
                ], style=CARD_STYLE),
            ], md=4),
        ]),
    ])
