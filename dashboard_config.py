# =============================================================================
# HDS-ROI v5.0 — Configuración Centralizada
# Autor: Proyecto de Tesis
# Fecha: 2026-07-30
# =============================================================================

# ─────────────────────────────────────────────
# PALETA DE COLORES (TEMA BLANCO PROFESIONAL)
# ─────────────────────────────────────────────

COLORS = {
    # Fondos
    "bg":              "#ffffff",          # Blanco puro
    "card":            "#f8f9fa",          # Gris muy claro
    "card_hover":      "#f0f2f5",          # Gris claro (hover)
    "border":          "#e0e0e0",          # Gris frontera
    
    # Acentos principales
    "accent":          "#00a86b",          # Verde esmeralda
    "accent2":         "#0066cc",          # Azul profesional
    "accent3":         "#ff6b35",          # Naranja vibrante
    "accent4":         "#ffc107",          # Amarillo dorado
    "purple":          "#7c3aed",          # Púrpura
    
    # Estados
    "green":           "#22c55e",          # Verde éxito
    "red":             "#ef4444",          # Rojo error
    "yellow":          "#eab308",          # Amarillo advertencia
    "blue":            "#3b82f6",          # Azul info
    
    # Texto
    "text":            "#1f2937",          # Gris oscuro (texto principal)
    "text_dim":        "#6b7280",          # Gris medio (texto secundario)
    "text_light":      "#9ca3af",          # Gris claro (texto terciario)
    
    # Especiales
    "shadow":          "rgba(0, 0, 0, 0.1)",
    "shadow_hover":    "rgba(0, 0, 0, 0.15)",
}

# ─────────────────────────────────────────────
# TEMPLATE PLOTLY PERSONALIZADO
# ─────────────────────────────────────────────

PLOTLY_TEMPLATE = dict(
    layout=dict(
        paper_bgcolor=COLORS["bg"],
        plot_bgcolor=COLORS["bg"],
        font=dict(
            color=COLORS["text"],
            family="'Segoe UI', 'Helvetica Neue', sans-serif",
            size=12
        ),
        xaxis=dict(
            gridcolor=COLORS["border"],
            zerolinecolor=COLORS["border"],
            showgrid=True,
            gridwidth=1,
        ),
        yaxis=dict(
            gridcolor=COLORS["border"],
            zerolinecolor=COLORS["border"],
            showgrid=True,
            gridwidth=1,
        ),
        legend=dict(
            bgcolor="rgba(255, 255, 255, 0.9)",
            bordercolor=COLORS["border"],
            borderwidth=1,
            font=dict(color=COLORS["text"]),
        ),
        margin=dict(l=50, r=30, t=50, b=50),
        hovermode="closest",
    )
)


# ─────────────────────────────────────────────
# ESTILOS CSS PERSONALIZADOS
# ─────────────────────────────────────────────

CUSTOM_CSS = """
:root {
    --primary: #00a86b;
    --secondary: #0066cc;
    --accent: #ff6b35;
    --bg: #ffffff;
    --text: #1f2937;
    --border: #e0e0e0;
}

* {
    font-family: 'Segoe UI', 'Helvetica Neue', sans-serif;
}

body {
    background-color: #f5f7fa;
    color: var(--text);
}

.card {
    background-color: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
    transition: all 0.3s ease;
}

.card:hover {
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
    border-color: var(--primary);
}

.section-title {
    color: var(--primary);
    font-weight: 700;
    border-bottom: 2px solid var(--border);
    padding-bottom: 12px;
    margin-bottom: 20px;
}

.kpi-value {
    color: var(--primary);
    font-weight: 700;
    font-size: 1.8rem;
}

.btn-primary {
    background-color: var(--primary);
    border-color: var(--primary);
    color: white;
}

.btn-primary:hover {
    background-color: #008c5a;
    border-color: #008c5a;
}

table {
    border-collapse: collapse;
    width: 100%;
}

thead {
    background-color: #f0f2f5;
    border-bottom: 2px solid var(--border);
}

th {
    color: var(--primary);
    font-weight: 600;
    padding: 12px;
    text-align: left;
}

td {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
}

tbody tr:hover {
    background-color: #f8f9fa;
}

.alert {
    border-radius: 6px;
    border-left: 4px solid var(--primary);
}
"""

