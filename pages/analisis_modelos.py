# pages/analisis_modelos.py - Análisis de Modelos Individuales

import dash
from dash import html, dcc, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.express as px
import pandas as pd

from config_v6 import COLORS, CARD_STYLE, CONTENT_STYLE
from components_v6 import crear_header, crear_seccion, crear_alerta
from utils_v6 import get_skus_dataframe

dash.register_page(__name__, path="/modelos")

layout = html.Div([
    crear_header(
        "📦 Análisis de Modelos",
        "Análisis individual de 7 SKUs principales"
    ),
    
    crear_alerta(
        "info",
        "📊 Análisis Detallado",
        "Cada SKU ha sido analizado considerando precio, margen, demanda y factor de venta."
    ),
    
    # ---- FILA 1: GRÁFICOS ----
    dbc.Row([
        dbc.Col([
            dcc.Graph(id="scatter-roi-precio"),
        ], md=6),
        dbc.Col([
            dcc.Graph(id="scatter-margen-venta"),
        ], md=6),
    ], style={"marginBottom": "30px"}),
    
    # ---- FILA 2: TABLA DETALLADA ----
    html.Div([
        crear_seccion(
            "📋 TABLA DETALLADA DE SKUs",
            id="tabla-skus-container",
            icono="📊"
        ),
    ]),
], style=CONTENT_STYLE)

@callback(
    Output("scatter-roi-precio", "figure"),
    Input("scatter-roi-precio", "id")
)
def actualizar_scatter_roi_precio(_):
    df = get_skus_dataframe()
    
    fig = px.scatter(
        df,
        x="precio",
        y="roi",
        size="score_demanda",
        color="margen",
        hover_name="producto",
        hover_data={
            "precio": ":$,.0f",
            "roi": ":.1f",
            "margen": ":.1f",
            "score_demanda": ":.1f",
        },
        title="ROI vs Precio (Tamaño = Demanda)",
        labels={
            "precio": "Precio ($)",
            "roi": "ROI (%)",
            "margen": "Margen (%)",
        },
        color_continuous_scale="Viridis",
    )
    
    fig.update_layout(
        template="plotly_white",
        height=400,
        hovermode="closest",
    )
    
    return fig

@callback(
    Output("scatter-margen-venta", "figure"),
    Input("scatter-margen-venta", "id")
)
def actualizar_scatter_margen_venta(_):
    df = get_skus_dataframe()
    
    fig = px.scatter(
        df,
        x="margen",
        y="factor_venta",
        size="roi",
        color="score_demanda",
        hover_name="producto",
        hover_data={
            "margen": ":.1f",
            "factor_venta": ":.2f",
            "roi": ":.1f",
            "score_demanda": ":.1f",
        },
        title="Margen vs Factor de Venta (Tamaño = ROI)",
        labels={
            "margen": "Margen (%)",
            "factor_venta": "Factor de Venta",
            "score_demanda": "Score Demanda",
        },
        color_continuous_scale="Plasma",
    )
    
    fig.update_layout(
        template="plotly_white",
        height=400,
        hovermode="closest",
    )
    
    return fig

@callback(
    Output("tabla-skus-container", "children"),
    Input("tabla-skus-container", "id")
)
def actualizar_tabla_skus(_):
    df = get_skus_dataframe()
    
    # Formatear datos
    df_display = df.copy()
    df_display["precio"] = df_display["precio"].apply(lambda x: f"${x:,.0f}")
    df_display["margen"] = df_display["margen"].apply(lambda x: f"{x:.1f}%")
    df_display["roi"] = df_display["roi"].apply(lambda x: f"+{x:.1f}%")
    df_display["score_demanda"] = df_display["score_demanda"].apply(lambda x: f"{x:.1f}")
    df_display["factor_venta"] = df_display["factor_venta"].apply(lambda x: f"{x:.2f}")
    df_display["peso"] = df_display["peso"].apply(lambda x: f"{x:.2f} kg")
    
    # Seleccionar columnas para mostrar
    df_display = df_display[[
        "sku", "producto", "categoria", "precio", "margen",
        "roi", "score_demanda", "factor_venta", "peso"
    ]]
    
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
