# pages/datos_reporte.py - Reporte de Datos de Scraping y Entrenamiento

import dash
from dash import html, dcc, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from config_v6 import COLORS, CARD_STYLE, CONTENT_STYLE
from components_v6 import (
    crear_header, crear_seccion, crear_alerta,
    crear_estadistica_fila, crear_kpi_card
)
from utils_v6 import generar_reporte_datos, get_fuentes_dataframe

dash.register_page(__name__, path="/datos-reporte")

layout = html.Div([
    crear_header(
        "📊 Reporte de Datos",
        "Scraping, Entrenamiento, Validación y Test"
    ),
    
    crear_alerta(
        "success",
        "✅ Proceso Completado",
        "Se han scrapeado 82 SKUs de 6 fuentes diferentes con distribución 60/20/20."
    ),
    
    # ---- FILA 1: KPIs ----
    dbc.Row([
        dbc.Col([
            crear_kpi_card(
                "Total Scrapeado",
                "82 SKUs",
                "📦",
                subtitulo="De 6 fuentes"
            ),
        ], md=3),
        dbc.Col([
            crear_kpi_card(
                "Entrenamiento",
                "49 SKUs",
                "🎓",
                subtitulo="60%"
            ),
        ], md=3),
        dbc.Col([
            crear_kpi_card(
                "Validación",
                "16 SKUs",
                "✓",
                subtitulo="20%"
            ),
        ], md=3),
        dbc.Col([
            crear_kpi_card(
                "Test",
                "17 SKUs",
                "🧪",
                subtitulo="20%"
            ),
        ], md=3),
    ], style={"marginBottom": "30px"}),
    
    # ---- FILA 2: GRÁFICOS ----
    dbc.Row([
        dbc.Col([
            dcc.Graph(id="pie-distribucion-datos"),
        ], md=6),
        dbc.Col([
            dcc.Graph(id="bar-fuentes"),
        ], md=6),
    ], style={"marginBottom": "30px"}),
    
    # ---- FILA 3: TABLA FUENTES ----
    html.Div([
        crear_seccion(
            "🌐 FUENTES DE SCRAPING",
            id="tabla-fuentes-container",
            icono="🔗"
        ),
    ]),
], style=CONTENT_STYLE)

@callback(
    Output("pie-distribucion-datos", "figure"),
    Input("pie-distribucion-datos", "id")
)
def actualizar_pie_distribucion(_):
    reporte = generar_reporte_datos()
    
    fig = go.Figure(data=[go.Pie(
        labels=["Entrenamiento", "Validación", "Test"],
        values=[
            reporte["entrenamiento"],
            reporte["validacion"],
            reporte["test"]
        ],
        marker=dict(colors=[
            COLORS["accent"],
            COLORS["accent2"],
            COLORS["warning"],
        ]),
        textposition="inside",
        textinfo="label+percent+value",
    )])
    
    fig.update_layout(
        title="Distribución de Datos (82 SKUs Total)",
        template="plotly_white",
        height=400,
    )
    
    return fig

@callback(
    Output("bar-fuentes", "figure"),
    Input("bar-fuentes", "id")
)
def actualizar_bar_fuentes(_):
    df = get_fuentes_dataframe()
    
    fig = px.bar(
        df,
        x="fuente",
        y="skus",
        color="porcentaje",
        hover_data={"porcentaje": ":.1f", "estado": True},
        title="SKUs por Fuente de Scraping",
        labels={
            "fuente": "Fuente",
            "skus": "Cantidad de SKUs",
            "porcentaje": "Porcentaje (%)",
        },
        color_continuous_scale="Viridis",
    )
    
    fig.update_layout(
        template="plotly_white",
        height=400,
        hovermode="x unified",
    )
    
    return fig

@callback(
    Output("tabla-fuentes-container", "children"),
    Input("tabla-fuentes-container", "id")
)
def actualizar_tabla_fuentes(_):
    df = get_fuentes_dataframe()
    
    df_display = df.copy()
    df_display["porcentaje"] = df_display["porcentaje"].apply(lambda x: f"{x:.1f}%")
    
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
