# pages/simulador_compra.py - Simulador de Compra con Presupuesto

import dash
from dash import html, dcc, callback, Input, Output, State
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from config_v6 import COLORS, CARD_STYLE, CONTENT_STYLE
from components_v6 import (
    crear_header, crear_seccion, crear_alerta,
    crear_kpi_card
)
from utils_v6 import get_top_modelos, calcular_simulador

dash.register_page(__name__, path="/simulador")

layout = html.Div([
    crear_header(
        "💰 Simulador de Compra",
        "Calcula ganancia total con presupuesto disponible"
    ),
    
    crear_alerta(
        "info",
        "🎯 Simulación Interactiva",
        "Ingresa tu presupuesto disponible y visualiza las ganancias potenciales por modelo."
    ),
    
    # ---- FILA 1: INPUT PRESUPUESTO ----
    dbc.Row([
        dbc.Col([
            html.Div([
                html.Label("💵 Presupuesto Disponible ($)", style={"fontWeight": "600", "marginBottom": "10px"}),
                dbc.Input(
                    id="input-presupuesto",
                    type="number",
                    placeholder="Ingresa presupuesto",
                    value=100000,
                    min=1000,
                    step=1000,
                    style={
                        "width": "100%",
                        "padding": "10px",
                        "borderRadius": "6px",
                        "border": f"1px solid {COLORS['border']}",
                        "fontSize": "14px",
                    }
                ),
            ], style=CARD_STYLE),
        ], md=4),
        dbc.Col([
            html.Div([
                html.Label("🎯 Modelo a Simular", style={"fontWeight": "600", "marginBottom": "10px"}),
                dcc.Dropdown(
                    id="dropdown-modelo",
                    options=[
                        {"label": "AGRESIVO", "value": "AGRESIVO"},
                        {"label": "ESTRELLA", "value": "ESTRELLA"},
                        {"label": "OPTIMO", "value": "OPTIMO"},
                        {"label": "BALANCEADO", "value": "BALANCEADO"},
                        {"label": "SEGURO", "value": "SEGURO"},
                    ],
                    value="ESTRELLA",
                    style={"width": "100%"},
                ),
            ], style=CARD_STYLE),
        ], md=4),
        dbc.Col([
            html.Div([
                html.Label("🔄 Actualizar", style={"fontWeight": "600", "marginBottom": "10px"}),
                dbc.Button(
                    "Calcular Simulación",
                    id="btn-simular",
                    color="primary",
                    className="w-100",
                    style={"height": "38px", "marginTop": "0px"}
                ),
            ], style=CARD_STYLE),
        ], md=4),
    ], style={"marginBottom": "30px"}),
    
    # ---- FILA 2: RESULTADOS KPIs ----
    dbc.Row([
        dbc.Col([
            crear_kpi_card(
                "Unidades a Comprar",
                id="kpi-unidades",
                icono="📦",
            ),
        ], md=3),
        dbc.Col([
            crear_kpi_card(
                "Capital Total",
                id="kpi-capital",
                icono="💰",
            ),
        ], md=3),
        dbc.Col([
            crear_kpi_card(
                "Ganancia Total",
                id="kpi-ganancia",
                icono="📈",
            ),
        ], md=3),
        dbc.Col([
            crear_kpi_card(
                "ROI Total",
                id="kpi-roi",
                icono="🎯",
            ),
        ], md=3),
    ], style={"marginBottom": "30px"}),
    
    # ---- FILA 3: TABLA COMPARATIVA ----
    html.Div([
        crear_seccion(
            "📊 COMPARATIVA DE TODOS LOS MODELOS",
            id="tabla-simulador-container",
            icono="📋"
        ),
    ], style={"marginBottom": "30px"}),
    
    # ---- FILA 4: GRÁFICOS ----
    dbc.Row([
        dbc.Col([
            dcc.Graph(id="bar-ganancia-modelos"),
        ], md=6),
        dbc.Col([
            dcc.Graph(id="bar-roi-modelos"),
        ], md=6),
    ]),
], style=CONTENT_STYLE)

