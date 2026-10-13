# -*- coding: utf-8 -*-
"""
PE2 v5.2 — Modelo híbrido SKU-memory + group_key semantic
Dataset: data/processed_v2/ (35 fechas, 877k registros)
Aporte académico:
  - WMAPE_seen:   SKUs vistos en train → memoria de sku_enc + sku_mean
  - WMAPE_unseen: SKUs nuevos          → inferencia semántica por group_key + hw_level
"""

import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.preprocessing import LabelEncoder
import json, warnings, os
from datetime import datetime
warnings.filterwarnings("ignore")

# ── CONFIG ──────────────────────────────────────────────────────────────────
DATA_DIR   = "data/processed_v2"
OUT_DIR    = "models"
os.makedirs(OUT_DIR, exist_ok=True)

TARGET     = "price_usd"
SEED       = 42
MIN_PRICE  = 1.0
MAX_PRICE  = 15000.0

# ── 1. CARGA ─────────────────────────────────────────────────────────────────
print("=" * 60)
print("PE2 v5.2 — Cargando datos...")
print("=" * 60)

dfs = {}
for split in ["train", "val", "test"]:
    df = pd.read_csv(f"{DATA_DIR}/{split}.csv", low_memory=False)
    df["price_date"] = pd.to_datetime(df["price_date"], errors="coerce")
    # Filtrar precios válidos
    df = df[(df[TARGET] >= MIN_PRICE) & (df[TARGET] <= MAX_PRICE)].copy()
    dfs[split] = df
    print(f"  {split}: {len(df):,} registros | {df['price_date'].dt.date.nunique()} fechas | "
          f"{df['price_date'].min().date()} → {df['price_date'].max().date()}")

train_df = dfs["train"]
val_df   = dfs["val"]
test_df  = dfs["test"]

# ── 2. FEATURES TEMPORALES ──────────────────────────────────────────────────
print("\nGenerando features temporales...")

for df in [train_df, val_df, test_df]:
    df["dow"]        = df["price_date"].dt.dayofweek
    df["week"]       = df["price_date"].dt.isocalendar().week.astype(int)
    df["month"]      = df["price_date"].dt.month
    df["days_since"] = (df["price_date"] - pd.Timestamp("2026-07-11")).dt.days

# ── 3. ENCODING ──────────────────────────────────────────────────────────────
print("Encodings...")

# hw_level: L1=brand+model, L2=brand+hw, L3=catch-all
L1_TYPES = {"cpu","gpu","motherboard","ssd","monitor","ram"}
L2_TYPES = {"laptop","cooler","psu"}

def hw_level(hw):
    if hw in L1_TYPES: return 1
    if hw in L2_TYPES: return 2
    return 3

for df in [train_df, val_df, test_df]:
    df["hw_level"] = df["hw_type"].fillna("otro").map(hw_level)

# SKU encoder (fit solo en train)
sku_enc = LabelEncoder()
sku_enc.fit(train_df["sku"].astype(str))
known_skus = set(sku_enc.classes_)

def encode_sku(series):
    arr = series.astype(str).values
    result = np.where(np.isin(arr, list(known_skus)),
                      sku_enc.transform(np.where(np.isin(arr, list(known_skus)), arr, sku_enc.classes_[0])),
                      -1)
    return result

train_df["sku_enc"] = encode_sku(train_df["sku"])
val_df["sku_enc"]   = encode_sku(val_df["sku"])
test_df["sku_enc"]  = encode_sku(test_df["sku"])

# group_key encoder
gk_enc = LabelEncoder()
gk_enc.fit(train_df["group_key"].astype(str))
known_gks = set(gk_enc.classes_)

def encode_gk(series):
    arr = series.astype(str).values
    result = np.where(np.isin(arr, list(known_gks)),
                      gk_enc.transform(np.where(np.isin(arr, list(known_gks)), arr, gk_enc.classes_[0])),
                      -1)
    return result

train_df["gk_enc"] = encode_gk(train_df["group_key"])
val_df["gk_enc"]   = encode_gk(val_df["group_key"])
test_df["gk_enc"]  = encode_gk(test_df["group_key"])

# hw_type encoder
hw_enc = LabelEncoder()
hw_enc.fit(train_df["hw_type"].fillna("otro"))
for df in [train_df, val_df, test_df]:
    df["hw_enc"] = hw_enc.transform(df["hw_type"].fillna("otro").map(
        lambda x: x if x in hw_enc.classes_ else "otro"))

# source encoder
src_enc = LabelEncoder()
src_enc.fit(train_df["source"].fillna("unknown"))
for df in [train_df, val_df, test_df]:
    df["src_enc"] = src_enc.transform(df["source"].fillna("unknown").map(
        lambda x: x if x in src_enc.classes_ else src_enc.classes_[0]))

