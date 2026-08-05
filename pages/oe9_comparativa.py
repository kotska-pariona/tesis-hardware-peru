# pages/oe9_comparativa.py - Comparativa OE9 (24 Soluciones Pareto)

import dash
from dash import html, dcc, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np

from config_v6 import COLORS, CARD_STYLE, CONTENT_STYLE
from components_v6 import crear_header, crear_seccion, crear_alerta, crear_kpi_card
from utils_v6 import get_top_modelos

dash.register_page(__name__, path="/oe9-comparativa")

# Generar 24 soluciones Pareto simuladas
def generar_soluciones_pareto():
    np.random.seed(42)
    tipos = ["ESTRELLA", "OPTIMO", "AGRESIVO", "BALANCEADO", "SEGURO"]
    soluciones = []
    
    for i in range(24):
        tipo = tipos[i % len(tipos)]
        roi = np.random.uniform(40, 85)
        r_j = np.random.uniform(0.0, 1.0)
        capital = np.random.uniform(100, 2500)
        
        soluciones.append({
            "ID": f"SOL-{i+1:02d}",
            "Tipo": tipo,
            "ROI": roi,
            "r_j": r_j,
            "Capital": capital,
            "Generacion": np.random.randint(150, 200),
        })
    
    return soluciones

layout = html.Div([
    crear_header(
        "📈 Comparativa OE9",
        "24 Soluciones Pareto del Análisis NSGA-III"
    ),
    
    crear_alerta(
        "info",
        "🔬 Análisis NSGA-III",
        "200 generaciones × 200 individuos = 40,000 evaluaciones. Se seleccionaron 24 soluciones no-dominadas."
    ),
    
    # ---- FILA 1: KPIs ----
    dbc.Row([
        dbc.Col([
            crear_kpi_card(
                "Soluciones Pareto",
                "24",
                "📊",
                subtitulo="No-dominadas"
            ),
        ], md=3),
        dbc.Col([
            crear_kpi_card(
                "Generaciones",
                "200",
                "🔄",
                subtitulo="Iteraciones"
            ),
        ], md=3),
        dbc.Col([
            crear_kpi_card(
                "Población",
                "200",
                "👥",
                subtitulo="Por generación"
            ),
        ], md=3),
        dbc.Col([
            crear_kpi_card(
                "Evaluaciones",
                "40,000",
                "⚙️",
                subtitulo="Totales"
            ),
        ], md=3),
    ], style={"marginBottom": "30px"}),
    
    # ---- FILA 2: GRÁFICOS ----
    dbc.Row([
        dbc.Col([
            dcc.Graph(id="scatter-oe9"),
        ], md=6),
        dbc.Col([
            dcc.Graph(id="pie-oe9"),
        ], md=6),
    ], style={"marginBottom": "30px"}),
    
    # ---- FILA 3: TABLA ----
    html.Div([
        crear_seccion(
            "📋 TABLA DE 24 SOLUCIONES",
            id="tabla-oe9-container",
            icono="📊"
        ),
    ]),
], style=CONTENT_STYLE)

@callback(
    Output("scatter-oe9", "figure"),
    Input("scatter-oe9", "id")
)
def actualizar_scatter_oe9(_):
    soluciones = generar_soluciones_pareto()
    df = pd.DataFrame(soluciones)
    
    fig = px.scatter(
        df,
        x="r_j",
        y="ROI",
        size="Capital",
        color="Tipo",
        hover_name="ID",
        hover_data={
            "ROI": ":.1f",
            "r_j": ":.4f",
            "Capital": ":$,.0f",
            "Generacion": True,
            "Tipo": True,
        },
        title="24 Soluciones Pareto: ROI vs Riesgo",
        labels={
            "r_j": "Riesgo de Obsolescencia (r_j)",
            "ROI": "ROI (%)",
        },
        color_discrete_map={
            "ESTRELLA": COLORS["accent"],
            "OPTIMO": COLORS["accent2"],
            "AGRESIVO": COLORS["danger"],
            "BALANCEADO": COLORS["warning"],
            "SEGURO": COLORS["info"],
        },
    )
    
    fig.update_layout(
        template="plotly_white",
        height=400,
        hovermode="closest",
    )
    
    return fig

@callback(
    Output("pie-oe9", "figure"),
    Input("pie-oe9", "id")
)
def actualizar_pie_oe9(_):
    soluciones = generar_soluciones_pareto()
    df = pd.DataFrame(soluciones)
    
    distribucion = df["Tipo"].value_counts()
    
    fig = go.Figure(data=[go.Pie(
        labels=distribucion.index,
        values=distribucion.values,
        marker=dict(
            colors=[
                COLORS["accent"],
                COLORS["accent2"],
                COLORS["danger"],
                COLORS["warning"],
                COLORS["info"],
            ]
        ),
        textposition="inside",
        textinfo="label+percent+value",
    )])
    
    fig.update_layout(
        title="Distribución de Soluciones por Tipo",
        template="plotly_white",
        height=400,
    )
    
    return fig

@callback(
    Output("tabla-oe9-container", "children"),
    Input("tabla-oe9-container", "id")
)
def actualizar_tabla_oe9(_):
    soluciones = generar_soluciones_pareto()
    df = pd.DataFrame(soluciones)
    
    df_display = df.copy()
    df_display["ROI"] = df_display["ROI"].apply(lambda x: f"+{x:.1f}%")
    df_display["r_j"] = df_display["r_j"].apply(lambda x: f"{x:.4f}")
    df_display["Capital"] = df_display["Capital"].apply(lambda x: f"${x:,.0f}")
    
    return html.Div([
        dbc.Table.from_dataframe(
            df_display,
            striped=True,
            bordered=True,
            hover=True,
            responsive=True,
            style={"fontSize": "11px"}
        ),
    ])
