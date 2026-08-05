# config_v6.py - Configuración centralizada Dashboard v6.0

import os
from datetime import datetime

# ============ COLORES Y ESTILOS ============
COLORS = {
    "bg": "#ffffff",
    "card": "#f8f9fa",
    "text": "#2c3e50",
    "text_light": "#7f8c8d",
    "border": "#e0e6ed",
    "accent": "#3498db",      # Azul principal
    "accent2": "#2ecc71",     # Verde
    "accent3": "#f39c12",     # Naranja
    "danger": "#e74c3c",      # Rojo
    "success": "#27ae60",     # Verde oscuro
    "warning": "#f1c40f",     # Amarillo
    "info": "#16a085",        # Turquesa
}

THEME = {
    "primary": COLORS["accent"],
    "secondary": COLORS["accent2"],
    "danger": COLORS["danger"],
    "warning": COLORS["warning"],
}

# ============ ESTILOS GLOBALES ============
CONTENT_STYLE = {
    "marginLeft": "250px",
    "marginRight": "20px",
    "padding": "20px",
    "backgroundColor": "#f5f7fa",
    "minHeight": "100vh",
}

CARD_STYLE = {
    "backgroundColor": COLORS["card"],
    "border": f"1px solid {COLORS['border']}",
    "borderRadius": "8px",
    "padding": "20px",
    "marginBottom": "20px",
    "boxShadow": "0 2px 4px rgba(0,0,0,0.05)",
}

HEADER_STYLE = {
    "color": COLORS["text"],
    "marginBottom": "20px",
    "fontSize": "28px",
    "fontWeight": "700",
}

SUBHEADER_STYLE = {
    "color": COLORS["text_light"],
    "marginBottom": "15px",
    "fontSize": "14px",
    "fontWeight": "500",
}

# ============ DATOS ESTÁTICOS v6.0 ============
MODELOS_TOP = {
    "AGRESIVO": {
        "roi": 83.8,
        "r_j": 0.9989,
        "capital": 144,
        "ganancia": 120,
        "tipo": "Agresivo",
        "riesgo": "ALTO",
    },
    "ESTRELLA": {
        "roi": 60.1,
        "r_j": 0.0013,
        "capital": 127,
        "ganancia": 76,
        "tipo": "Estrella",
        "riesgo": "BAJO",
    },
    "OPTIMO": {
        "roi": 65.4,
        "r_j": 0.0089,
        "capital": 1802,
        "ganancia": 1180,
        "tipo": "Óptimo",
        "riesgo": "BAJO",
    },
    "BALANCEADO": {
        "roi": 55.2,
        "r_j": 0.3456,
        "capital": 892,
        "ganancia": 492,
        "tipo": "Balanceado",
        "riesgo": "MEDIO",
    },
    "SEGURO": {
        "roi": 42.1,
        "r_j": 0.0045,
        "capital": 2150,
        "ganancia": 906,
        "tipo": "Seguro",
        "riesgo": "BAJO",
    },
}

SKUS_DETALLADOS = [
    {
        "sku": "SKU001",
        "producto": "Laptop ASUS VivoBook",
        "categoria": "Electrónica",
        "precio": 599,
        "margen": 18.5,
        "roi": 72.3,
        "score_demanda": 8.5,
        "factor_venta": 0.92,
        "peso": 2.1,
    },
    {
        "sku": "SKU002",
        "producto": "Mouse Logitech MX",
        "categoria": "Accesorios",
        "precio": 99,
        "margen": 35.2,
        "roi": 58.9,
        "score_demanda": 7.2,
        "factor_venta": 0.88,
        "peso": 0.15,
    },
    {
        "sku": "SKU003",
        "producto": "Monitor LG 27 4K",
        "categoria": "Electrónica",
        "precio": 349,
        "margen": 22.1,
        "roi": 65.4,
        "score_demanda": 8.9,
        "factor_venta": 0.95,
        "peso": 5.8,
    },
    {
        "sku": "SKU004",
        "producto": "Teclado Mecánico RGB",
        "categoria": "Accesorios",
        "precio": 129,
        "margen": 40.5,
        "roi": 83.8,
        "score_demanda": 9.1,
        "factor_venta": 0.97,
        "peso": 0.9,
    },
    {
        "sku": "SKU005",
        "producto": "Webcam Logitech 4K",
        "categoria": "Accesorios",
        "precio": 149,
        "margen": 28.3,
        "roi": 55.2,
        "score_demanda": 6.8,
        "factor_venta": 0.82,
        "peso": 0.3,
    },
    {
        "sku": "SKU006",
        "producto": "Auriculares Sony WH-1000",
        "categoria": "Audio",
        "precio": 349,
        "margen": 25.7,
        "roi": 60.1,
        "score_demanda": 8.2,
        "factor_venta": 0.91,
        "peso": 0.25,
    },
    {
        "sku": "SKU007",
        "producto": "Hub USB-C 7 Puertos",
        "categoria": "Accesorios",
        "precio": 79,
        "margen": 42.1,
        "roi": 42.1,
        "score_demanda": 5.4,
        "factor_venta": 0.75,
        "peso": 0.2,
    },
]

FUENTES_SCRAPING = [
    {"fuente": "Amazon", "skus": 14, "porcentaje": 17.1, "estado": "✅"},
    {"fuente": "eBay", "skus": 13, "porcentaje": 15.9, "estado": "✅"},
    {"fuente": "AliExpress", "skus": 14, "porcentaje": 17.1, "estado": "✅"},
    {"fuente": "Coolbox", "skus": 13, "porcentaje": 15.9, "estado": "✅"},
    {"fuente": "Falabella", "skus": 14, "porcentaje": 17.1, "estado": "✅"},
    {"fuente": "Hiraoka", "skus": 14, "porcentaje": 17.1, "estado": "✅"},
]

# ============ RUTAS Y DIRECTORIOS ============
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

# Crear directorios si no existen
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)

# ============ CONFIGURACIÓN DE LA APP ============
APP_NAME = "HDS-ROI v6.0"
APP_VERSION = "6.0.0"
LAST_UPDATE = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

DEBUG = True
PORT = 8050
HOST = "127.0.0.1"
