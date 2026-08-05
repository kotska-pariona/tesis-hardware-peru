# utils_v6.py - Utilidades para Dashboard v6.0

import pandas as pd
import numpy as np
from config_v6 import MODELOS_TOP, SKUS_DETALLADOS, FUENTES_SCRAPING

def get_top_modelos():
    """Retorna los 5 modelos top ordenados por ROI"""
    modelos = []
    for nombre, datos in MODELOS_TOP.items():
        modelos.append({
            "modelo": nombre,
            "roi": datos["roi"],
            "r_j": datos["r_j"],
            "capital": datos["capital"],
            "ganancia": datos["ganancia"],
            "riesgo": datos["riesgo"],
        })
    return sorted(modelos, key=lambda x: x["roi"], reverse=True)

def get_mejor_roi():
    """Retorna el modelo con mejor ROI absoluto"""
    modelos = get_top_modelos()
    return modelos[0] if modelos else None

def get_mejor_balance():
    """Retorna el modelo con mejor balance ROI/Riesgo"""
    modelos = get_top_modelos()
    mejor = max(modelos, key=lambda x: x["roi"] / (x["r_j"] + 0.001))
    return mejor

def get_mejor_eficiencia():
    """Retorna el modelo con mejor eficiencia (ROI/Capital)"""
    modelos = get_top_modelos()
    mejor = max(modelos, key=lambda x: x["roi"] / (x["capital"] + 1))
    return mejor

def get_skus_dataframe():
    """Retorna DataFrame con SKUs detallados"""
    return pd.DataFrame(SKUS_DETALLADOS)

def get_fuentes_dataframe():
    """Retorna DataFrame con fuentes de scraping"""
    return pd.DataFrame(FUENTES_SCRAPING)

def calcular_simulador(presupuesto, modelo_roi, capital_unitario):
    """
    Calcula simulación de compra
    
    Args:
        presupuesto: Presupuesto total disponible
        modelo_roi: ROI del modelo en %
        capital_unitario: Capital requerido por unidad
    
    Returns:
        dict con unidades, ganancia total, ROI total
    """
    unidades = int(presupuesto / capital_unitario)
    capital_total = unidades * capital_unitario
    ganancia_unitaria = capital_unitario * (modelo_roi / 100)
    ganancia_total = unidades * ganancia_unitaria
    roi_total = (ganancia_total / capital_total * 100) if capital_total > 0 else 0
    
    return {
        "unidades": unidades,
        "capital_total": capital_total,
        "ganancia_unitaria": ganancia_unitaria,
        "ganancia_total": ganancia_total,
        "roi_total": roi_total,
    }

def clasificar_riesgo(r_j):
    """Clasifica el nivel de riesgo según r_j"""
    if r_j < 0.3:
        return "🟢 BAJO"
    elif r_j < 0.7:
        return "🟡 MEDIO"
    else:
        return "🔴 ALTO"

def generar_reporte_datos():
    """Genera reporte de datos de scraping y entrenamiento"""
    total_skus = 82
    entrenamiento = int(total_skus * 0.60)
    validacion = int(total_skus * 0.20)
    test = total_skus - entrenamiento - validacion
    
    return {
        "total_scrapeado": total_skus,
        "entrenamiento": entrenamiento,
        "validacion": validacion,
        "test": test,
        "porcentaje_entrenamiento": 60,
        "porcentaje_validacion": 20,
        "porcentaje_test": 20,
    }

def generar_matriz_riesgo():
    """Genera matriz de riesgo ROI vs r_j"""
    modelos = get_top_modelos()
    datos = []
    
    for modelo in modelos:
        datos.append({
            "Modelo": modelo["modelo"],
            "ROI (%)": modelo["roi"],
            "r_j": modelo["r_j"],
            "Capital ($)": modelo["capital"],
            "Riesgo": clasificar_riesgo(modelo["r_j"]),
        })
    
    return pd.DataFrame(datos)

def generar_recomendaciones():
    """Genera 3 recomendaciones finales de compra"""
    mejor_roi = get_mejor_roi()
    mejor_balance = get_mejor_balance()
    mejor_eficiencia = get_mejor_eficiencia()
    
    return {
        "opcion_1": {
            "titulo": "🔥 MÁXIMO ROI (Agresivo)",
            "modelo": mejor_roi["modelo"],
            "roi": mejor_roi["roi"],
            "capital": mejor_roi["capital"],
            "ganancia": mejor_roi["ganancia"],
            "riesgo": mejor_roi["riesgo"],
            "r_j": mejor_roi["r_j"],
            "para": "Inversionistas con tolerancia al riesgo",
        },
        "opcion_2": {
            "titulo": "⚖️ MEJOR BALANCE (Recomendado)",
            "modelo": mejor_balance["modelo"],
            "roi": mejor_balance["roi"],
            "capital": mejor_balance["capital"],
            "ganancia": mejor_balance["ganancia"],
            "riesgo": mejor_balance["riesgo"],
            "r_j": mejor_balance["r_j"],
            "para": "Mayoría de inversionistas",
        },
        "opcion_3": {
            "titulo": "💎 MÁXIMA EFICIENCIA",
            "modelo": mejor_eficiencia["modelo"],
            "roi": mejor_eficiencia["roi"],
            "capital": mejor_eficiencia["capital"],
            "ganancia": mejor_eficiencia["ganancia"],
            "riesgo": mejor_eficiencia["riesgo"],
            "r_j": mejor_eficiencia["r_j"],
            "para": "Inversionistas con presupuesto limitado",
        },
    }

def formatear_moneda(valor):
    """Formatea valor como moneda USD"""
    return f"${valor:,.2f}"

def formatear_porcentaje(valor):
    """Formatea valor como porcentaje"""
    return f"{valor:.1f}%"