# ── 4. ESTADÍSTICAS SIN LEAKAGE ──────────────────────────────────────────────
print("Calculando estadísticas (sin leakage)...")

# SKU stats — solo desde train
sku_stats = train_df.groupby("sku")[TARGET].agg(
    sku_mean="mean", sku_median="median", sku_std="std", sku_count="count"
).reset_index()
sku_stats["sku_std"] = sku_stats["sku_std"].fillna(0)

# group_key stats — solo desde train
gk_stats = train_df.groupby("group_key")[TARGET].agg(
    gk_mean="mean", gk_median="median", gk_std="std", gk_count="count"
).reset_index()
gk_stats["gk_std"] = gk_stats["gk_std"].fillna(0)

# hw_type stats — solo desde train
hw_stats = train_df.groupby("hw_type")[TARGET].agg(
    hw_mean="mean", hw_median="median"
).reset_index()

# Merge stats en los 3 splits
for df in [train_df, val_df, test_df]:
    df.drop(columns=[c for c in df.columns if c in
             ["sku_mean","sku_median","sku_std","sku_count",
              "gk_mean","gk_median","gk_std","gk_count",
              "hw_mean","hw_median"]], inplace=True, errors="ignore")
    df = df.merge(sku_stats, on="sku", how="left")
    df = df.merge(gk_stats,  on="group_key", how="left")
    df = df.merge(hw_stats,  on="hw_type",   how="left")
    # Fallback para SKUs/GKs nuevos
    global_mean = train_df[TARGET].mean()
    for col in ["sku_mean","sku_median","gk_mean","gk_median","hw_mean","hw_median"]:
        df[col] = df[col].fillna(global_mean)
    for col in ["sku_std","gk_std"]:
        df[col] = df[col].fillna(0)
    for col in ["sku_count","gk_count"]:
        df[col] = df[col].fillna(0)
    # Actualizar el df en el dict
    if "price_date" in df.columns:
        pass
    # Re-asignar
    if len(df) == len(train_df):
        train_df = df
    elif len(df) == len(val_df):
        val_df = df
    else:
        test_df = df

# ── 5. LAG FEATURES ──────────────────────────────────────────────────────────
# Usar las columnas de lag ya calculadas en features/
lag_cols = [c for c in train_df.columns if c.startswith("price_usd_lag") or
            c.startswith("price_usd_ma") or c.startswith("price_usd_std") or
            c.startswith("price_usd_zscore")]
print(f"  Lag features disponibles: {lag_cols}")

# lag_1 como proxy del precio anterior (sin leakage)
for df in [train_df, val_df, test_df]:
    if "price_usd_lag_1" in df.columns:
        df["lag_1"] = df["price_usd_lag_1"].fillna(df["sku_mean"])
    else:
        df["lag_1"] = df["sku_mean"]

# ── 6. FEATURE SET FINAL ─────────────────────────────────────────────────────
FEATURES = [
    # Identidad granular
    "sku_enc", "gk_enc", "hw_enc", "src_enc", "hw_level",
    # Memoria de precio (SKU-level)
    "sku_mean", "sku_median", "sku_std", "sku_count", "lag_1",
    # Inferencia semántica (group_key-level)
    "gk_mean", "gk_median", "gk_std", "gk_count",
    # Inferencia por tipo HW
    "hw_mean", "hw_median",
    # Temporales
    "dow", "week", "month", "days_since",
    # Precio en soles (señal de mercado local)
    "price_pen",
    # Descuento
    "discount_pct",
]

# Agregar lags disponibles
for lc in lag_cols:
    if lc not in FEATURES:
        FEATURES.append(lc)

# Filtrar solo los que existen
FEATURES = [f for f in FEATURES if f in train_df.columns]
print(f"\n  Features finales ({len(FEATURES)}): {FEATURES}")

# ── 7. PREPARAR MATRICES ─────────────────────────────────────────────────────
X_train = train_df[FEATURES].fillna(-1)
y_train = train_df[TARGET]
X_val   = val_df[FEATURES].fillna(-1)
y_val   = val_df[TARGET]
X_test  = test_df[FEATURES].fillna(-1)
y_test  = test_df[TARGET]

print(f"\n  X_train: {X_train.shape}")
print(f"  X_val:   {X_val.shape}")
print(f"  X_test:  {X_test.shape}")

# ── 8. ENTRENAMIENTO LGBM ────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("Entrenando LightGBM v5.2...")
print("=" * 60)

