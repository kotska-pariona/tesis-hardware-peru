"""
Experimento 3: Escalabilidad temporal — MAPE vs días de historia
Paper: Tabla/figura que justifica por qué 25+ días son suficientes
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
OUT_PATH  = Path("results/exp3_escalabilidad.json")

DIAS_HISTORIA = [7, 10, 15, 20, 25, 30, 45]
FEATURES = ["lag_1","lag_2","lag_3","ma_2","ma_3","ma_5","std_3","std_5",
            "pct_change_1","pct_change_2","sku_mean","sku_std","sku_min","sku_max",
            "day_of_week","day_of_month","month","is_weekend","sku_enc","source_enc","category_enc"]

def mape(y_true, y_pred):
    mask = y_true > 1
    return np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100

def run():
    print("=" * 60)
    print("  EXP3: Escalabilidad temporal (MAPE vs días historia)")
    print("=" * 60)

    df = pd.read_csv(DATA_PATH, parse_dates=["fecha"])
    df = df.sort_values(["sku_id","fecha"]).reset_index(drop=True)

    df["day_of_week"]  = df["fecha"].dt.dayofweek
    df["day_of_month"] = df["fecha"].dt.day
    df["month"]        = df["fecha"].dt.month
    df["is_weekend"]   = (df["day_of_week"] >= 5).astype(int)

    grp = df.groupby("sku_id")["precio_soles"]
    for k in [1,2,3]:
        df[f"lag_{k}"] = grp.shift(k)
    for k in [2,3,5]:
        df[f"ma_{k}"]  = grp.shift(1).rolling(k).mean().reset_index(level=0, drop=True)
        df[f"std_{k}"] = grp.shift(1).rolling(k).std().reset_index(level=0, drop=True)
    df["pct_change_1"] = grp.pct_change(1)
    df["pct_change_2"] = grp.pct_change(2)

    sku_stats = df.groupby("sku_id")["precio_soles"].agg(["mean","std","min","max"])
    sku_stats.columns = ["sku_mean","sku_std","sku_min","sku_max"]
    df = df.merge(sku_stats, on="sku_id", how="left")
    df["sku_enc"]      = df["sku_id"].astype("category").cat.codes
    df["source_enc"]   = df["fuente"].astype("category").cat.codes if "fuente" in df.columns else 0
    df["category_enc"] = df["categoria"].astype("category").cat.codes if "categoria" in df.columns else 0
    df = df.dropna(subset=["lag_1","lag_2","lag_3"])

    fecha_max = df["fecha"].max()
    results = {}

    for dias in DIAS_HISTORIA:
        fecha_corte = fecha_max - pd.Timedelta(days=dias)
        df_sub = df[df["fecha"] >= fecha_corte].copy()

        if len(df_sub) < 1000:
            print(f"  {dias:3d} días: insuficientes datos ({len(df_sub)} filas), saltando...")
            continue

        n = len(df_sub)
        train_end = int(n * 0.8)
        feats_ok = [f for f in FEATURES if f in df_sub.columns]

        X_train = df_sub.iloc[:train_end][feats_ok]
        y_train = df_sub.iloc[:train_end]["precio_soles"]
        X_test  = df_sub.iloc[train_end:][feats_ok]
        y_test  = df_sub.iloc[train_end:]["precio_soles"]

        model = lgb.LGBMRegressor(
            objective="regression_l1", learning_rate=0.05,
            num_leaves=63, n_estimators=300, verbose=-1
        )
        model.fit(X_train, y_train)
        pred = model.predict(X_test)

        m  = mape(y_test.values, pred)
        r2 = r2_score(y_test, pred)

        results[str(dias)] = {
            "dias": dias,
            "n_filas": len(df_sub),
            "n_test": len(X_test),
            "mape": round(m, 4),
            "r2": round(r2, 6),
        }
        print(f"  {dias:3d} días | {len(df_sub):7,d} filas | MAPE={m:.4f}% | R2={r2:.6f}")

    OUT_PATH.parent.mkdir(exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  ✅ Guardado: {OUT_PATH}")

if __name__ == "__main__":
    run()
