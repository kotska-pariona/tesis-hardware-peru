import pandas as pd
df_master = pd.read_csv("data/raw/MASTER_hardware_peru.csv", low_memory=False)

# Solo local PE, categoría CPU
local = df_master[
    (df_master["source_type"] == "local") &
    (df_master["category_norm"] == "CPU")
].copy()

local["price_pen"] = pd.to_numeric(local["price_pen"], errors="coerce")
local = local[local["price_pen"] > 0]

print(f"=== Local CPU: {len(local)} registros ===")
print(f"\n--- Distribución price_pen ---")
print(local["price_pen"].describe().round(1))

print(f"\n--- Productos más baratos (posible ruido) ---")
cheap = local.nsmallest(15, "price_pen")[["title","price_pen","source"]]
for _, r in cheap.iterrows():
    print(f"  S/{r['price_pen']:8.2f} | {str(r['title'])[:60]}")

print(f"\n--- Rango S/100-S/5000 (CPUs reales) ---")
real = local[(local["price_pen"] >= 100) & (local["price_pen"] <= 5000)]
print(f"  Count: {len(real)}")
print(f"  Median: S/{real['price_pen'].median():.0f}")
print(f"  Mean:   S/{real['price_pen'].mean():.0f}")

print(f"\n--- Muestra CPUs reales ---")
for _, r in real.sample(min(10,len(real)), random_state=42).iterrows():
    print(f"  S/{r['price_pen']:8.2f} | {str(r['title'])[:60]}")
