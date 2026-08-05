# pages/decision_final.py - Página de Decisión Final y Recomendaciones

import dash
from dash import html, dcc, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd

from config_v6 import COLORS, CARD_STYLE, CONTENT_STYLE
from components_v6 import (
    crear_header, crear_seccion, crear_alerta,
    crear_recomendacion_box, crear_badge
)
from utils_v6 import generar_recomendaciones, get_top_modelos

dash.register_page(__name__, path="/decision-final")

layout = html.Div([
    crear_header(
        "🎯 Decisión Final",
        "3 Recomendaciones Principales de Compra"
    ),
    
    crear_alerta(
        "success",
        "✅ Análisis Completado",
        "Basado en 24 soluciones Pareto, 82 SKUs analizados y 40,000 evaluaciones de optimización."
    ),
    
    # ---- FILA 1: 3 RECOMENDACIONES ----
    dbc.Row([
        dbc.Col([
            html.Div(id="recomendacion-1"),
        ], md=4),
        dbc.Col([
            html.Div(id="recomendacion-2"),
        ], md=4),
        dbc.Col([
            html.Div(id="recomendacion-3"),
        ], md=4),
    ], style={"marginBottom": "30px"}),
    
    # ---- FILA 2: MATRIZ DECISIÓN ----
    html.Div([
        crear_seccion(
            "📊 MATRIZ DE DECISIÓN",
            id="matriz-decision-container",
            icono="🎯"
        ),
    ], style={"marginBottom": "30px"}),
    
    # ---- FILA 3: GRÁFICO COMPARATIVO ----
    dbc.Row([
        dbc.Col([
            dcc.Graph(id="radar-recomendaciones"),
        ], md=6),
        dbc.Col([
            dcc.Graph(id="heatmap-comparativa"),
        ], md=6),
    ], style={"marginBottom": "30px"}),
    
    # ---- FILA 4: PRÓXIMOS PASOS ----
    html.Div([
        crear_seccion(
            "📋 PRÓXIMOS PASOS",
            id="pasos-container",
            icono="✅"
        ),
    ]),
], style=CONTENT_STYLE)

@callback(
    [
        Output("recomendacion-1", "children"),
        Output("recomendacion-2", "children"),
        Output("recomendacion-3", "children"),
    ],
    Input("recomendacion-1", "id")
)
def actualizar_recomendaciones(_):
    recomendaciones = generar_recomendaciones()
    
    rec1 = crear_recomendacion_box(
        recomendaciones["opcion_1"]["titulo"],
        recomendaciones["opcion_1"]["modelo"],
        recomendaciones["opcion_1"]["roi"],
        recomendaciones["opcion_1"]["capital"],
        recomendaciones["opcion_1"]["ganancia"],
        recomendaciones["opcion_1"]["riesgo"],
        recomendaciones["opcion_1"]["para"],
    )
    
    rec2 = crear_recomendacion_box(
        recomendaciones["opcion_2"]["titulo"],
        recomendaciones["opcion_2"]["modelo"],
        recomendaciones["opcion_2"]["roi"],
        recomendaciones["opcion_2"]["capital"],
        recomendaciones["opcion_2"]["ganancia"],
        recomendaciones["opcion_2"]["riesgo"],
        recomendaciones["opcion_2"]["para"],
    )
    
    rec3 = crear_recomendacion_box(
        recomendaciones["opcion_3"]["titulo"],
        recomendaciones["opcion_3"]["modelo"],
        recomendaciones["opcion_3"]["roi"],
        recomendaciones["opcion_3"]["capital"],
        recomendaciones["opcion_3"]["ganancia"],
        recomendaciones["opcion_3"]["riesgo"],
        recomendaciones["opcion_3"]["para"],
    )
    
    return rec1, rec2, rec3

