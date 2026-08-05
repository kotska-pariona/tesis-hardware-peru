# app.py - Aplicación Principal Dash v6.0

import dash
import dash_bootstrap_components as dbc
from dash import html, dcc

from config_v6 import COLORS, CONTENT_STYLE, APP_NAME
from components_sidebar import crear_sidebar

# ============ INICIALIZAR APP ============

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
    pages_folder="pages",
    use_pages=True,
)

# ============ ESTILOS GLOBALES ============

app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen',
                    'Ubuntu', 'Cantarell', 'Fira Sans', 'Droid Sans', 'Helvetica Neue',
                    sans-serif;
                -webkit-font-smoothing: antialiased;
                -moz-osx-font-smoothing: grayscale;
                background-color: #f5f7fa;
            }
            
            ::-webkit-scrollbar {
                width: 8px;
                height: 8px;
            }
            
            ::-webkit-scrollbar-track {
                background: #f1f1f1;
            }
            
            ::-webkit-scrollbar-thumb {
                background: #888;
                border-radius: 4px;
            }
            
            ::-webkit-scrollbar-thumb:hover {
                background: #555;
            }
            
            .dash-table-container {
                overflow-x: auto;
            }
            
            .dash-table {
                font-size: 12px !important;
            }
            
            .dash-table thead tr th {
                background-color: ''' + COLORS["accent"] + ''' !important;
                color: white !important;
                font-weight: 600 !important;
                padding: 12px !important;
            }
            
            .dash-table tbody tr td {
                padding: 10px 12px !important;
                border-color: ''' + COLORS["border"] + ''' !important;
            }
            
            .dash-table tbody tr:hover {
                background-color: ''' + COLORS["card"] + ''' !important;
            }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''

# ============ LAYOUT ============

app.layout = html.Div([
    # Sidebar
    crear_sidebar(),
    
    # Contenido Principal
    html.Div([
        dcc.Location(id="url", refresh=False),
        dash.page_container,
    ], style=CONTENT_STYLE),
], style={"display": "flex"})

# ============ CALLBACKS ============

# (Los callbacks específicos están en cada página)

# ============ EJECUTAR APP ============

if __name__ == "__main__":
    app.run_server(debug=True, port=8050, host="127.0.0.1")
