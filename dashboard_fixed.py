import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

print("\n" + "=" * 80)
print("  🚀 HDS-ROI v6.2 — Iniciando con validación paso a paso...")
print("=" * 80 + "\n")

# =============================================================================
# PASO 1: IMPORTS
# =============================================================================
print("📦 PASO 1: Importando módulos...")

try:
    import os
    import json
    import warnings
    from datetime import datetime
    from pathlib import Path
    print("  ✅ Módulos estándar OK")
except Exception as e:
    print(f"  ❌ Error en imports estándar: {e}")
    sys.exit(1)

try:
    import numpy as np
    import pandas as pd
    print("  ✅ NumPy/Pandas OK")
except Exception as e:
    print(f"  ❌ Error en NumPy/Pandas: {e}")
    sys.exit(1)

try:
    import plotly.graph_objects as go
    import plotly.express as px
    print("  ✅ Plotly OK")
except Exception as e:
    print(f"  ❌ Error en Plotly: {e}")
    sys.exit(1)

try:
    import dash
    from dash import dcc, html, Input, Output, State
    import dash_bootstrap_components as dbc
    print(f"  ✅ Dash {dash.__version__} OK")
except Exception as e:
    print(f"  ❌ Error en Dash: {e}")
    sys.exit(1)

try:
    from dashboard_config import COLORS, PLOTLY_TEMPLATE, CHART_CONFIG, SIDEBAR_STYLE, CONTENT_STYLE, APP_CONFIG
    print("  ✅ dashboard_config.py OK")
except Exception as e:
    print(f"  ❌ Error en dashboard_config.py: {e}")
    sys.exit(1)

try:
    from dashboard_data import DATA
    print("  ✅ dashboard_data.py OK")
    print(f"     → OE9 soluciones: {len(DATA['oe9_pareto'])}")
    print(f"     → SKUs predicciones: {len(DATA.get('predicciones_multi', {}).get('skus', {}))}")
except Exception as e:
    print(f"  ❌ Error en dashboard_data.py: {e}")
    sys.exit(1)

warnings.filterwarnings("ignore")

# =============================================================================
# PASO 2: CREAR APP
# =============================================================================
print("\n📱 PASO 2: Creando aplicación Dash...")

try:
    app = dash.Dash(
        __name__,
        external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP],
        suppress_callback_exceptions=True,
        title=APP_CONFIG["title"],
    )
    print("  ✅ App Dash creada")
except Exception as e:
    print(f"  ❌ Error creando app: {e}")
    sys.exit(1)

# =============================================================================
# PASO 3: COMPONENTES BÁSICOS
# =============================================================================
print("\n🎨 PASO 3: Definiendo componentes...")

def kpi_card(title, value, subtitle="", color=None, icon="📊"):
    color = color or COLORS["accent"]
    return dbc.Card([
        dbc.CardBody([
            html.Div([
                html.Span(icon, style={"fontSize": "2rem", "marginRight": "12px"}),
                html.Div([
                    html.P(title, style={"color": COLORS["text_dim"], "fontSize": "0.75rem"}),
                    html.H4(value, style={"color": color, "fontSize": "1.8rem", "fontWeight": 700}),
                    html.P(subtitle, style={"color": COLORS["text_dim"], "fontSize": "0.7rem"}),
                ], style={"flex": 1})
            ], style={"display": "flex", "alignItems": "center"})
        ])
    ], style={"height": "120px", "borderRadius": "10px"})

def section_title(text, icon=""):
    return html.H5(
        [html.Span(icon + " " if icon else ""), text],
        style={"color": COLORS["accent"], "borderBottom": f"3px solid {COLORS['accent']}",
               "paddingBottom": "10px", "marginBottom": "20px", "fontWeight": 700}
    )

print("  ✅ Componentes definidos")

# =============================================================================
# PASO 4: PÁGINAS SIMPLES
# =============================================================================
print("\n📄 PASO 4: Definiendo páginas...")