@callback(
    Output("matriz-decision-container", "children"),
    Input("matriz-decision-container", "id")
)
def actualizar_matriz_decision(_):
    modelos = get_top_modelos()[:5]
    
    datos = []
    for modelo in modelos:
        datos.append({
            "Modelo": modelo["modelo"],
            "ROI (%)": f"+{modelo['roi']:.1f}%",
            "Capital ($)": f"${modelo['capital']:,}",
            "Ganancia ($)": f"${modelo['ganancia']:,}",
            "Riesgo": modelo["riesgo"],
            "r_j": f"{modelo['r_j']:.4f}",
            "Recomendación": "🔥 COMPRAR AHORA" if modelo["roi"] > 60 else (
                "✅ COMPRAR" if modelo["roi"] > 50 else "⚠️ REVISAR"
            ),
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
    Output("radar-recomendaciones", "figure"),
    Input("radar-recomendaciones", "id")
)
def actualizar_radar(_):
    modelos = get_top_modelos()[:5]
    
    # Normalizar valores para el radar
    max_roi = max([m["roi"] for m in modelos])
    max_capital = max([m["capital"] for m in modelos])
    
    datos_radar = []
    for modelo in modelos:
        datos_radar.append({
            "Modelo": modelo["modelo"],
            "ROI (norm)": (modelo["roi"] / max_roi) * 100,
            "Capital (norm)": (modelo["capital"] / max_capital) * 100,
            "Ganancia (norm)": (modelo["ganancia"] / max([m["ganancia"] for m in modelos])) * 100,
        })
    
    fig = go.Figure()
    
    for dato in datos_radar:
        fig.add_trace(go.Scatterpolar(
            r=[dato["ROI (norm)"], dato["Capital (norm)"], dato["Ganancia (norm)"]],
            theta=["ROI", "Capital", "Ganancia"],
            fill="toself",
            name=dato["Modelo"],
        ))
    
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        showlegend=True,
        title="Comparativa Radar de Modelos",
        template="plotly_white",
        height=400,
    )
    
    return fig

@callback(
    Output("heatmap-comparativa", "figure"),
    Input("heatmap-comparativa", "id")
)
def actualizar_heatmap(_):
    modelos = get_top_modelos()[:5]
    
    # Crear matriz de comparación
    matriz = []
    modelos_nombres = []
    
    for modelo in modelos:
        modelos_nombres.append(modelo["modelo"])
        matriz.append([
            modelo["roi"],
            modelo["capital"] / 100,  # Escalar para visualización
            modelo["ganancia"] / 100,  # Escalar para visualización
            modelo["r_j"] * 100,  # Convertir a escala 0-100
        ])
    
    fig = go.Figure(data=go.Heatmap(
        z=matriz,
        x=["ROI (%)", "Capital (/100)", "Ganancia (/100)", "Riesgo (r_j x100)"],
        y=modelos_nombres,
        colorscale="Viridis",
        text=[[f"{v:.1f}" for v in fila] for fila in matriz],
        texttemplate="%{text}",
        textfont={"size": 10},
    ))
    
    fig.update_layout(
        title="Heatmap Comparativo de Modelos",
        template="plotly_white",
        height=400,
    )
    
    return fig

@callback(
    Output("pasos-container", "children"),
    Input("pasos-container", "id")
)
def actualizar_pasos(_):
    return html.Div([
        dbc.Row([
            dbc.Col([
                html.Div([
                    html.H6("1️⃣ SELECCIONAR MODELO", style={"fontWeight": "700", "marginBottom": "10px"}),
                    html.P(
                        "Elige entre las 3 opciones recomendadas según tu perfil de riesgo.",
                        style={"fontSize": "12px", "marginBottom": "10px"}
                    ),
                    html.Ul([
                        html.Li("Agresivo: Máximo ROI", style={"fontSize": "11px"}),
                        html.Li("Balanceado: Mejor relación riesgo-retorno", style={"fontSize": "11px"}),
                        html.Li("Conservador: Máxima estabilidad", style={"fontSize": "11px"}),
                    ]),
                ], style=CARD_STYLE),
            ], md=4),
            dbc.Col([
                html.Div([
                    html.H6("2️⃣ DEFINIR PRESUPUESTO", style={"fontWeight": "700", "marginBottom": "10px"}),
                    html.P(
                        "Usa el simulador para calcular ganancias con tu presupuesto disponible.",
                        style={"fontSize": "12px", "marginBottom": "10px"}
                    ),
                    html.Ul([
                        html.Li("Presupuesto mínimo: $1,000", style={"fontSize": "11px"}),
                        html.Li("Sin límite máximo", style={"fontSize": "11px"}),
                        html.Li("Visualiza ROI total", style={"fontSize": "11px"}),
                    ]),
                ], style=CARD_STYLE),
            ], md=4),
            dbc.Col([
                html.Div([
                    html.H6("3️⃣ EJECUTAR COMPRA", style={"fontWeight": "700", "marginBottom": "10px"}),
                    html.P(
                        "Procede con la compra siguiendo el plan recomendado.",
                        style={"fontSize": "12px", "marginBottom": "10px"}
                    ),
                    html.Ul([
                        html.Li("Monitorear mercado", style={"fontSize": "11px"}),
                        html.Li("Revisar obsolescencia", style={"fontSize": "11px"}),
                        html.Li("Ajustar estrategia", style={"fontSize": "11px"}),
                    ]),
                ], style=CARD_STYLE),
            ], md=4),
        ]),
    ])