@callback(
    [
        Output("kpi-unidades", "children"),
        Output("kpi-capital", "children"),
        Output("kpi-ganancia", "children"),
        Output("kpi-roi", "children"),
    ],
    Input("btn-simular", "n_clicks"),
    [
        State("input-presupuesto", "value"),
        State("dropdown-modelo", "value"),
    ],
    prevent_initial_call=False
)
def actualizar_kpis(n_clicks, presupuesto, modelo_seleccionado):
    modelos_dict = {m["modelo"]: m for m in get_top_modelos()}
    modelo = modelos_dict.get(modelo_seleccionado)
    
    if not modelo or not presupuesto:
        return "0", "$0", "$0", "0%"
    
    sim = calcular_simulador(presupuesto, modelo["roi"], modelo["capital"])
    
    return (
        f"{sim['unidades']:,}",
        f"${sim['capital_total']:,.0f}",
        f"${sim['ganancia_total']:,.0f}",
        f"+{sim['roi_total']:.1f}%",
    )

@callback(
    Output("tabla-simulador-container", "children"),
    Input("btn-simular", "n_clicks"),
    State("input-presupuesto", "value"),
    prevent_initial_call=False
)
def actualizar_tabla_simulador(n_clicks, presupuesto):
    modelos = get_top_modelos()
    
    datos = []
    for modelo in modelos:
        sim = calcular_simulador(presupuesto, modelo["roi"], modelo["capital"])
        datos.append({
            "Modelo": modelo["modelo"],
            "ROI Unit. (%)": f"+{modelo['roi']:.1f}%",
            "Capital/Unit. ($)": f"${modelo['capital']:,}",
            "Unidades": f"{sim['unidades']:,}",
            "Ganancia/Unit. ($)": f"${sim['ganancia_unitaria']:,.0f}",
            "Ganancia Total ($)": f"${sim['ganancia_total']:,.0f}",
            "ROI Total (%)": f"+{sim['roi_total']:.1f}%",
        })
    
    df = pd.DataFrame(datos)
    
    return html.Div([
        dbc.Table.from_dataframe(
            df,
            striped=True,
            bordered=True,
            hover=True,
            responsive=True,
            style={"fontSize": "11px"}
        ),
    ])

@callback(
    Output("bar-ganancia-modelos", "figure"),
    Input("btn-simular", "n_clicks"),
    State("input-presupuesto", "value"),
    prevent_initial_call=False
)
def actualizar_bar_ganancia(n_clicks, presupuesto):
    modelos = get_top_modelos()
    
    datos = []
    for modelo in modelos:
        sim = calcular_simulador(presupuesto, modelo["roi"], modelo["capital"])
        datos.append({
            "Modelo": modelo["modelo"],
            "Ganancia Total": sim["ganancia_total"],
        })
    
    df = pd.DataFrame(datos)
    
    fig = px.bar(
        df,
        x="Modelo",
        y="Ganancia Total",
        color="Ganancia Total",
        title=f"Ganancia Total por Modelo (Presupuesto: ${presupuesto:,})",
        color_continuous_scale="Viridis",
    )
    
    fig.update_layout(
        template="plotly_white",
        height=400,
        hovermode="x unified",
    )
    
    return fig

@callback(
    Output("bar-roi-modelos", "figure"),
    Input("btn-simular", "n_clicks"),
    State("input-presupuesto", "value"),
    prevent_initial_call=False
)
def actualizar_bar_roi(n_clicks, presupuesto):
    modelos = get_top_modelos()
    
    datos = []
    for modelo in modelos:
        sim = calcular_simulador(presupuesto, modelo["roi"], modelo["capital"])
        datos.append({
            "Modelo": modelo["modelo"],
            "ROI Total": sim["roi_total"],
        })
    
    df = pd.DataFrame(datos)
    
    fig = px.bar(
        df,
        x="Modelo",
        y="ROI Total",
        color="ROI Total",
        title="ROI Total por Modelo",
        color_continuous_scale="Plasma",
    )
    
    fig.update_layout(
        template="plotly_white",
        height=400,
        hovermode="x unified",
    )
    
    return fig
