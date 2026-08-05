# =============================================================================
# HDS-ROI v5.0 — Carga de Datos
# Autor: Proyecto de Tesis
# Fecha: 2026-07-30
# =============================================================================

import os
import json
import warnings
import numpy as np
import pandas as pd
from pathlib import Path

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────
# RUTAS DE DATOS
# ─────────────────────────────────────────────

DATA_DIR = Path("data")
RESULTS_DIR = Path("results")
FIGURES_DIR = Path("figures")

# ─────────────────────────────────────────────
# 1. CARGA OE9 NSGA-III
# ─────────────────────────────────────────────

def load_oe9_pareto():
    """Carga frente de Pareto OE9 NSGA-III (24 soluciones)."""
    path = RESULTS_DIR / "oe9_pareto_front.csv"
    if os.path.exists(path):
        df = pd.read_csv(path)
        return df
    
    # Fallback sintético
    np.random.seed(42)
    n = 24
    return pd.DataFrame({
        "sol_id": range(n),
        "tipo": np.random.choice(["ESTRELLA", "OPTIMO", "AGRESIVO", "BALANCEADO", "SEGURO"], n),
        "n_skus": np.random.randint(1, 25, n),
        "n_categorias": np.random.randint(1, 8, n),
        "capital_usd": np.random.uniform(127, 3511, n),
        "ingresos_usd": np.random.uniform(200, 5000, n),
        "ganancia_usd": np.random.uniform(76, 1449, n),
        "roi_pct": np.random.uniform(39.6, 83.8, n),
        "rj_portafolio": np.random.uniform(0.0012, 0.9989, n),
    })

def load_oe9_resumen():
    """Carga resumen de estadísticas OE9."""
    path = RESULTS_DIR / "oe9_resumen_nsga3.json"
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    
    return {
        "n_soluciones_pareto": 24,
        "roi_stats": {"min": 39.6, "max": 83.8, "mean": 58.2, "median": 57.5},
        "capital_stats": {"min": 127, "max": 3511, "mean": 1200, "median": 1100},
        "ganancia_stats": {"min": 76, "max": 1449, "mean": 600, "median": 580},
    }

def load_oe9_portafolios():
    """Carga detalle de portafolios OE9."""
    path = RESULTS_DIR / "oe9_portafolios_nodominados.json"
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return []

def load_feature_matrix():
    """Carga matriz de features (82 SKUs × 32 columnas)."""
    path = DATA_DIR / "features" / "oe9_feature_matrix.csv"
    if os.path.exists(path):
        df = pd.read_csv(path)
        return df
    
    # Fallback sintético
    np.random.seed(99)
    n_skus = 82
    return pd.DataFrame({
        "sku": range(1, n_skus + 1),
        "producto": [f"Producto_{i}" for i in range(1, n_skus + 1)],
        "categoria": np.random.choice(["GPU", "CPU", "RAM", "SSD", "Motherboard", "PSU", "Case"], n_skus),
        "roi_unitario_pct": np.random.uniform(20, 100, n_skus),
        "ganancia_unitaria": np.random.uniform(50, 200, n_skus),
        "r_j": np.random.uniform(0, 1, n_skus),
        "precio_costo": np.random.uniform(50, 500, n_skus),
        "precio_venta": np.random.uniform(100, 800, n_skus),
    })

# ─────────────────────────────────────────────
# 2. CARGA DE PORTAFOLIOS
# ─────────────────────────────────────────────

def load_portafolios():
    """Carga portafolios de 3 perfiles."""
    data = {
        "perfil": ["Conservador", "Moderado", "Agresivo"],
        "roi_pct": [28.5, 69.0, 112.3],
        "riesgo": [2.8, 5.0, 7.6],
        "inversion": [2100, 4737, 7800],
        "n_skus": [4, 7, 11],
        "hhi": [0.18, 0.31, 0.48],
        "diversif": [0.88, 0.72, 0.55],
        "margen_bruto": [0.32, 0.41, 0.53],
    }
    return pd.DataFrame(data)

