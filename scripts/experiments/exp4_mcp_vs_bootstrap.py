"""
Experimento 4: Mondrian CP vs Bootstrap CI
Paper: Tabla cobertura empírica por estrato de precio
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
OUT_PATH  = Path("results/exp4_mcp_vs_bootstrap.json")
ALPHA     = 0.05   # 95% cobertura objetivo
N_BOOT    = 500

FEATURES = ["lag_1","lag_2","lag_3","ma_2","ma_3","ma_5","std_3","std_5",
            "pct_change_1","pct_change_2","sku_mean","sku_std","sku_min","sku_max",
            "day_of_week","day_of_month","month","is_weekend","sku_enc","source_enc","category_enc"]

ESTRATOS = {
    "S1_$5-$20":    (5,   20),
    "S2_$20-$100":  (20,  100),
    "S3_$100-$500": (100, 500),
    "S4_$500-$2k":  (500, 2000),
    "S5_$2k+":      (2000, 99999),
}

def mape_fn(y_true, y_pred):
    mask = y_true > 1
    return np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100

def run():
    print("=" * 60)
    print("  EXP4: Mondrian CP vs Bootstrap CI")
    print("=" * 60)

    df = pd.read_csv(DATA_PATH, low_memory=False)
    df["price_date"] = pd.to_datetime(df["price_date"], format="%Y-%m-%d", errors="coerce")
    df = df.dropna(subset=["price_date", "price_pen"])
    df = df[df["price_pen"] > 0]
    df = df.sort_values(["sku","price_date"]).reset_index(drop=True)

    df["day_of_week"]  = df["price_date"].dt.dayofweek
    df["day_of_month"] = df["price_date"].dt.day
    df["month"]        = df["price_date"].dt.month
    df["is_weekend"]   = (df["day_of_week"] >= 5).astype(int)

    grp = df.groupby("sku")["price_pen"]
    for k in [1,2,3]:
        df[f"lag_{k}"] = grp.shift(k)
    for k in [2,3,5]:
        df[f"ma_{k}"]  = grp.shift(1).rolling(k).mean().reset_index(level=0, drop=True)
        df[f"std_{k}"] = grp.shift(1).rolling(k).std().reset_index(level=0, drop=True)
    df["pct_change_1"] = grp.pct_change(1)
    df["pct_change_2"] = grp.pct_change(2)

    sku_stats = df.groupby("sku")["price_pen"].agg(["mean","std","min","max"])
    sku_stats.columns = ["sku_mean","sku_std","sku_min","sku_max"]
    df = df.merge(sku_stats, on="sku", how="left")
    df["sku_enc"]      = df["sku"].astype("category").cat.codes
    df["source_enc"]   = df["source"].astype("category").cat.codes if "source" in df.columns else 0
    df["category_enc"] = df["category"].astype("category").cat.codes if "category" in df.columns else 0
    df = df.dropna(subset=["lag_1","lag_2","lag_3"])

    n = len(df)
    train_end  = int(n * 0.60)
    cal_end    = int(n * 0.80)
    feats_ok   = [f for f in FEATURES if f in df.columns]

    X_train = df.iloc[:train_end][feats_ok]
    y_train = df.iloc[:train_end]["price_pen"]
    X_cal   = df.iloc[train_end:cal_end][feats_ok]
    y_cal   = df.iloc[train_end:cal_end]["price_pen"]
    X_test  = df.iloc[cal_end:][feats_ok]
    y_test  = df.iloc[cal_end:]["price_pen"]
    precio_test = df.iloc[cal_end:]["price_pen"].values

    # Entrenar modelo base
    model = lgb.LGBMRegressor(
        objective="regression_l1", learning_rate=0.05,
        num_leaves=127, n_estimators=500, verbose=-1
    )
    model.fit(X_train, y_train)

    pred_cal  = model.predict(X_cal)
    pred_test = model.predict(X_test)

    # ── Mondrian CP (estratificado por rango de precio) ──────────────
    residuals_cal = np.abs(y_cal.values - pred_cal)
    precio_cal    = y_cal.values

    mcp_results = {}
    for estrato, (lo, hi) in ESTRATOS.items():
        mask_cal  = (precio_cal  >= lo) & (precio_cal  < hi)
        mask_test = (precio_test >= lo) & (precio_test < hi)
        if mask_cal.sum() < 10 or mask_test.sum() < 5:
            continue
        q = np.quantile(residuals_cal[mask_cal], 1 - ALPHA)
        y_lo = pred_test[mask_test] - q
        y_hi = pred_test[mask_test] + q
        covered = ((precio_test[mask_test] >= y_lo) & (precio_test[mask_test] <= y_hi)).mean()
        width   = np.mean(y_hi - y_lo)
        mcp_results[estrato] = {
            "cobertura": round(float(covered) * 100, 2),
            "ancho_medio": round(float(width), 2),
            "n_test": int(mask_test.sum()),
        }
        print(f"  MCP  {estrato:20s} | cobertura={covered*100:.2f}% | ancho={width:.2f}")

    # ── Bootstrap CI ─────────────────────────────────────────────────
    print("\n  Calculando Bootstrap CI (500 iteraciones)...")
    rng = np.random.default_rng(42)
    boot_preds = np.zeros((N_BOOT, len(X_test)))
    for b in range(N_BOOT):
        idx = rng.integers(0, len(X_train), len(X_train))
        m_b = lgb.LGBMRegressor(
            objective="regression_l1", learning_rate=0.1,
            num_leaves=63, n_estimators=100, verbose=-1
        )
        m_b.fit(X_train.iloc[idx], y_train.iloc[idx])
        boot_preds[b] = m_b.predict(X_test)

    boot_lo = np.quantile(boot_preds, ALPHA/2,   axis=0)
    boot_hi = np.quantile(boot_preds, 1-ALPHA/2, axis=0)

    boot_results = {}
    for estrato, (lo, hi) in ESTRATOS.items():
        mask_test = (precio_test >= lo) & (precio_test < hi)
        if mask_test.sum() < 5:
            continue
        covered = ((precio_test[mask_test] >= boot_lo[mask_test]) &
                   (precio_test[mask_test] <= boot_hi[mask_test])).mean()
        width   = np.mean(boot_hi[mask_test] - boot_lo[mask_test])
        boot_results[estrato] = {
            "cobertura": round(float(covered) * 100, 2),
            "ancho_medio": round(float(width), 2),
            "n_test": int(mask_test.sum()),
        }
        print(f"  Boot {estrato:20s} | cobertura={covered*100:.2f}% | ancho={width:.2f}")

    output = {
        "alpha": ALPHA,
        "objetivo_cobertura": (1 - ALPHA) * 100,
        "n_bootstrap": N_BOOT,
        "mondrian_cp": mcp_results,
        "bootstrap_ci": boot_results,
    }

    OUT_PATH.parent.mkdir(exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  ✅ Guardado: {OUT_PATH}")

if __name__ == "__main__":
    run()
