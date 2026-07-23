
import pandas as pd
import numpy as np
import os
import glob

print("=" * 60)
print("🔍 DIAGNÓSTICO COMPLETO DEL DATASET")
print("=" * 60)

# ── 1. BUSCAR ARCHIVOS CSV/EXCEL EN EL PROYECTO ──────────────
print("\n📁 ARCHIVOS ENCONTRADOS EN EL PROYECTO:")
print("-" * 40)

extensions = ["*.csv", "*.xlsx", "*.xls", "*.parquet", "*.json"]
found_files = []

for ext in extensions:
    files = glob.glob(f"**/{ext}", recursive=True) + glob.glob(ext)
    for f in files:
        if "models/" not in f:  # excluir carpeta models
            size_mb = os.path.getsize(f) / (1024 * 1024)
            found_files.append((f, size_mb))
            print(f"  📄 {f}  ({size_mb:.2f} MB)")

if not found_files:
    print("  ⚠️  No se encontraron archivos de datos")
    print("  → Busca manualmente tu archivo principal")

# ── 2. CARGAR EL ARCHIVO PRINCIPAL ───────────────────────────
print("\n" + "=" * 60)
print("📊 ANÁLISIS DEL DATASET PRINCIPAL")
print("=" * 60)

# Intenta cargar el archivo más grande (probablemente el principal)
if found_files:
    main_file = sorted(found_files, key=lambda x: x[1], reverse=True)[0][0]
    print(f"\n→ Analizando: {main_file}")
    
    try:
        if main_file.endswith(".csv"):
            df = pd.read_csv(main_file, low_memory=False)
        elif main_file.endswith((".xlsx", ".xls")):
            df = pd.read_excel(main_file)
        elif main_file.endswith(".parquet"):
            df = pd.read_parquet(main_file)
        
        # ── INFORMACIÓN BÁSICA ────────────────────────────────
        print(f"\n📐 DIMENSIONES: {df.shape[0]:,} filas × {df.shape[1]} columnas")
        print(f"💾 Memoria: {df.memory_usage(deep=True).sum() / 1024**2:.2f} MB")
        
        # ── COLUMNAS Y TIPOS ──────────────────────────────────
        print("\n📋 COLUMNAS Y TIPOS DE DATOS:")
        print("-" * 50)
        for col in df.columns:
            dtype = str(df[col].dtype)
            nulls = df[col].isnull().sum()
            null_pct = (nulls / len(df)) * 100
            unique = df[col].nunique()
            print(f"  {col:<35} {dtype:<12} "
                  f"nulls={null_pct:.1f}%  unique={unique:,}")
        
        # ── COLUMNAS DE FECHA ─────────────────────────────────
        print("\n📅 DETECCIÓN DE COLUMNAS TEMPORALES:")
        print("-" * 50)
        date_keywords = ["fecha", "date", "time", "created", 
                        "updated", "timestamp", "año", "mes", "dia"]
        date_cols = []
        for col in df.columns:
            if any(kw in col.lower() for kw in date_keywords):
                date_cols.append(col)
                sample = df[col].dropna().iloc[0] if len(df[col].dropna()) > 0 else "N/A"
                print(f"  ✅ {col}: ejemplo → {sample}")
        
        if not date_cols:
            print("  ⚠️  No se detectaron columnas de fecha automáticamente")
            print("  → Revisa manualmente las columnas listadas arriba")
        
        # ── COLUMNAS DE ID/SKU ────────────────────────────────
        print("\n🏷️  DETECCIÓN DE COLUMNAS ID/SKU:")
        print("-" * 50)
        id_keywords = ["id", "sku", "codigo", "code", "producto", 
                      "product", "item", "modelo", "model"]
        for col in df.columns:
            if any(kw in col.lower() for kw in id_keywords):
                n_unique = df[col].nunique()
                print(f"  ✅ {col}: {n_unique:,} valores únicos")
        
        # ── COLUMNAS NUMÉRICAS ────────────────────────────────
        print("\n🔢 COLUMNAS NUMÉRICAS (estadísticas):")
        print("-" * 50)
        num_cols = df.select_dtypes(include=[np.number]).columns
        if len(num_cols) > 0:
            print(df[num_cols].describe().round(2).to_string())
        
        # ── MUESTRA DE DATOS ──────────────────────────────────
        print("\n👀 PRIMERAS 3 FILAS:")
        print("-" * 50)
        print(df.head(3).to_string())
        
        # ── RESUMEN PARA PE2 ──────────────────────────────────
        print("\n" + "=" * 60)
        print("🎯 RESUMEN PARA DECISIÓN PE2")
        print("=" * 60)
        print(f"  Filas totales    : {df.shape[0]:,}")
        print(f"  Columnas         : {df.shape[1]}")
        print(f"  Cols temporales  : {len(date_cols)} → {date_cols}")
        print(f"  Cols numéricas   : {len(num_cols)}")
        
        has_dates = len(date_cols) > 0
        has_ids   = any(kw in col.lower() 
                       for col in df.columns 
                       for kw in ["id", "sku", "codigo", "producto"])
        
        print("\n  ¿Tiene fechas?   :", "✅ SÍ" if has_dates else "❌ NO")
        print("  ¿Tiene IDs/SKU?  :", "✅ SÍ" if has_ids else "❌ NO")
        
        if has_dates and has_ids:
            print("\n  🟢 VIABLE para TFT con datos propios")
        elif has_dates:
            print("\n  🟡 PARCIALMENTE viable - falta columna ID/SKU")
        else:
            print("\n  🔴 Necesitamos revisar estrategia PE2")
            
    except Exception as e:
        print(f"  ❌ Error al cargar: {e}")
else:
    print("\n❌ No se encontraron archivos")
    print("   Indica la ruta de tu dataset manualmente")
    print("   Ejemplo: df = pd.read_csv('ruta/a/tu/archivo.csv')")

print("\n" + "=" * 60)
print("✅ DIAGNÓSTICO COMPLETADO")
print("=" * 60)
