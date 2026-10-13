"""
train_pe2_v5.py  — v5.1
========================
Fix vs v5.0:
  - ELIMINADOS ratio_vs_* calculados con price_usd (data leakage del target)
  - Ratios ahora se calculan con LAG_1 como proxy del precio anterior
  - Fix JSON bool_ serialization
  - Fix merge hw_stats2 (no se asignaba el resultado)
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import json
import numpy as np
import pandas as pd
import lightgbm as lgb
from pathlib import Path
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import r2_score

# -------------------------------------------------
# CONFIG
# -------------------------------------------------
PRICE_FLOOR     = 20.0
TARGET          = "price_usd"
MODEL_OUT       = Path("models/pe2_lgbm/lgbm_pe2_v5.txt")
METRICS_OUT     = Path("results/pe2_lgbm_v5_metrics.json")
MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
METRICS_OUT.parent.mkdir(parents=True, exist_ok=True)

LGBM_PARAMS = {
    "objective":         "regression_l1",
    "metric":            ["mae", "rmse"],
    "num_leaves":        127,
    "learning_rate":     0.03,
    "feature_fraction":  0.8,
    "bagging_fraction":  0.8,
    "bagging_freq":      5,
    "min_child_samples": 20,
    "reg_alpha":         0.1,
    "reg_lambda":        0.1,
    "n_jobs":            -1,
    "verbose":           -1,
    "seed":              42,
}
NUM_BOOST_ROUND = 4000
EARLY_STOPPING  = 150

# -------------------------------------------------
# 1. CARGA Y FILTRO
# -------------------------------------------------
print("[1/6] Cargando splits...")
train = pd.read_csv("data/processed/train.csv", low_memory=False)
val   = pd.read_csv("data/processed/val.csv",   low_memory=False)
test  = pd.read_csv("data/processed/test.csv",  low_memory=False)

for df in [train, val, test]:
    df.drop(df[df[TARGET] < PRICE_FLOOR].index, inplace=True)
    df.reset_index(drop=True, inplace=True)

print(f"  train={len(train):,}  val={len(val):,}  test={len(test):,}")

# -------------------------------------------------
# 2. FEATURE ENGINEERING
# -------------------------------------------------
def add_hw_level(df):
    """L1=brand+model conocidos, L2=solo brand, L3=ambos Unknown"""
    cond_l1 = (df["brand_norm"] != "Unknown") & (df["model_norm"] != "Unknown")
    cond_l2 = (df["brand_norm"] != "Unknown") & (df["model_norm"] == "Unknown")
    df["hw_level"] = 3
    df.loc[cond_l2, "hw_level"] = 2
    df.loc[cond_l1, "hw_level"] = 1
    return df

def build_features(train_df, val_df, test_df):
    all_dfs = [train_df, val_df, test_df]

    # -- Encoders categoricos ----------------------
    cat_cols = ["group_key", "brand_norm", "hw_type",
                "source", "source_rol", "category"]
    for col in cat_cols:
        le = LabelEncoder()
        le.fit(pd.concat([d[col].astype(str) for d in all_dfs]))
        for df in all_dfs:
            df[f"{col}_enc"] = le.transform(df[col].astype(str))

    # -- hw_level ----------------------------------
    for df in all_dfs:
        add_hw_level(df)

    # -- Temporal ----------------------------------
    for df in all_dfs:
        df["price_date"]   = pd.to_datetime(df["price_date"], errors="coerce")
        df["day_of_week"]  = df["price_date"].dt.dayofweek
        df["day_of_month"] = df["price_date"].dt.day
        df["month"]        = df["price_date"].dt.month
        df["is_weekend"]   = (df["day_of_week"] >= 5).astype(int)

    # -- Lags y rolling (por sku, ordenado por fecha) --
    # IMPORTANTE: calcular ANTES de los ratios para usar lag_1 como proxy
    processed_lag = []
    for df in all_dfs:
        df = df.sort_values(["sku", "price_date"]).copy()
        grp = df.groupby("sku")[TARGET]
        df["lag_1"]        = grp.shift(1)
        df["lag_2"]        = grp.shift(2)
        df["lag_3"]        = grp.shift(3)
        df["ma_2"]         = grp.transform(lambda x: x.shift(1).rolling(2).mean())
        df["ma_3"]         = grp.transform(lambda x: x.shift(1).rolling(3).mean())
        df["ma_5"]         = grp.transform(lambda x: x.shift(1).rolling(5).mean())
        df["std_3"]        = grp.transform(lambda x: x.shift(1).rolling(3).std())
        df["std_5"]        = grp.transform(lambda x: x.shift(1).rolling(5).std())
        df["pct_change_1"] = grp.pct_change(1)
        df["pct_change_2"] = grp.pct_change(2)
        processed_lag.append(df)
    train_df, val_df, test_df = processed_lag
    all_dfs = [train_df, val_df, test_df]

    # -- Stats por group_key (SOLO calculadas en train) ----------------
    gk_stats = train_df.groupby("group_key")[TARGET].agg(
        gk_mean="mean", gk_std="std", gk_median="median",
        gk_min="min",   gk_max="max", gk_count="count"
    ).reset_index()
    gk_stats["gk_std"] = gk_stats["gk_std"].fillna(0)

    hw_fb = train_df.groupby("hw_type")[TARGET].agg(
        hw_mean_fb="mean", hw_median_fb="median"
    ).reset_index()

    processed_gk = []
    for df in all_dfs:
        df = df.merge(gk_stats, on="group_key", how="left")
        df = df.merge(hw_fb,    on="hw_type",   how="left")
        df["gk_mean"]   = df["gk_mean"].fillna(df["hw_mean_fb"])
        df["gk_median"] = df["gk_median"].fillna(df["hw_median_fb"])
        df["gk_std"]    = df["gk_std"].fillna(0)
        df["gk_min"]    = df["gk_min"].fillna(df["hw_mean_fb"])
        df["gk_max"]    = df["gk_max"].fillna(df["hw_mean_fb"])
        df["gk_count"]  = df["gk_count"].fillna(1)
        df.drop(columns=["hw_mean_fb","hw_median_fb"], inplace=True)
        processed_gk.append(df)
    train_df, val_df, test_df = processed_gk
    all_dfs = [train_df, val_df, test_df]

    # -- Stats por sku (SOLO calculadas en train) ----------------------
    sku_stats = train_df.groupby("sku")[TARGET].agg(
        sku_mean="mean", sku_std="std",
        sku_min="min",   sku_max="max", sku_count="count"
    ).reset_index()
    sku_stats["sku_std"] = sku_stats["sku_std"].fillna(0)

    processed_sku = []
    for df in all_dfs:
        df = df.merge(sku_stats, on="sku", how="left")
        df["sku_mean"]  = df["sku_mean"].fillna(df["gk_mean"])
        df["sku_std"]   = df["sku_std"].fillna(0)
        df["sku_min"]   = df["sku_min"].fillna(df["gk_min"])
        df["sku_max"]   = df["sku_max"].fillna(df["gk_max"])
        df["sku_count"] = df["sku_count"].fillna(1)
        processed_sku.append(df)
    train_df, val_df, test_df = processed_sku
    all_dfs = [train_df, val_df, test_df]

    # -- Stats por hw_type (SOLO calculadas en train) ------------------
    hw_stats = train_df.groupby("hw_type")[TARGET].agg(
        hw_mean="mean", hw_std="std", hw_median="median"
    ).reset_index()
    hw_stats["hw_std"] = hw_stats["hw_std"].fillna(0)

    processed_hw = []
    for df in all_dfs:
        df = df.merge(hw_stats, on="hw_type", how="left")
        processed_hw.append(df)
    train_df, val_df, test_df = processed_hw
    all_dfs = [train_df, val_df, test_df]

    # -- Fillna de lags con gk_mean (ahora que existe gk_mean) ---------
    for df in all_dfs:
        for c in ["lag_1","lag_2","lag_3","ma_2","ma_3","ma_5"]:
            df[c] = df[c].fillna(df["gk_mean"])
        for c in ["std_3","std_5"]:
            df[c] = df[c].fillna(0)
        for c in ["pct_change_1","pct_change_2"]:
            df[c] = df[c].fillna(0).clip(-1, 10)

    # -- Ratios SIN data leakage: usar lag_1 como proxy del precio -----
    # lag_1 es el precio ANTERIOR observado → no es el target actual
    for df in all_dfs:
        df["ratio_lag1_vs_gk_mean"]   = df["lag_1"] / (df["gk_mean"]   + 1e-6)
        df["ratio_lag1_vs_gk_median"] = df["lag_1"] / (df["gk_median"] + 1e-6)
        df["ratio_lag1_vs_hw_mean"]   = df["lag_1"] / (df["hw_mean"]   + 1e-6)
        df["ratio_lag1_vs_sku_mean"]  = df["lag_1"] / (df["sku_mean"]  + 1e-6)

    return train_df, val_df, test_df

print("[2/6] Construyendo features...")
train, val, test = build_features(train, val, test)

# -------------------------------------------------
# 3. FEATURE SET v5.1
# -------------------------------------------------
FEATURES_V5 = [
    # Lags / rolling (precios anteriores del mismo SKU)
    "lag_1", "lag_2", "lag_3",
    "ma_2", "ma_3", "ma_5",
    "std_3", "std_5",
    "pct_change_1", "pct_change_2",
    # Stats historicas por SKU
    "sku_mean", "sku_std", "sku_min", "sku_max", "sku_count",
    # Stats historicas por group_key  <-- NUEVO v5
    "gk_mean", "gk_std", "gk_median", "gk_min", "gk_max", "gk_count",
    # Stats historicas por hw_type
    "hw_mean", "hw_std", "hw_median",
    # Ratios sin leakage (lag_1 / estadistica)
    "ratio_lag1_vs_gk_mean", "ratio_lag1_vs_gk_median",
    "ratio_lag1_vs_hw_mean", "ratio_lag1_vs_sku_mean",
    # Temporales
    "day_of_week", "day_of_month", "month", "is_weekend",
    # Categoricos encodados
    "group_key_enc",   # identidad semantica brand|model  <-- NUEVO v5
    "brand_norm_enc",  # <-- NUEVO v5
    "hw_level",        # L1/L2/L3                         <-- NUEVO v5
    "source_enc",
    "category_enc",
    "hw_type_enc",
    "source_rol_enc",
]

# -------------------------------------------------
# 4. DATASETS LGBM
# -------------------------------------------------
def to_log(y):   return np.log1p(y)
def from_log(y): return np.expm1(y)

X_train = train[FEATURES_V5]
y_train = to_log(train[TARGET])
X_val   = val[FEATURES_V5]
y_val   = to_log(val[TARGET])
X_test  = test[FEATURES_V5]
y_test  = test[TARGET].values

dtrain = lgb.Dataset(X_train, label=y_train, feature_name=FEATURES_V5)
dval   = lgb.Dataset(X_val,   label=y_val,   reference=dtrain)

print(f"  Features: {len(FEATURES_V5)}")
print(f"  X_train: {X_train.shape}  X_val: {X_val.shape}  X_test: {X_test.shape}")

# -------------------------------------------------
# 5. ENTRENAMIENTO
# -------------------------------------------------
print("\n[3/6] Entrenando PE2 v5.1...")
callbacks = [
    lgb.early_stopping(EARLY_STOPPING, verbose=True),
    lgb.log_evaluation(200),
]

model = lgb.train(
    LGBM_PARAMS,
    dtrain,
    num_boost_round=NUM_BOOST_ROUND,
    valid_sets=[dtrain, dval],
    valid_names=["train", "val"],
    callbacks=callbacks,
)

model.save_model(str(MODEL_OUT))
print(f"\n[4/6] Modelo guardado: {MODEL_OUT}  (best_iter={model.best_iteration})")

# -------------------------------------------------
# 6. METRICAS
# -------------------------------------------------
def compute_metrics(y_true, y_pred, label=""):
    mae   = float(np.mean(np.abs(y_true - y_pred)))
    rmse  = float(np.sqrt(np.mean((y_true - y_pred)**2)))
    mape  = float(np.mean(np.abs((y_true - y_pred) / (y_true + 1e-6))) * 100)
    wmape = float(np.sum(np.abs(y_true - y_pred)) / (np.sum(y_true) + 1e-6) * 100)
    r2    = float(r2_score(y_true, y_pred))
    n     = int(len(y_true))
    ok_mape  = "OK"   if mape  < 2    else "FAIL"
    ok_wmape = "OK"   if wmape < 2    else "FAIL"
    ok_r2    = "OK"   if r2    > 0.85 else "FAIL"
    print(f"\n  [{label}] n={n:,}")
    print(f"    MAE={mae:.4f}  RMSE={rmse:.4f}")
    print(f"    MAPE={mape:.4f}%  [{ok_mape}]  "
          f"WMAPE={wmape:.4f}%  [{ok_wmape}]  "
          f"R2={r2:.6f}  [{ok_r2}]")
    return {"mae": round(mae,4), "rmse": round(rmse,4),
            "mape": round(mape,4), "wmape": round(wmape,4),
            "r2": round(r2,6), "n": n}

print("\n[5/6] Evaluando...")
pred_val  = from_log(model.predict(X_val,  num_iteration=model.best_iteration))
pred_test = from_log(model.predict(X_test, num_iteration=model.best_iteration))

m_val  = compute_metrics(val[TARGET].values, pred_val,  "VAL")
m_test = compute_metrics(y_test,             pred_test, "TEST")

# -- WMAPE por hw_type (test) --------------------
print("\n  WMAPE por hw_type [TEST]:")
test_eval = test.copy()
test_eval["pred"] = pred_test
for hw in sorted(test_eval["hw_type"].unique()):
    sub  = test_eval[test_eval["hw_type"] == hw]
    wm   = float(np.sum(np.abs(sub[TARGET]-sub["pred"])) / (np.sum(sub[TARGET])+1e-6) * 100)
    flag = "OK" if wm < 2 else ("~OK" if wm < 5 else "FAIL")
    print(f"    [{flag}] {hw:<15} WMAPE={wm:.2f}%  n={len(sub):,}")

# -- WMAPE por hw_level (test) -------------------
print("\n  WMAPE por hw_level [TEST]:")
for lvl in [1, 2, 3]:
    sub  = test_eval[test_eval["hw_level"] == lvl]
    if len(sub) == 0: continue
    wm   = float(np.sum(np.abs(sub[TARGET]-sub["pred"])) / (np.sum(sub[TARGET])+1e-6) * 100)
    flag = "OK" if wm < 2 else ("~OK" if wm < 5 else "FAIL")
    print(f"    [{flag}] L{lvl}  WMAPE={wm:.2f}%  n={len(sub):,}")

# -- Feature importance top 15 -------------------
print("\n  Feature importance (gain) top 15:")
fi = pd.Series(model.feature_importance(importance_type="gain"),
               index=FEATURES_V5).sort_values(ascending=False)
for feat, val_fi in fi.head(15).items():
    print(f"    {feat:<35} {val_fi:>12.1f}")

# -------------------------------------------------
# 7. GUARDAR METRICAS (fix bool_ serialization)
# -------------------------------------------------
metrics = {
    "model":            "LightGBM_v5.1",
    "oe":               "OE2",
    "num_trees":        int(model.best_iteration),
    "price_floor_usd":  float(PRICE_FLOOR),
    "target_transform": "log1p",
    "features":         FEATURES_V5,
    "new_features_v5":  ["group_key_enc","brand_norm_enc","hw_level",
                         "gk_mean","gk_std","gk_median",
                         "gk_min","gk_max","gk_count",
                         "ratio_lag1_vs_gk_mean","ratio_lag1_vs_gk_median",
                         "ratio_lag1_vs_hw_mean","ratio_lag1_vs_sku_mean"],
    "metrics_val":  m_val,
    "metrics_test": m_test,
    "metas_tesis": {
        "mape_lt_2pct":  bool(m_test["mape"]  < 2),
        "wmape_lt_2pct": bool(m_test["wmape"] < 2),
        "r2_gt_085":     bool(m_test["r2"]    > 0.85),
    }
}

with open(METRICS_OUT, "w", encoding="utf-8") as f:
    json.dump(metrics, f, indent=2, ensure_ascii=False)

print(f"\n[6/6] Metricas guardadas: {METRICS_OUT}")
print("\n=== PE2 v5.1 completado. ===")