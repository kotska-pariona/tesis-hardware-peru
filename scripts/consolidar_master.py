# scripts/consolidar_master.py
import pandas as pd
import glob
import os

print("=" * 60)
print("  CONSOLIDADOR MASTER — HDS-ROI v6.0")
print("=" * 60)

dfs = []

# 1. Cargar MASTER actual (el más grande que tienes)
master_path = "data/raw/MASTER_hardware_peru.csv"
if os.path.exists(master_path):
    df_master = pd.read_csv(master_path, low_memory=False)
    print(f"✅ MASTER actual     : {len(df_master):>10,} registros ({os.path.getsize(master_path)//1024//1024} MB)")
    dfs.append(df_master)

# 2. Cargar todos los batch_24h_*.csv
batch_files = sorted(glob.glob("data/raw/batch_24h_*.csv"))
print(f"\n📂 Batches 24h encontrados: {len(batch_files)}")
for f in batch_files:
    try:
        df_b = pd.read_csv(f, low_memory=False)
        fecha = os.path.basename(f).replace("batch_24h_","").replace(".csv","")
        print(f"  {fecha}: {len(df_b):>8,} registros")
        dfs.append(df_b)
    except Exception as e:
        print(f"  ⚠️  Error en {f}: {e}")

# 3. Cargar batches individuales de agosto (los que no están en 24h)
batch_ind = sorted(glob.glob("data/raw/batch_2026080*_*.csv"))
print(f"\n📂 Batches agosto encontrados: {len(batch_ind)}")
for f in batch_ind:
    try:
        df_b = pd.read_csv(f, low_memory=False)
        print(f"  {os.path.basename(f)}: {len(df_b):>8,} registros")
        dfs.append(df_b)
    except Exception as e:
        print(f"  ⚠️  Error en {f}: {e}")

# 4. Consolidar todo
print(f"\n🔄 Consolidando {len(dfs)} fuentes...")
df_total = pd.concat(dfs, ignore_index=True)
print(f"   Total bruto: {len(df_total):,} registros")

# 5. Deduplicar
# Columnas clave para deduplicación
dup_cols = []
for col in ['sku', 'title', 'source', 'price_date']:
    if col in df_total.columns:
        dup_cols.append(col)

if dup_cols:
    antes = len(df_total)
    df_total = df_total.drop_duplicates(subset=dup_cols, keep='last')
    print(f"   Duplicados eliminados: {antes - len(df_total):,}")
    print(f"   Total único: {len(df_total):,}")
else:
    df_total = df_total.drop_duplicates(keep='last')
    print(f"   Total único (sin cols clave): {len(df_total):,}")

# 6. Verificar cobertura temporal
if 'price_date' in df_total.columns:
    df_total['price_date'] = pd.to_datetime(df_total['price_date'], errors='coerce')
    print(f"\n📅 Rango temporal:")
    print(f"   Desde : {df_total['price_date'].min()}")
    print(f"   Hasta : {df_total['price_date'].max()}")
    dias = (df_total['price_date'].max() - df_total['price_date'].min()).days
    print(f"   Días  : {dias}")

# 7. Registros por fuente
if 'source' in df_total.columns:
    print(f"\n🏪 Por fuente:")
    for src, cnt in df_total['source'].value_counts().items():
        print(f"   {src:<20}: {cnt:>8,}")

# 8. Meta OE1
meta = 1_500_000
pct = len(df_total) / meta * 100
print(f"\n🎯 Meta OE1: {meta:,}")
print(f"   Actual : {len(df_total):,} ({pct:.1f}%)")
print(f"   Estado : {'✅ CUMPLE' if len(df_total) >= meta else f'⚠️ Faltan {meta-len(df_total):,}'}")

# 9. Guardar MASTER consolidado
output = "data/raw/MASTER_hardware_peru_CONSOLIDADO.csv"
df_total.to_csv(output, index=False)
size_mb = os.path.getsize(output) // 1024 // 1024
print(f"\n✅ MASTER consolidado guardado:")
print(f"   {output}")
print(f"   {len(df_total):,} registros | {size_mb} MB")

# 10. Si el consolidado es mayor, reemplazar el MASTER
if len(df_total) > len(df_master):
    import shutil
    shutil.copy(output, master_path)
    print(f"\n✅ MASTER principal actualizado: {master_path}")
    print(f"   {len(df_master):,} → {len(df_total):,} registros (+{len(df_total)-len(df_master):,})")
else:
    print(f"\n⚠️  El consolidado ({len(df_total):,}) no supera al MASTER actual ({len(df_master):,})")
    print(f"   Revisar manualmente antes de reemplazar")