params = {
    "objective":        "regression",
    "metric":           "mae",
    "boosting_type":    "gbdt",
    "n_estimators":     2000,
    "learning_rate":    0.03,
    "num_leaves":       127,
    "max_depth":        -1,
    "min_child_samples": 20,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq":     5,
    "lambda_l1":        0.1,
    "lambda_l2":        0.1,
    "verbose":          -1,
    "random_state":     SEED,
    "n_jobs":           -1,
}

model = lgb.LGBMRegressor(**params)
model.fit(
    X_train, y_train,
    eval_set=[(X_val, y_val)],
    callbacks=[
        lgb.early_stopping(stopping_rounds=50, verbose=True),
        lgb.log_evaluation(period=100),
    ]
)

# ── 9. MÉTRICAS ──────────────────────────────────────────────────────────────
def wmape(y_true, y_pred):
    y_true, y_pred = np.array(y_true), np.array(y_pred)
    mask = y_true > 0
    return np.sum(np.abs(y_true[mask] - y_pred[mask])) / np.sum(y_true[mask])

def mae(y_true, y_pred):
    return np.mean(np.abs(np.array(y_true) - np.array(y_pred)))

print("\n" + "=" * 60)
print("MÉTRICAS PE2 v5.2")
print("=" * 60)

results = {}

for split_name, X, y, df in [
    ("val",  X_val,  y_val,  val_df),
    ("test", X_test, y_test, test_df),
]:
    preds = model.predict(X)
    preds = np.clip(preds, MIN_PRICE, MAX_PRICE)

    # Métricas globales
    wm  = wmape(y, preds)
    ma  = mae(y, preds)

    # Métricas seen vs unseen
    seen_mask   = df["sku"].isin(known_skus)
    unseen_mask = ~seen_mask

    wm_seen   = wmape(y[seen_mask],   preds[seen_mask])   if seen_mask.sum()   > 0 else float("nan")
    wm_unseen = wmape(y[unseen_mask], preds[unseen_mask]) if unseen_mask.sum() > 0 else float("nan")
    mae_seen   = mae(y[seen_mask],   preds[seen_mask])    if seen_mask.sum()   > 0 else float("nan")
    mae_unseen = mae(y[unseen_mask], preds[unseen_mask])  if unseen_mask.sum() > 0 else float("nan")

    n_seen   = seen_mask.sum()
    n_unseen = unseen_mask.sum()

    print(f"\n  [{split_name.upper()}]")
    print(f"    WMAPE global:  {wm:.4f}  ({wm*100:.2f}%)")
    print(f"    MAE global:    ${ma:.2f}")
    print(f"    WMAPE seen:    {wm_seen:.4f}  ({wm_seen*100:.2f}%)  — {n_seen:,} SKUs conocidos")
    print(f"    WMAPE unseen:  {wm_unseen:.4f}  ({wm_unseen*100:.2f}%)  — {n_unseen:,} SKUs nuevos")
    print(f"    MAE seen:      ${mae_seen:.2f}")
    print(f"    MAE unseen:    ${mae_unseen:.2f}")

    results[split_name] = {
        "wmape": float(wm), "mae": float(ma),
        "wmape_seen": float(wm_seen), "wmape_unseen": float(wm_unseen),
        "mae_seen": float(mae_seen), "mae_unseen": float(mae_unseen),
        "n_seen": int(n_seen), "n_unseen": int(n_unseen),
    }

# ── 10. FEATURE IMPORTANCE ───────────────────────────────────────────────────
print("\n" + "=" * 60)
print("FEATURE IMPORTANCE (top 15)")
print("=" * 60)
fi = pd.DataFrame({
    "feature": FEATURES,
    "importance": model.feature_importances_
}).sort_values("importance", ascending=False)
print(fi.head(15).to_string(index=False))

# ── 11. GUARDAR ──────────────────────────────────────────────────────────────
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
model_path = f"{OUT_DIR}/pe2_v52_{ts}.txt"
model.booster_.save_model(model_path)

metrics_path = f"{OUT_DIR}/pe2_v52_metrics_{ts}.json"
with open(metrics_path, "w", encoding="utf-8") as f:
    json.dump({
        "version": "PE2_v5.2",
        "timestamp": ts,
        "dataset": "processed_v2",
        "train_records": len(train_df),
        "train_dates": train_df["price_date"].dt.date.nunique(),
        "features": FEATURES,
        "n_features": len(FEATURES),
        "best_iteration": model.best_iteration_,
        "results": results,
    }, f, indent=2, ensure_ascii=False)

print(f"\n✅ Modelo guardado: {model_path}")
print(f"✅ Métricas guardadas: {metrics_path}")
print("\n🎯 Listo para la tesis!")
