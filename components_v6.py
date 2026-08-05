# components_v6.py - Componentes Reutilizables para Dashboard v6.0

import dash_bootstrap_components as dbc
from dash import html, dcc
from config_v6 import COLORS, CARD_STYLE, HEADER_STYLE, SUBHEADER_STYLE

# ============ COMPONENTES DE ENCABEZADO ============

def crear_header(titulo, subtitulo=""):
    """Crea un encabezado estándar"""
    return html.Div([
        html.H1(titulo, style=HEADER_STYLE),
        html.P(subtitulo, style=SUBHEADER_STYLE) if subtitulo else None,
    ])

def crear_kpi_card(titulo, valor, icono, color="primary", subtitulo=""):
    """Crea una tarjeta KPI"""
    return dbc.Card([
        dbc.CardBody([
            html.Div([
                html.Div(icono, style={
                    "fontSize": "32px",
                    "marginRight": "15px",
                    "color": COLORS["accent"],
                }),
                html.Div([
                    html.P(titulo, style={
                        "fontSize": "12px",
                        "color": COLORS["text_light"],
                        "margin": "0",
                    }),
                    html.H3(valor, style={
                        "fontSize": "24px",
                        "fontWeight": "700",
                        "color": COLORS["text"],
                        "margin": "0",
                    }),
                    html.P(subtitulo, style={
                        "fontSize": "11px",
                        "color": COLORS["text_light"],
                        "margin": "5px 0 0 0",
                    }) if subtitulo else None,
                ]),
            ], style={"display": "flex", "alignItems": "center"}),
        ]),
    ], style={
        **CARD_STYLE,
        "borderLeft": f"4px solid {COLORS['accent']}",
    })

def crear_recomendacion_box(titulo, modelo, roi, capital, ganancia, riesgo, para):
    """Crea una caja de recomendación"""
    return dbc.Card([
        dbc.CardBody([
            html.H5(titulo, style={"marginBottom": "15px", "fontWeight": "700"}),
            html.Div([
                html.Div([
                    html.P("Modelo:", style={"fontSize": "12px", "color": COLORS["text_light"]}),
                    html.P(modelo, style={"fontSize": "14px", "fontWeight": "600"}),
                ], style={"marginBottom": "10px"}),
                html.Div([
                    html.P("ROI:", style={"fontSize": "12px", "color": COLORS["text_light"]}),
                    html.P(f"+{roi}%", style={"fontSize": "18px", "fontWeight": "700", "color": COLORS["accent2"]}),
                ], style={"marginBottom": "10px"}),
                html.Div([
                    html.P("Capital:", style={"fontSize": "12px", "color": COLORS["text_light"]}),
                    html.P(f"${capital}", style={"fontSize": "14px", "fontWeight": "600"}),
                ], style={"marginBottom": "10px"}),
                html.Div([
                    html.P("Ganancia:", style={"fontSize": "12px", "color": COLORS["text_light"]}),
                    html.P(f"${ganancia}", style={"fontSize": "14px", "fontWeight": "600"}),
                ], style={"marginBottom": "10px"}),
                html.Div([
                    html.P("Riesgo:", style={"fontSize": "12px", "color": COLORS["text_light"]}),
                    html.P(riesgo, style={"fontSize": "14px", "fontWeight": "600"}),
                ], style={"marginBottom": "10px"}),
                html.Hr(style={"margin": "10px 0"}),
                html.P(f"Para: {para}", style={"fontSize": "11px", "color": COLORS["text_light"], "fontStyle": "italic"}),
            ]),
        ]),
    ], style={**CARD_STYLE, "marginBottom": "15px"})

def crear_tabla_simple(df, titulo=""):
    """Crea una tabla simple con estilo"""
    return html.Div([
        html.H6(titulo, style={"marginBottom": "15px", "fontWeight": "700"}) if titulo else None,
        dbc.Table.from_dataframe(
            df,
            striped=True,
            bordered=True,
            hover=True,
            responsive=True,
            style={
                "fontSize": "13px",
                "marginBottom": "0",
            }
        ),
    ])

def crear_seccion(titulo, contenido, icono=""):
    """Crea una sección con título"""
    return html.Div([
        html.Div([
            html.Span(icono, style={"marginRight": "10px", "fontSize": "20px"}) if icono else None,
            html.H5(titulo, style={"display": "inline", "fontWeight": "700"}),
        ], style={"marginBottom": "15px"}),
        html.Div(contenido, style={
            "backgroundColor": COLORS["card"],
            "padding": "15px",
            "borderRadius": "6px",
            "borderLeft": f"3px solid {COLORS['accent']}",
        }),
    ], style={"marginBottom": "20px"})

def crear_badge(texto, color="primary"):
    """Crea un badge/etiqueta"""
    colores_map = {
        "success": COLORS["accent2"],
        "danger": COLORS["danger"],
        "warning": COLORS["warning"],
        "info": COLORS["info"],
        "primary": COLORS["accent"],
    }
    return html.Span(
        texto,
        style={
            "display": "inline-block",
            "padding": "4px 12px",
            "borderRadius": "12px",
            "backgroundColor": colores_map.get(color, COLORS["accent"]),
            "color": "white",
            "fontSize": "11px",
            "fontWeight": "600",
        }
    )

def crear_estadistica_fila(label, valor, unidad="", color="accent"):
    """Crea una fila de estadística"""
    return html.Div([
        html.Div([
            html.Span(label, style={
                "color": COLORS["text_light"],
                "fontSize": "12px",
            }),
            html.Span(f"{valor} {unidad}", style={
                "fontSize": "16px",
                "fontWeight": "700",
                "color": COLORS[color],
                "marginLeft": "10px",
            }),
        ], style={
            "display": "flex",
            "justifyContent": "space-between",
            "alignItems": "center",
            "padding": "8px 0",
            "borderBottom": f"1px solid {COLORS['border']}",
        }),
    ])

def crear_alerta(tipo, titulo, mensaje):
    """Crea una alerta"""
    colores_map = {
        "info": {"bg": COLORS["info"], "border": COLORS["info"]},
        "success": {"bg": COLORS["accent2"], "border": COLORS["accent2"]},
        "warning": {"bg": COLORS["warning"], "border": COLORS["warning"]},
        "danger": {"bg": COLORS["danger"], "border": COLORS["danger"]},
    }
    
    color = colores_map.get(tipo, colores_map["info"])
    
    return dbc.Alert([
        html.H6(titulo, style={"marginBottom": "5px", "fontWeight": "700"}),
        html.P(mensaje, style={"margin": "0", "fontSize": "13px"}),
    ], color=tipo, style={
        "borderLeft": f"4px solid {color['border']}",
        "marginBottom": "15px",
    })