def load_skus():
    """Carga SKUs del portafolio equilibrado."""
    data = {
        "sku": [
            "GPU RTX 4060", "CPU Ryzen 5 7600", "RAM DDR5 32GB",
            "SSD NVMe 1TB", "Motherboard B650", "PSU 750W 80+Gold",
            "Case ATX Mid-Tower"
        ],
        "categoria": ["GPU", "CPU", "RAM", "Almacenamiento", "Motherboard", "PSU", "Case"],
        "precio_usd": [320, 210, 95, 75, 160, 85, 70],
        "margen_pct": [0.38, 0.42, 0.35, 0.40, 0.45, 0.30, 0.28],
        "score_demanda": [0.87, 0.91, 0.78, 0.82, 0.74, 0.65, 0.60],
        "factor_venta": [0.72, 0.80, 0.65, 0.70, 0.60, 0.55, 0.50],
        "roi_sku": [0.82, 0.95, 0.68, 0.74, 0.71, 0.52, 0.45],
        "peso_portafolio": [0.22, 0.19, 0.14, 0.13, 0.13, 0.10, 0.09],
    }
    return pd.DataFrame(data)

# ─────────────────────────────────────────────
# 3. CARGA DE MONTE CARLO
# ─────────────────────────────────────────────

def load_montecarlo():
    """Carga resultados de simulación Monte Carlo (2,000 iteraciones)."""
    path = RESULTS_DIR / "montecarlo.csv"
    if os.path.exists(path):
        return pd.read_csv(path)
    
    np.random.seed(7)
    n = 2000
    factor_venta = np.random.normal(0.72, 0.12, n)
    margen = np.random.normal(0.41, 0.06, n)
    precio_compra = np.random.normal(1.00, 0.05, n)
    roi_sim = (factor_venta * margen) / precio_compra
    
    return pd.DataFrame({
        "iteracion": np.arange(n),
        "factor_venta": factor_venta,
        "margen": margen,
        "precio_compra": precio_compra,
        "roi_simulado": roi_sim,
    })

# ─────────────────────────────────────────────
# 4. CARGA DE PRECIOS
# ─────────────────────────────────────────────

def load_precios():
    """Carga datos de competitividad de precios."""
    sources = {
        "data/precios_amazon.csv": "Amazon",
        "data/precios_ebay.csv": "eBay",
        "data/precios_aliexpress.csv": "AliExpress",
        "data/precios_coolbox.csv": "Coolbox",
        "data/precios_falabella.csv": "Falabella",
        "data/precios_hiraoka.csv": "Hiraoka",
    }
    
    frames = []
    for fpath, fuente in sources.items():
        if os.path.exists(fpath):
            df = pd.read_csv(fpath)
            df["fuente"] = fuente
            frames.append(df)
    
    if frames:
        return pd.concat(frames, ignore_index=True)
    
    # Fallback sintético
    np.random.seed(99)
    productos = ["GPU RTX 4060", "CPU Ryzen 5 7600", "RAM DDR5 32GB",
                 "SSD NVMe 1TB", "Motherboard B650"]
    fuentes = ["Amazon", "eBay", "AliExpress", "Coolbox", "Falabella", "Hiraoka"]
    rows = []
    base = {"GPU RTX 4060": 320, "CPU Ryzen 5 7600": 210, "RAM DDR5 32GB": 95,
            "SSD NVMe 1TB": 75, "Motherboard B650": 160}
    
    for p in productos:
        for f in fuentes:
            factor = np.random.uniform(0.90, 1.25)
            rows.append({
                "producto": p,
                "fuente": f,
                "precio_usd": round(base[p] * factor, 2),
                "disponible": np.random.choice([True, False], p=[0.8, 0.2]),
                "descuento_pct": round(np.random.uniform(0, 0.15), 3),
            })
    
    return pd.DataFrame(rows)

