import pandas as pd

df = pd.read_csv('data/processed/MASTER_hardware_peru_clean.csv', low_memory=False)

print("SKUs unicos (incluyendo NaN):", df['sku'].nunique(dropna=False))
print("Fuentes unicas:", df['source'].unique())
print("Rango de fechas:", df['price_date'].min(), "->", df['price_date'].max())
print()
print("Registros por fuente:")
print(df['source'].value_counts())
print()
print("Dias de historial por SKU (source+sku):")
df['sku_key'] = df['source'].astype(str) + '_' + df['sku'].astype(str)
print(df.groupby('sku_key')['price_date'].nunique().describe())
