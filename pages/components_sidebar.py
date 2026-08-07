# components_sidebar.py - Componente de Barra Lateral

import dash_bootstrap_components as dbc
from dash import html, dcc
from config_v6 import COLORS, APP_NAME, APP_VERSION, LAST_UPDATE

def crear_sidebar():
    """Crea la barra lateral del dashboard"""
    
    return html.Div([
        # ---- HEADER SIDEBAR ----
        html.Div([
            html.H4(
                "🎯 HDS-ROI",
                style={
                    "color": "white",
                    "marginBottom": "5px",
                    "fontWeight": "700",
                }
            ),
            html.P(
                f"v{APP_VERSION}",
                style={
                    "color": "#bdc3c7",
                    "fontSize": "12px",
                    "margin": "0",
                }
            ),
        ], style={
            "backgroundColor": COLORS["accent"],
            "padding": "20px",
            "borderRadius": "0",
            "marginBottom": "20px",
        }),
        
        # ---- NAVEGACIÓN ----
        html.Div([
            html.H6(
                "📍 NAVEGACIÓN",
                style={
                    "color": COLORS["text_light"],
                    "fontSize": "11px",
                    "fontWeight": "700",
                    "marginBottom": "15px",
                    "textTransform": "uppercase",
                    "letterSpacing": "1px",
                }
            ),
            dcc.Link(
                html.Div([
                    html.Span("🎯 Motor de Decisión", style={"marginLeft": "10px"}),
                ], style={
                    "display": "flex",
                    "alignItems": "center",
                    "padding": "12px",
                    "marginBottom": "8px",
                    "borderRadius": "6px",
                    "backgroundColor": COLORS["card"],
                    "color": COLORS["text"],
                    "textDecoration": "none",
                    "fontSize": "13px",
                    "fontWeight": "500",
                    "transition": "all 0.3s",
                }),
                href="/",
                style={"textDecoration": "none"}
            ),
            dcc.Link(
                html.Div([
                    html.Span("📦 Análisis de Modelos", style={"marginLeft": "10px"}),
                ], style={
                    "display": "flex",
                    "alignItems": "center",
                    "padding": "12px",
                    "marginBottom": "8px",
                    "borderRadius": "6px",
                    "backgroundColor": COLORS["card"],
                    "color": COLORS["text"],
                    "textDecoration": "none",
                    "fontSize": "13px",
                    "fontWeight": "500",
                }),
                href="/modelos",
                style={"textDecoration": "none"}
            ),
            dcc.Link(
                html.Div([
                    html.Span("📊 Reporte de Datos", style={"marginLeft": "10px"}),
                ], style={
                    "display": "flex",
                    "alignItems": "center",
                    "padding": "12px",
                    "marginBottom": "8px",
                    "borderRadius": "6px",
                    "backgroundColor": COLORS["card"],
                    "color": COLORS["text"],
                    "textDecoration": "none",
                    "fontSize": "13px",
                    "fontWeight": "500",
                }),
                href="/datos-reporte",
                style={"textDecoration": "none"}
            ),
            dcc.Link(
                html.Div([
                    html.Span("⚠️ Análisis de Riesgo", style={"marginLeft": "10px"}),
                ], style={
                    "display": "flex",
                    "alignItems": "center",
                    "padding": "12px",
                    "marginBottom": "8px",
                    "borderRadius": "6px",
                    "backgroundColor": COLORS["card"],
                    "color": COLORS["text"],
                    "textDecoration": "none",
                    "fontSize": "13px",
                    "fontWeight": "500",
                }),
                href="/riesgo",
                style={"textDecoration": "none"}
            ),
            dcc.Link(
                html.Div([
                    html.Span("💰 Simulador de Compra", style={"marginLeft": "10px"}),
                ], style={
                    "display": "flex",
                    "alignItems": "center",
                    "padding": "12px",
                    "marginBottom": "8px",
                    "borderRadius": "6px",
                    "backgroundColor": COLORS["card"],
                    "color": COLORS["text"],
                    "textDecoration": "none",
                    "fontSize": "13px",
                    "fontWeight": "500",
                }),
                href="/simulador",
                style={"textDecoration": "none"}
            ),
            dcc.Link(
                html.Div([
                    html.Span("📈 Comparativa OE9", style={"marginLeft": "10px"}),
                ], style={
                    "display": "flex",
                    "alignItems": "center",
                    "padding": "12px",
                    "marginBottom": "8px",
                    "borderRadius": "6px",
                    "backgroundColor": COLORS["card"],
                    "color": COLORS["text"],
                    "textDecoration": "none",
                    "fontSize": "13px",
                    "fontWeight": "500",
                }),
                href="/oe9-comparativa",
                style={"textDecoration": "none"}
            ),
            
            dcc.Link(
                html.Div([
                    html.Span("📊 Arbitraje ROI", style={"marginLeft": "10px"}),
                ], style={
                    "display": "flex",
                    "alignItems": "center",
                    "padding": "12px",
                    "marginBottom": "8px",
                    "borderRadius": "6px",
                    "backgroundColor": "#1a3a2a",
                    "color": "#27ae60",
                    "textDecoration": "none",
                    "fontSize": "13px",
                    "fontWeight": "600",
                    "border": "1px solid #27ae60",
                }),
                href="/arbitraje",
                style={"textDecoration": "none"}
            ),
            dcc.Link(
                html.Div([
                    html.Span("🎯 Decisión Final", style={"marginLeft": "10px"}),
                ], style={
                    "display": "flex",
                    "alignItems": "center",
                    "padding": "12px",
                    "marginBottom": "8px",
                    "borderRadius": "6px",
                    "backgroundColor": COLORS["accent"],
                    "color": "white",
                    "textDecoration": "none",
                    "fontSize": "13px",
                    "fontWeight": "600",
                }),
                href="/decision-final",
                style={"textDecoration": "none"}
            ),
        ], style={"marginBottom": "30px"}),
        
        # ---- INFORMACIÓN ----
        html.Hr(style={"borderColor": COLORS["border"], "margin": "20px 0"}),
        
        html.Div([
            html.H6(
                "ℹ️ INFORMACIÓN",
                style={
                    "color": COLORS["text_light"],
                    "fontSize": "11px",
                    "fontWeight": "700",
                    "marginBottom": "15px",
                    "textTransform": "uppercase",
                    "letterSpacing": "1px",
                }
            ),
            html.Div([
                html.P("Última actualización:", style={"fontSize": "11px", "margin": "0", "fontWeight": "600"}),
                html.P(LAST_UPDATE, style={"fontSize": "10px", "color": COLORS["text_light"], "margin": "0"}),
            ], style={"marginBottom": "15px"}),
            html.Div([
                html.P("Versión:", style={"fontSize": "11px", "margin": "0", "fontWeight": "600"}),
                html.P(APP_VERSION, style={"fontSize": "10px", "color": COLORS["text_light"], "margin": "0"}),
            ], style={"marginBottom": "15px"}),
            html.Div([
                html.P("Estado:", style={"fontSize": "11px", "margin": "0", "fontWeight": "600"}),
                html.P("🟢 Operativo", style={"fontSize": "10px", "color": COLORS["accent2"], "margin": "0"}),
            ]),
        ]),
        
    ], style={
        "position": "fixed",
        "top": "0",
        "left": "0",
        "bottom": "0",
        "width": "250px",
        "backgroundColor": "white",
        "padding": "20px",
        "overflowY": "auto",
        "borderRight": f"1px solid {COLORS['border']}",
        "boxShadow": "2px 0 4px rgba(0,0,0,0.05)",
    })