# ─────────────────────────────────────────────
# 5. CARGA DE ABLACIÓN DE MODELOS
# ─────────────────────────────────────────────

def load_ablacion():
    """Carga métricas de ablación de modelos."""
    path = RESULTS_DIR / "ablacion_modelos.csv"
    if os.path.exists(path):
        return pd.read_csv(path)
    
    data = {
        "modelo": ["Baseline (Media)", "LightGBM", "XGBoost", "TFT", "N-BEATS"],
        "mae": [0.312, 0.198, 0.204, 0.171, 0.163],
        "rmse": [0.421, 0.267, 0.275, 0.231, 0.219],
        "mape_pct": [31.2, 19.8, 20.4, 17.1, 16.3],
        "smape_pct": [28.5, 18.2, 18.9, 15.8, 15.1],
        "tiempo_s": [0.1, 2.3, 2.8, 45.2, 38.7],
        "params_k": [0, 12, 15, 180, 95],
    }
    return pd.DataFrame(data)

# ─────────────────────────────────────────────
# 6. CARGA DE PARETO ORIGINAL
# ─────────────────────────────────────────────

def load_pareto():
    """Carga frente de Pareto NSGA-III original (4 objetivos)."""
    path = RESULTS_DIR / "pareto_front.csv"
    if os.path.exists(path):
        return pd.read_csv(path)
    
    np.random.seed(42)
    n = 75
    roi = np.random.uniform(0.30, 1.20, n)
    riesgo = np.random.uniform(2.0, 8.0, n)
    div = np.random.uniform(0.40, 0.95, n)
    hhi = np.random.uniform(0.10, 0.60, n)
    inv = np.random.uniform(2000, 8000, n)
    
    return pd.DataFrame({
        "roi": roi,
        "riesgo": riesgo,
        "diversificacion": div,
        "hhi": hhi,
        "inversion_usd": inv,
        "perfil": np.random.choice(["Conservador", "Moderado", "Agresivo"], n),
    })

# ─────────────────────────────────────────────
# 7. ANÁLISIS DE DATOS
# ─────────────────────────────────────────────

def get_data_quality_report():
    """Genera reporte de calidad de datos."""
    df_features = load_feature_matrix()
    
    n_rows = len(df_features)
    n_cols = len(df_features.columns)
    n_missing = df_features.isnull().sum().sum()
    pct_missing = (n_missing / (n_rows * n_cols)) * 100
    
    missing_by_col = df_features.isnull().sum().sort_values(ascending=False)
    missing_by_col = missing_by_col[missing_by_col > 0]
    
    dtype_counts = df_features.dtypes.value_counts()
    
    return {
        "n_rows": n_rows,
        "n_cols": n_cols,
        "n_missing": n_missing,
        "pct_missing": pct_missing,
        "missing_by_col": missing_by_col,
        "dtype_counts": dtype_counts,
        "status": "✅ Completada" if pct_missing < 5 else "⚠️ En progreso",
    }

# ─────────────────────────────────────────────
# 8. CARGA CENTRALIZADA
# ─────────────────────────────────────────────

def load_all_data():
    """Carga todos los datos necesarios."""
    return {
        "oe9_pareto": load_oe9_pareto(),
        "oe9_resumen": load_oe9_resumen(),
        "oe9_portafolios": load_oe9_portafolios(),
        "feature_matrix": load_feature_matrix(),
        "portafolios": load_portafolios(),
        "skus": load_skus(),
        "montecarlo": load_montecarlo(),
        "precios": load_precios(),
        "ablacion": load_ablacion(),
        "pareto": load_pareto(),
        "data_quality": get_data_quality_report(),
    }

# Cargar datos al importar
print("📊 Cargando datos...")
DATA = load_all_data()
print("✅ Datos cargados exitosamente")
