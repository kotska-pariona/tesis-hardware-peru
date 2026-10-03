import pandas as pd
import numpy as np

# Cargar datos
master = pd.read_csv('data/raw/MASTER_hardware_peru.csv', low_memory=False)
rj = pd.read_csv('results/obsolescencia_scores.csv')
matches = pd.read_csv('results/pe3b_matches.csv')

# Feature 1: rj_score por SKU
master = master.merge(
    rj[['sku','rj_score']],
    on='sku', how='left'
).fillna({'rj_score': 0.5})  # neutral si no hay score

# Feature 2: gap precio local vs importación
gap_map = matches.groupby('sku_local')['gap_pct'].mean()
master['gap_local_import'] = master['sku'].map(gap_map).fillna(0)

# Feature 3: volatilidad 7 días
master = master.sort_values(['sku','timestamp'])
master['volatilidad_7d'] = master.groupby('sku')['price_usd']\
    .transform(lambda x: x.rolling(7).std() / x.rolling(7).mean())

print(f"Features agregadas: rj_score, gap_local_import, volatilidad_7d")
print(f"Registros: {len(master):,}")
master.to_csv('data/features/master_enriched.csv', index=False)
