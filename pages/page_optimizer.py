import dash
from dash import dcc, html, Input, Output, State, callback
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
import json
import subprocess

dash.register_page(__name__, path='/optimizer', name='💰 Optimizador')

# ══════════════════════════════════════════════════════════════════════════════
# LAYOUT
# ══════════════════════════════════════════════════════════════════════════════
layout = dbc.Container([
    dbc.Row([
        dbc.Col([
            html.H2("💰 Optimizador de Portafolio", className="text-primary mb-4"),
            html.P("Ingresa tu presupuesto y obtén recomendaciones de compra optimizadas por ROI"),
        ])
    ]),
    
    # ── Input de presupuesto ──────────────────────────────────
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H5("Presupuesto de Inversión", className="card-title"),
                    dbc.InputGroup([
                        dbc.InputGroupText("$"),
                        dbc.Input(
                            id="input-budget",
                            type="number",
                            value=50000,
                            min=1000,
                            max=1000000,
                            step=1000
                        ),
                        dbc.InputGroupText("USD"),
                    ]),
                    html.Br(),
                    dbc.Button(
                        "🚀 Optimizar Portafolio",
                        id="btn-optimize",
                        color="primary",
                        size="lg",
                        className="w-100"
                    ),
                ])
            ])
        ], width=4),
        
        # ── Métricas del portafolio ───────────────────────────────
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H5("Resultados", className="card-title"),
                    html.Div(id="portfolio-metrics")
                ])
            ])
        ], width=8),
    ], className="mb-4"),
    
    # ── Tabla de productos ────────────────────────────────────
    dbc.Row([
        dbc.Col([
            html.Div(id="portfolio-table")
        ])
    ]),
    
    # ── Loading spinner ───────────────────────────────────────
    dcc.Loading(
        id="loading-optimizer",
        type="default",
        children=html.Div(id="loading-output")
    )
], fluid=True)

# ══════════════════════════════════════════════════════════════════════════════
# CALLBACKS
# ══════════════════════════════════════════════════════════════════════════════

@callback(
    [Output("portfolio-metrics", "children"),
     Output("portfolio-table", "children"),
     Output("loading-output", "children")],
    Input("btn-optimize", "n_clicks"),
    State("input-budget", "value"),
    prevent_initial_call=True
)
def optimize_portfolio(n_clicks, budget):
    if not budget:
        return "Ingresa un presupuesto válido", "", ""
    
    # Ejecutar optimizador
    result = subprocess.run(
        ["python", "scripts/optimize_portfolio_simple.py", str(budget)],
        capture_output=True,
        text=True
    )
    
    # Cargar resultados
    try:
        with open("results/portfolio_optimizado.json") as f:
            portfolio = json.load(f)
    except:
        return "Error al optimizar portafolio", "", ""
    
    # ── Métricas ──────────────────────────────────────────────
    metrics = dbc.Row([
        dbc.Col([
            html.H3(f"${portfolio['inversion_total_usd']:,.0f}"),
            html.P("Inversión Total", className="text-muted")
        ]),
        dbc.Col([
            html.H3(f"{portfolio['roi_promedio_pct']:.1f}%"),
            html.P("ROI Promedio", className="text-muted")
        ]),
        dbc.Col([
            html.H3(f"{portfolio['num_productos']}"),
            html.P("Productos", className="text-muted")
        ]),
        dbc.Col([
            html.H3(f"S/ {portfolio['margen_total_pen']:,.0f}"),
            html.P("Margen Total", className="text-muted")
        ]),
    ])
    
    # ── Tabla ─────────────────────────────────────────────────
    df = pd.DataFrame(portfolio['productos'])
    
    table = dbc.Table.from_dataframe(
        df[['name', 'brand', 'hw_type', 'precio_compra_usd', 'precio_venta_pen', 'roi_pct']].head(20),
        striped=True,
        bordered=True,
        hover=True
    )
    
    return metrics, table, ""
