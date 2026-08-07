"""
Experimento 1: Ablación de features LightGBM
Paper: HDS-ROI — Tabla comparativa contribución marginal por feature set
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import json
import numpy as np
import pandas as pd
import lightgbm as lgb
from pathlib import Path
from sklearn.metrics import r2_score

DATA_PATH = Path("data/raw/MASTER_hardware_peru_CONSOLIDADO.csv")
OUT_PATH  = Path("results/exp1_ablacion_features.json")

FEATURE_SETS = {
    "F5_lag_only":    ["lag_1","lag_2","lag_3","ma_2","ma_3"],
    "F10_temporal":   ["lag_1","lag_2","lag_3","ma_2","ma_3","ma_5","std_3","std_5","pct_change_1","pct_change_2"],
    "F15_sku":        ["lag_1","lag_2","lag_3","ma_2","ma_3","ma_5","std_3","std_5","pct_change_1","pct_change_2",
                       "sku_mean","sku_std","sku_min","sku_max","sku_enc"],
    "F21_full":       ["lag_1","lag_2","lag_3","ma_2","ma_3","ma_5","std_3","std_5","pct_change_1","pct_change_2",
                       "sku_mean","sku_std","sku_min","sku_max","day_of_week","day_of_month","month",
                       "is_weekend","sku_enc","source_enc","category_enc"],
}

LGB_PARAMS = {
    "objective": "regression_l1",
    "learning_rate": 0.05,
    "num_leaves": 127,
    "n_estimators": 500,
    "verbose": -1,
}

def mape(y_true, y_pred):
    mask = y_true > 1
    return np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100

def run():
    print("=" * 60)
    print("  EXP1: Ablación de Features LightGBM")
    print("=" * 60)

    df = pd.read_csv(DATA_PATH, low_memory=False)
    df["price_date"] = pd.to_datetime(df["price_date"], format="%Y-%m-%d", errors="coerce")
    df = df.dropna(subset=["price_date", "price_pen"])
    df = df[df["price_pen"] > 0]
    df = df.sort_values(["sku","price_date"]).reset_index(drop=True)

    # Features de tiempo
    df["day_of_week"]  = df["price_date"].dt.dayofweek
    df["day_of_month"] = df["price_date"].dt.day
    df["month"]        = df["price_date"].dt.month
    df["is_weekend"]   = (df["day_of_week"] >= 5).astype(int)

    # Lags y medias móviles por SKU
    grp = df.groupby("sku")["price_pen"]
    for k in [1,2,3]:
        df[f"lag_{k}"] = grp.shift(k)
    for k in [2,3,5]:
        df[f"ma_{k}"]  = grp.shift(1).rolling(k).mean().reset_index(level=0, drop=True)
        df[f"std_{k}"] = grp.shift(1).rolling(k).std().reset_index(level=0, drop=True)
    df["pct_change_1"] = grp.pct_change(1)
    df["pct_change_2"] = grp.pct_change(2)

    # Stats por SKU
    sku_stats = df.groupby("sku")["price_pen"].agg(["mean","std","min","max"])
    sku_stats.columns = ["sku_mean","sku_std","sku_min","sku_max"]
    df = df.merge(sku_stats, on="sku", how="left")

    # Encodings
    df["sku_enc"]      = df["sku"].astype("category").cat.codes
    df["source_enc"]   = df["source"].astype("category").cat.codes if "source" in df.columns else 0
    df["category_enc"] = df["category"].astype("category").cat.codes if "category" in df.columns else 0

    df = df.dropna(subset=["lag_1","lag_2","lag_3"])
    target = "price_pen"

    n = len(df)
    train_end = int(n * 0.7)
    val_end   = int(n * 0.85)

    results = {}
    for name, feats in FEATURE_SETS.items():
        available = [f for f in feats if f in df.columns]
        X_train = df.iloc[:train_end][available]
        y_train = df.iloc[:train_end][target]
        X_val   = df.iloc[train_end:val_end][available]
        y_val   = df.iloc[train_end:val_end][target]
        X_test  = df.iloc[val_end:][available]
        y_test  = df.iloc[val_end:][target]

        model = lgb.LGBMRegressor(**LGB_PARAMS)
        model.fit(X_train, y_train,
                  eval_set=[(X_val, y_val)],
                  callbacks=[lgb.early_stopping(50, verbose=False)])

        pred = model.predict(X_test)
        m = mape(y_test.values, pred)
        r2 = r2_score(y_test, pred)

        results[name] = {
            "n_features": len(available),
            "mape_test": round(m, 4),
            "r2_test": round(r2, 6),
        }
        print(f"  {name:20s} | features={len(available):2d} | MAPE={m:.4f}% | R2={r2:.6f}")

    OUT_PATH.parent.mkdir(exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  ✅ Guardado: {OUT_PATH}")

if __name__ == "__main__":
    run()