def page_home():
    df_oe9 = DATA["oe9_pareto"]
    return html.Div([
        section_title("HDS-ROI v6.2 — Dashboard Principal", "🎓"),
        dbc.Row([
            dbc.Col(kpi_card("WMAPE", "0.97%", "PE2 v5.2", COLORS["green"], "🎯"), md=3),
            dbc.Col(kpi_card("Soluciones", str(len(df_oe9)), "NSGA-III", COLORS["accent"], "⚙️"), md=3),
            dbc.Col(kpi_card("ROI Máx", f"+{df_oe9['roi_pct'].max():.1f}%", "Portafolio", COLORS["accent3"], "💰"), md=3),
            dbc.Col(kpi_card("SKUs", "30", "Predicciones", COLORS["accent2"], "📊"), md=3),
        ], className="mb-4"),
        dbc.Alert("✅ Sistema operativo · Todos los módulos cargados", color="success"),
    ], style={"padding": "24px"})

def page_404():
    return html.Div([
        html.H3("404 — Página no encontrada", style={"padding": "24px"}),
        dbc.Alert("Usa el menú lateral para navegar", color="warning"),
    ], style={"padding": "24px"})

print("  ✅ Páginas definidas")

# =============================================================================
# PASO 5: SIDEBAR
# =============================================================================
print("\n🗂️ PASO 5: Creando sidebar...")

sidebar = html.Div([
    html.Div([
        html.H4("HDS-ROI", style={"color": COLORS["accent"], "fontWeight": 800}),
        html.P("v6.2 · PE2 v5.2", style={"color": COLORS["text_dim"], "fontSize": "0.7rem"}),
    ], style={"padding": "16px"}),
    
    dbc.Nav([
        dbc.NavLink("🏠 Inicio", href="/", active="exact"),
        dbc.NavLink("📊 Datos", href="/datos", active="exact"),
        dbc.NavLink("⚙️ NSGA-III", href="/oe9", active="exact"),
    ], vertical=True, pills=True),
], style=SIDEBAR_STYLE)

print("  ✅ Sidebar creado")

# =============================================================================
# PASO 6: LAYOUT
# =============================================================================
print("\n🎨 PASO 6: Configurando layout...")

try:
    app.layout = html.Div([
        dcc.Location(id="url", refresh=False),
        sidebar,
        html.Div(id="page-content", style=CONTENT_STYLE),
    ])
    print("  ✅ Layout configurado")
except Exception as e:
    print(f"  ❌ Error en layout: {e}")
    sys.exit(1)

# =============================================================================
# PASO 7: CALLBACKS
# =============================================================================
print("\n🔗 PASO 7: Registrando callbacks...")

try:
    @app.callback(
        Output("page-content", "children"),
        Input("url", "pathname"),
    )
    def display_page(pathname):
        if pathname == "/datos":
            return html.Div([
                section_title("Análisis de Datos", "📊"),
                dbc.Alert("✅ 1000 registros cargados", color="success"),
            ], style={"padding": "24px"})
        elif pathname == "/oe9":
            df = DATA["oe9_pareto"]
            return html.Div([
                section_title("NSGA-III OE9", "⚙️"),
                dbc.Alert(f"✅ {len(df)} soluciones Pareto", color="success"),
            ], style={"padding": "24px"})
        elif pathname == "/":
            return page_home()
        else:
            return page_404()
    
    print("  ✅ Callback de navegación registrado")
except Exception as e:
    print(f"  ❌ Error en callbacks: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# =============================================================================
# PASO 8: INICIAR SERVIDOR
# =============================================================================
print("\n" + "=" * 80)
print("  🚀 HDS-ROI v6.2 — Listo para iniciar")
print("=" * 80)
print(f"  🌐 URL: http://{APP_CONFIG['host']}:{APP_CONFIG['port']}")
print(f"  📊 Datos: {len(DATA['oe9_pareto'])} soluciones OE9 · 30 SKUs")
print("─" * 80)
print("  ⚡ Iniciando servidor Dash...")
print("  ⏳ Esperando conexiones (Ctrl+C para detener)...")
print("=" * 80 + "\n")

if __name__ == "__main__":
    try:
        app.run(
            host=APP_CONFIG["host"],
            port=APP_CONFIG["port"],
            debug=False,
        )
    except KeyboardInterrupt:
        print("\n\n⏹️  Servidor detenido por el usuario")
    except Exception as e:
        print(f"\n\n❌ ERROR FATAL: {e}\n")
        import traceback
        traceback.print_exc()
