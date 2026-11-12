#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
optimize_portfolio_simple.py
============================
Optimizador de portafolio simplificado para HDS-ROI v6.2

Recibe un presupuesto por línea de comandos y genera un portafolio óptimo
distribuyendo el capital entre los productos más rentables del dataset.

Uso:
    python scripts/optimize_portfolio_simple.py 5000

Salida:
    results/portfolio_optimizado.json

Autor: HDS-ROI Team
Fecha: 2026-10-14
"""

import sys
import json
import warnings
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════════════

TIPO_CAMBIO_PEN = 3.75  # PEN/USD

# Unidades máximas por tipo de hardware (diversificación realista)
UNIDADES_MAX_HW = {
    "gpu":         3,
    "cpu":         5,
    "ram":         8,
    "ssd":         6,
    "hdd":         4,
    "motherboard": 3,
    "psu":         4,
    "case":        3,
    "cooler":      4,
    "monitor":     2,
    "laptop":      2,
    "otro":        3,
}

# Máximo de SKUs diferentes por tipo de hardware
MAX_SKUS_POR_HW = 2

# Porcentaje máximo del presupuesto para un solo producto
MAX_PCT_CAPITAL_POR_PRODUCTO = 0.25

# ═══════════════════════════════════════════════════════════════════════════
# FUNCIONES AUXILIARES
# ═══════════════════════════════════════════════════════════════════════════

def cargar_datos_prediccion():
    """
    Carga el archivo de predicciones multihorizonte.
    
    Returns:
        dict: Datos de predicciones con estructura {skus: {...}, resumen: {...}}
    """
    path = Path("results/predicciones_multihorizonte.json")
    
    if not path.exists():
        print(f"❌ ERROR: No se encuentra {path}")
        print("   Ejecuta primero: python scripts/pe2_multihorizonte.py")
        sys.exit(1)
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except json.JSONDecodeError as e:
        print(f"❌ ERROR: Archivo JSON corrupto: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ ERROR al cargar datos: {e}")
        sys.exit(1)


def extraer_productos(skus_data):
    """
    Extrae productos válidos del dataset de predicciones.
    
    Args:
        skus_data (dict): Diccionario de SKUs con oportunidades
    
    Returns:
        pd.DataFrame: DataFrame con productos válidos y sus métricas
    """
    productos = []
    
    for sku_key, info in skus_data.items():
        try:
            op = info.get("oportunidad", {})
            
            # Validar datos mínimos
            precio_compra = float(op.get("precio_compra_usd", 0) or 0)
            precio_venta  = float(op.get("precio_venta_usd", 0) or 0)
            roi_pct       = float(op.get("roi_pct", 0) or 0)
            
            if precio_compra <= 0 or precio_venta <= 0 or roi_pct <= 0:
                continue
            
            # Calcular métricas
            ganancia_usd = precio_venta - precio_compra
            margen_pen   = ganancia_usd * TIPO_CAMBIO_PEN
            
            # Extraer metadatos
            titulo    = info.get("title", sku_key)[:100]
            source    = info.get("source", "unknown")
            category  = info.get("category", "otro")
            hw_type   = info.get("hw_type", op.get("hw_type", "otro"))
            brand     = info.get("brand", "Generic")
            url       = info.get("url", "#")
            accion    = op.get("accion", "EVALUAR")
            score     = float(op.get("score_oportunidad", 0) or 0)
            
            # Predicción H+7d
            pred_7d = info.get("predicciones", {}).get("7", {})
            tendencia = pred_7d.get("tendencia", "ESTABLE")
            var_7d    = float(pred_7d.get("variacion_pct", 0) or 0)
            
            productos.append({
                "sku":              sku_key,
                "name":             titulo,
                "brand":            brand,
                "source":           source,
                "category":         category,
                "hw_type":          hw_type,
                "url":              url,
                "precio_compra_usd": precio_compra,
                "precio_venta_usd":  precio_venta,
                "precio_venta_pen":  precio_venta * TIPO_CAMBIO_PEN,
                "ganancia_usd":      ganancia_usd,
                "margen_pen":        margen_pen,
                "roi_pct":           roi_pct,
                "accion":            accion,
                "score_oportunidad": score,
                "tendencia_7d":      tendencia,
                "variacion_7d_pct":  var_7d,
            })
        
        except Exception as e:
            # Saltar productos con errores de parsing
            continue
    
    if not productos:
        print("❌ ERROR: No se encontraron productos válidos en el dataset")
        sys.exit(1)
    
    df = pd.DataFrame(productos)
    print(f"✅ Cargados {len(df)} productos válidos del dataset")
    return df


def optimizar_portafolio(df, presupuesto):
    """
    Optimiza el portafolio distribuyendo el presupuesto entre productos.
    
    Estrategia:
    1. Ordenar por score de oportunidad (ROI + tendencia + rating)
    2. Priorizar por tipo de hardware (GPU > CPU > RAM > SSD...)
    3. Respetar límites de unidades por tipo
    4. Máximo 2 SKUs diferentes por tipo de hardware
    5. Máximo 25% del presupuesto por producto
    
    Args:
        df (pd.DataFrame): DataFrame con productos
        presupuesto (float): Presupuesto disponible en USD
    
    Returns:
        list: Lista de productos seleccionados con unidades
    """
    # Prioridad de tipos de hardware
    PRIORIDAD_HW = [
        "gpu", "cpu", "ram", "ssd", "motherboard",
        "psu", "monitor", "cooler", "laptop", "case", "hdd", "otro"
    ]
    
    # Ordenar por prioridad de HW y luego por score
    def hw_sort_key(row):
        hw = row["hw_type"]
        pri = PRIORIDAD_HW.index(hw) if hw in PRIORIDAD_HW else 99
        return (pri, -row["score_oportunidad"], -row["roi_pct"])
    
    df_sorted = df.copy()
    df_sorted["_sort_key"] = df_sorted.apply(hw_sort_key, axis=1)
    df_sorted = df_sorted.sort_values("_sort_key")
    
    # Inicializar variables
    presupuesto_restante = float(presupuesto)
    portafolio = []
    hw_incluidos = {}  # Contador de SKUs por tipo de hardware
    
    for _, row in df_sorted.iterrows():
        if presupuesto_restante < 10:
            break
        
        hw_type       = row["hw_type"]
        precio_compra = row["precio_compra_usd"]
        
        # Validar límite de SKUs por tipo de hardware
        if hw_incluidos.get(hw_type, 0) >= MAX_SKUS_POR_HW:
            continue
        
        # Calcular unidades máximas
        max_u_hw      = UNIDADES_MAX_HW.get(hw_type, 3)
        max_capital   = min(presupuesto_restante, presupuesto * MAX_PCT_CAPITAL_POR_PRODUCTO)
        u_por_capital = int(max_capital / precio_compra)
        unidades      = min(u_por_capital, max_u_hw)
        
        if unidades <= 0:
            continue
        
        # Calcular inversión y ganancia
        inversion_usd = unidades * precio_compra
        ganancia_usd  = unidades * row["ganancia_usd"]
        margen_pen    = unidades * row["margen_pen"]
        venta_pen     = unidades * row["precio_venta_pen"]
        
        # Agregar al portafolio
        portafolio.append({
            "sku":              row["sku"],
            "name":             row["name"],
            "brand":            row["brand"],
            "source":           row["source"],
            "category":         row["category"],
            "hw_type":          hw_type,
            "url":              row["url"],
            "precio_compra_usd": precio_compra,
            "precio_venta_usd":  row["precio_venta_usd"],
            "precio_venta_pen":  row["precio_venta_pen"],
            "ganancia_usd":      row["ganancia_usd"],
            "margen_pen":        row["margen_pen"],
            "roi_pct":           row["roi_pct"],
            "accion":            row["accion"],
            "score_oportunidad": row["score_oportunidad"],
            "tendencia_7d":      row["tendencia_7d"],
            "variacion_7d_pct":  row["variacion_7d_pct"],
            "unidades":          unidades,
            "inversion_usd":     inversion_usd,
            "ganancia_total_usd": ganancia_usd,
            "margen_total_pen":  margen_pen,
            "venta_total_pen":   venta_pen,
        })
        
        # Actualizar contadores
        presupuesto_restante -= inversion_usd
        hw_incluidos[hw_type] = hw_incluidos.get(hw_type, 0) + 1
    
    if not portafolio:
        print("❌ ERROR: No se pudo construir un portafolio con el presupuesto dado")
        sys.exit(1)
    
    return portafolio


def calcular_metricas_portafolio(portafolio, presupuesto):
    """
    Calcula métricas agregadas del portafolio.
    
    Args:
        portafolio (list): Lista de productos seleccionados
        presupuesto (float): Presupuesto original
    
    Returns:
        dict: Métricas del portafolio
    """
    inversion_total = sum(p["inversion_usd"] for p in portafolio)
    margen_total    = sum(p["margen_total_pen"] for p in portafolio)
    venta_total     = sum(p["venta_total_pen"] for p in portafolio)
    
    # ROI promedio ponderado por inversión
    if inversion_total > 0:
        roi_promedio = sum(
            p["roi_pct"] * (p["inversion_usd"] / inversion_total)
            for p in portafolio
        )
    else:
        roi_promedio = 0.0
    
    # Diversificación
    tipos_hw = set(p["hw_type"] for p in portafolio)
    num_productos = len(portafolio)
    
    # Índice Herfindahl-Hirschman (HHI) — concentración del portafolio
    if inversion_total > 0:
        hhi = sum((p["inversion_usd"] / inversion_total) ** 2 for p in portafolio)
    else:
        hhi = 1.0
    
    return {
        "presupuesto_usd":       presupuesto,
        "inversion_total_usd":   round(inversion_total, 2),
        "saldo_no_invertido_usd": round(presupuesto - inversion_total, 2),
        "margen_total_pen":      round(margen_total, 2),
        "venta_total_pen":       round(venta_total, 2),
        "roi_promedio_pct":      round(roi_promedio, 2),
        "num_productos":         num_productos,
        "num_tipos_hw":          len(tipos_hw),
        "tipos_hw":              sorted(list(tipos_hw)),
        "hhi":                   round(hhi, 4),
        "diversificacion_score": round(1 - hhi, 4),  # Inverso del HHI
    }


def guardar_resultado(portafolio, metricas):
    """
    Guarda el portafolio optimizado en JSON.
    
    Args:
        portafolio (list): Lista de productos seleccionados
        metricas (dict): Métricas del portafolio
    """
    output_path = Path("results/portfolio_optimizado.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    resultado = {
        "metadata": {
            "fecha_generacion": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "version":          "HDS-ROI v6.2",
            "optimizador":      "optimize_portfolio_simple.py",
        },
        **metricas,
        "productos": portafolio,
    }
    
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(resultado, f, indent=2, ensure_ascii=False)
        print(f"✅ Portafolio guardado en: {output_path}")
    except Exception as e:
        print(f"❌ ERROR al guardar resultado: {e}")
        sys.exit(1)


def imprimir_resumen(metricas, portafolio):
    """
    Imprime un resumen del portafolio optimizado.
    
    Args:
        metricas (dict): Métricas del portafolio
        portafolio (list): Lista de productos seleccionados
    """
    print("\n" + "=" * 80)
    print("  📊 RESUMEN DEL PORTAFOLIO OPTIMIZADO")
    print("=" * 80)
    print(f"  💵 Presupuesto:          ${metricas['presupuesto_usd']:,.2f} USD")
    print(f"  💰 Inversión Total:      ${metricas['inversion_total_usd']:,.2f} USD")
    print(f"  💸 Saldo No Invertido:   ${metricas['saldo_no_invertido_usd']:,.2f} USD")
    print(f"  📈 ROI Promedio:         {metricas['roi_promedio_pct']:.2f}%")
    print(f"  💵 Margen Total:         S/ {metricas['margen_total_pen']:,.2f} PEN")
    print(f"  🏪 Venta Total:          S/ {metricas['venta_total_pen']:,.2f} PEN")
    print(f"  📦 Productos:            {metricas['num_productos']}")
    print(f"  🔧 Tipos de Hardware:    {metricas['num_tipos_hw']} ({', '.join(metricas['tipos_hw'])})")
    print(f"  📊 HHI (Concentración):  {metricas['hhi']:.4f}")
    print(f"  🌈 Score Diversificación: {metricas['diversificacion_score']:.4f}")
    print("─" * 80)
    print("  🛒 TOP 10 PRODUCTOS:")
    print("─" * 80)
    
    for i, p in enumerate(portafolio[:10], 1):
        print(f"  {i:2d}. {p['name'][:50]:<50} | "
              f"ROI: {p['roi_pct']:5.1f}% | "
              f"Unid: {p['unidades']:2d} | "
              f"Inv: ${p['inversion_usd']:7,.0f}")
    
    if len(portafolio) > 10:
        print(f"       ... y {len(portafolio) - 10} productos más")
    
    print("=" * 80 + "\n")


# ═══════════════════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════

def main():
    """
    Función principal del optimizador.
    """
    print("\n" + "=" * 80)
    print("  🚀 HDS-ROI v6.2 — Optimizador de Portafolio Simple")
    print("=" * 80 + "\n")
    
    # Validar argumentos
    if len(sys.argv) < 2:
        print("❌ ERROR: Falta el argumento de presupuesto")
        print("\nUso:")
        print("    python scripts/optimize_portfolio_simple.py <presupuesto_usd>")
        print("\nEjemplo:")
        print("    python scripts/optimize_portfolio_simple.py 5000")
        sys.exit(1)
    
    try:
        presupuesto = float(sys.argv[1])
    except ValueError:
        print(f"❌ ERROR: Presupuesto inválido: {sys.argv[1]}")
        print("   Debe ser un número (ej: 5000)")
        sys.exit(1)
    
    if presupuesto < 100:
        print(f"❌ ERROR: Presupuesto muy bajo: ${presupuesto:.2f}")
        print("   Mínimo recomendado: $1,000 USD")
        sys.exit(1)
    
    print(f"💵 Presupuesto disponible: ${presupuesto:,.2f} USD")
    print(f"💱 Tipo de cambio: S/ {TIPO_CAMBIO_PEN} PEN/USD\n")
    
    # Cargar datos
    print("📥 Cargando datos de predicciones...")
    data = cargar_datos_prediccion()
    skus_data = data.get("skus", {})
    
    if not skus_data:
        print("❌ ERROR: No hay datos de SKUs en el archivo de predicciones")
        sys.exit(1)
    
    print(f"✅ Encontrados {len(skus_data)} SKUs en el dataset\n")
    
    # Extraer productos válidos
    print("🔍 Extrayendo productos válidos...")
    df_productos = extraer_productos(skus_data)
    
    # Optimizar portafolio
    print(f"\n⚙️  Optimizando portafolio con presupuesto ${presupuesto:,.2f}...")
    portafolio = optimizar_portafolio(df_productos, presupuesto)
    
    # Calcular métricas
    print("📊 Calculando métricas del portafolio...")
    metricas = calcular_metricas_portafolio(portafolio, presupuesto)
    
    # Guardar resultado
    print("💾 Guardando resultado...")
    guardar_resultado(portafolio, metricas)
    
    # Imprimir resumen
    imprimir_resumen(metricas, portafolio)
    
    print("✅ Optimización completada exitosamente\n")
    return 0


# ═══════════════════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Proceso interrumpido por el usuario")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ ERROR CRÍTICO: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