# ─────────────────────────────────────────────
# CONFIGURACIÓN DE GRÁFICOS
# ─────────────────────────────────────────────

CHART_CONFIG = {
    "displayModeBar": False,  # Ocultar toolbar de Plotly
    "responsive": True,
    "staticPlot": False,
}

# Paletas de colores para gráficos
PALETTE_SEQUENTIAL = [
    "#e8f5e9",
    "#c8e6c9",
    "#a5d6a7",
    "#81c784",
    "#66bb6a",
    "#4caf50",
    "#43a047",
    "#388e3c",
    "#2e7d32",
    "#1b5e20",
]

PALETTE_DIVERGING = [
    "#ef4444",  # Rojo
    "#f97316",  # Naranja
    "#eab308",  # Amarillo
    "#84cc16",  # Lima
    "#22c55e",  # Verde
]

PALETTE_CATEGORICAL = [
    COLORS["accent"],    # Verde
    COLORS["accent2"],   # Azul
    COLORS["accent3"],   # Naranja
    COLORS["accent4"],   # Amarillo
    COLORS["purple"],    # Púrpura
    COLORS["red"],       # Rojo
]

# ─────────────────────────────────────────────
# CONFIGURACIÓN DE LAYOUT
# ─────────────────────────────────────────────

SIDEBAR_WIDTH = "220px"
SIDEBAR_STYLE = {
    "position": "fixed",
    "top": 0,
    "left": 0,
    "bottom": 0,
    "width": SIDEBAR_WIDTH,
    "padding": "20px 16px",
    "background-color": COLORS["card"],
    "border-right": f"1px solid {COLORS['border']}",
    "overflow-y": "auto",
    "z-index": 1000,
}

CONTENT_STYLE = {
    "margin-left": SIDEBAR_WIDTH,
    "min-height": "100vh",
    "background-color": "#f5f7fa",
    "padding": "24px",
}

# ─────────────────────────────────────────────
# CONFIGURACIÓN DE TIPOGRAFÍA
# ─────────────────────────────────────────────

TYPOGRAPHY = {
    "h1": {"fontSize": "2.5rem", "fontWeight": 700, "color": COLORS["text"]},
    "h2": {"fontSize": "2rem", "fontWeight": 700, "color": COLORS["text"]},
    "h3": {"fontSize": "1.5rem", "fontWeight": 700, "color": COLORS["text"]},
    "h4": {"fontSize": "1.25rem", "fontWeight": 600, "color": COLORS["text"]},
    "h5": {"fontSize": "1rem", "fontWeight": 600, "color": COLORS["accent"]},
    "h6": {"fontSize": "0.875rem", "fontWeight": 600, "color": COLORS["text_dim"]},
    "body": {"fontSize": "0.875rem", "color": COLORS["text"]},
    "caption": {"fontSize": "0.75rem", "color": COLORS["text_dim"]},
}

# ─────────────────────────────────────────────
# ICONOS Y SÍMBOLOS
# ─────────────────────────────────────────────

ICONS = {
    "home": "🏠",
    "chart": "📊",
    "portfolio": "📦",
    "sensitivity": "🎲",
    "pareto": "🧬",
    "competitive": "💹",
    "ablation": "🔬",
    "data": "📈",
    "pipeline": "🔧",
    "success": "✅",
    "error": "❌",
    "warning": "⚠️",
    "info": "ℹ️",
    "star": "⭐",
    "rocket": "🚀",
    "fire": "🔥",
    "money": "💰",
    "target": "🎯",
}

# ─────────────────────────────────────────────
# MENSAJES Y TEXTOS
# ─────────────────────────────────────────────

MESSAGES = {
    "loading": "Cargando datos...",
    "error": "Error al cargar los datos",
    "no_data": "No hay datos disponibles",
    "success": "Datos cargados exitosamente",
}

# ─────────────────────────────────────────────
# CONFIGURACIÓN DE APLICACIÓN
# ─────────────────────────────────────────────

APP_CONFIG = {
    "title": "HDS-ROI v5.0",
    "subtitle": "Dashboard de Optimización de Portafolio Dropshipping",
    "version": "5.0",
    "author": "Proyecto de Tesis",
    "year": 2026,
    "debug": True,
    "host": "127.0.0.1",
    "port": 8050,
}
