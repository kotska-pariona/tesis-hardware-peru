"""
pe2_lgbm.py — OE2: LightGBM para predicción de precios de hardware
===================================================================
Justificación del cambio TFT → LightGBM:
  - Solo 9 días de historia (TFT necesita 30-90 días mínimo)
  - TFT: overfitting desde epoch 0, val_loss sube
  - LightGBM: ideal para datos tabulares con features de lag
  - Naive baseline R2=0.9959 → lag_1 es señal dominante
  - Literatura: modelos simples superan DL con historia < 30 días
    (Makridakis et al., 2022; M5 Competition results)
"""

import os, json, warnings
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import r2_score

warnings.filterwarnings("ignore")
os.environ["PYTHONIOENCODING"] = "utf-8"

# ══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════
CFG = {
    "data_dir"   : Path("data/processed"),
    "output_dir" : Path("models/pe2_lgbm"),
    "results_dir": Path("results"),

    "target"     : "price_usd",
    "group_ids"  : ["sku", "source"],

    "price_min"  : 0.50,
    "price_max"  : 15_000.0,
    "price_p_low": 0.001,
    "price_p_high": 0.999,

    # LightGBM params
    "lgbm_params": {
        "objective"        : "regression_l1",   # MAE → robusto a outliers
        "metric"           : ["mae", "mse"],
        "learning_rate"    : 0.05,
        "num_leaves"       : 127,
        "max_depth"        : -1,
        "min_child_samples": 20,
        "feature_fraction" : 0.8,
        "bagging_fraction" : 0.8,
        "bagging_freq"     : 5,
        "reg_alpha"        : 0.1,
        "reg_lambda"       : 0.1,
        "n_jobs"           : -1,
        "verbose"          : -1,
        "seed"             : 42,
    },
    "num_boost_round"  : 2000,
    "early_stopping"   : 100,
}

# ══════════════════════════════════════════════════════════════
# 1. CARGA Y LIMPIEZA
# ══════════════════════════════════════════════════════════════
def load_and_clean(cfg):
    print("\n" + "="*60)
    print("  1. CARGANDO Y LIMPIANDO DATOS")
    print("="*60)

    splits = {}
    for split in ["train", "val", "test"]:
        df = pd.read_csv(cfg["data_dir"] / f"{split}.csv", low_memory=False)
        splits[split] = df

    # Límites desde train
    train_p = splits["train"][cfg["target"]].dropna()
    mask    = (train_p >= cfg["price_min"]) & (train_p <= cfg["price_max"])
    p_clean = train_p[mask]
    p_low   = p_clean.quantile(cfg["price_p_low"])
    p_high  = p_clean.quantile(cfg["price_p_high"])
    print(f"  Rango de precio: [{p_low:.2f}, {p_high:.2f}]")

    cleaned = {}
    for split, df in splits.items():
        df = df.copy()
        df[cfg["target"]] = df[cfg["target"]].clip(lower=p_low, upper=p_high)
        df["price_date"]  = pd.to_datetime(df["price_date"], errors="coerce")
        df = df[
            df["price_date"].notna() &
            df[cfg["target"]].notna() &
            (df[cfg["target"]] >= cfg["price_min"])
        ].copy()
        for col in cfg["group_ids"]:
            if col in df.columns:
                df[col] = df[col].fillna("unknown").astype(str)
        p = df[cfg["target"]]
        print(f"  {split}: {len(df):,} filas | "
              f"min={p.min():.2f} | med={p.median():.2f} | max={p.max():.2f}")
        cleaned[split] = df

    return cleaned["train"], cleaned["val"], cleaned["test"], p_low, p_high


# ══════════════════════════════════════════════════════════════
# 2. FEATURE ENGINEERING
# ══════════════════════════════════════════════════════════════
def build_features(df, cfg, label_encoders=None, fit=False):
    """
    Construye features tabulares para LightGBM.
    No depende de historia temporal larga — usa lags directos.
    """
    df = df.copy()
    df = df.sort_values(cfg["group_ids"] + ["price_date"])
    grp = df.groupby(cfg["group_ids"])[cfg["target"]]

    # ── Features temporales ──────────────────────────────────
    df["day_of_week"]  = df["price_date"].dt.dayofweek
    df["day_of_month"] = df["price_date"].dt.day
    df["month"]        = df["price_date"].dt.month
    df["is_weekend"]   = (df["day_of_week"] >= 5).astype(int)

    # ── Lags (señal dominante con R2=0.9959) ─────────────────
    df["lag_1"] = grp.shift(1)
    df["lag_2"] = grp.shift(2)
    df["lag_3"] = grp.shift(3)

    # ── Medias móviles ────────────────────────────────────────
    df["ma_2"] = grp.transform(
        lambda x: x.shift(1).rolling(2, min_periods=1).mean())
    df["ma_3"] = grp.transform(
        lambda x: x.shift(1).rolling(3, min_periods=1).mean())
    df["ma_5"] = grp.transform(
        lambda x: x.shift(1).rolling(5, min_periods=1).mean())

    # ── Desviación estándar ───────────────────────────────────
    df["std_3"] = grp.transform(
        lambda x: x.shift(1).rolling(3, min_periods=2).std()).fillna(0)
    df["std_5"] = grp.transform(
        lambda x: x.shift(1).rolling(5, min_periods=2).std()).fillna(0)

    # ── Cambio porcentual ─────────────────────────────────────
    df["pct_change_1"] = (df["lag_1"] / df["lag_2"] - 1).fillna(0).clip(-1, 1)
    df["pct_change_2"] = (df["lag_2"] / df["lag_3"] - 1).fillna(0).clip(-1, 1)

    # ── Stats por SKU (sobre historia disponible) ─────────────
    sku_stats = df.groupby(cfg["group_ids"])[cfg["target"]].agg(
        sku_mean="mean", sku_std="std", sku_min="min", sku_max="max"
    ).reset_index()
    sku_stats["sku_std"] = sku_stats["sku_std"].fillna(0)
    df = df.merge(sku_stats, on=cfg["group_ids"], how="left")

    # ── Encoders categóricos ──────────────────────────────────
    cat_cols = ["sku", "source", "category"] if "category" in df.columns \
               else ["sku", "source"]

    if label_encoders is None:
        label_encoders = {}

    for col in cat_cols:
        if col not in df.columns:
            continue
        df[col] = df[col].fillna("unknown").astype(str)
        if fit:
            le = LabelEncoder()
            df[f"{col}_enc"] = le.fit_transform(df[col])
            label_encoders[col] = le
        else:
            le = label_encoders.get(col)
            if le is not None:
                known = set(le.classes_)
                df[col] = df[col].apply(
                    lambda x: x if x in known else "unknown")
                if "unknown" not in known:
                    le.classes_ = np.append(le.classes_, "unknown")
                df[f"{col}_enc"] = le.transform(df[col])
            else:
                df[f"{col}_enc"] = 0

    # ── Rellenar NaN en lags con el propio precio ─────────────
    for col in ["lag_1","lag_2","lag_3","ma_2","ma_3","ma_5"]:
        df[col] = df[col].fillna(df[cfg["target"]])

    return df, label_encoders


def get_feature_cols(df):
    base = [
        "lag_1", "lag_2", "lag_3",
        "ma_2", "ma_3", "ma_5",
        "std_3", "std_5",
        "pct_change_1", "pct_change_2",
        "sku_mean", "sku_std", "sku_min", "sku_max",
        "day_of_week", "day_of_month", "month", "is_weekend",
    ]
    enc = [c for c in df.columns if c.endswith("_enc")]
    return [c for c in base + enc if c in df.columns]


# ══════════════════════════════════════════════════════════════
# 3. MÉTRICAS
# ══════════════════════════════════════════════════════════════
def compute_metrics(preds, actuals, label=""):
    mask  = (actuals > 0) & np.isfinite(preds) & np.isfinite(actuals)
    p, a  = preds[mask], actuals[mask]
    mae   = float(np.mean(np.abs(p - a)))
    rmse  = float(np.sqrt(np.mean((p - a)**2)))
    mape  = float(np.mean(np.abs((p - a) / a)) * 100)
    wmape = float(np.sum(np.abs(p - a)) / np.sum(a) * 100)
    r2    = float(r2_score(a, p))

    print(f"\n  {'─'*45}")
    print(f"  MÉTRICAS {label} ({mask.sum():,} muestras)")
    print(f"  {'─'*45}")
    print(f"  MAE   : {mae:.4f}")
    print(f"  RMSE  : {rmse:.4f}")
    print(f"  MAPE  : {mape:.4f}%")
    print(f"  WMAPE : {wmape:.4f}%")
    print(f"  R2    : {r2:.6f}")
    print(f"\n  METAS TESIS:")
    print(f"  MAPE  < 2%  : {'✓ OK' if mape  < 2.0  else '✗ NO'} ({mape:.4f}%)")
    print(f"  WMAPE < 2%  : {'✓ OK' if wmape < 2.0  else '✗ NO'} ({wmape:.4f}%)")
    print(f"  R2    > 0.85: {'✓ OK' if r2    > 0.85 else '✗ NO'} ({r2:.6f})")

    # Por rango de precio
    print(f"\n  POR RANGO DE PRECIO:")
    print(f"  {'Rango':<22} {'N':>7} {'MAPE':>8} {'WMAPE':>8} {'R2':>8}")
    print(f"  {'─'*55}")
    for rng_label, lo, hi in [
        ("$5-$20",    5,    20),
        ("$20-$100",  20,   100),
        ("$100-$500", 100,  500),
        ("$500-$2k",  500,  2000),
        ("$2k+",      2000, 99999),
    ]:
        m = (a >= lo) & (a < hi)
        if m.sum() < 5:
            continue
        pp, aa = p[m], a[m]
        mp  = float(np.mean(np.abs((pp-aa)/aa))*100)
        wmp = float(np.sum(np.abs(pp-aa))/np.sum(aa)*100)
        rr  = float(r2_score(aa, pp)) if len(aa) > 1 else 0
        print(f"  {rng_label:<22} {m.sum():>7,} {mp:>7.2f}% {wmp:>7.2f}% {rr:>8.4f}")

    return {"mae":round(mae,4), "rmse":round(rmse,4),
            "mape":round(mape,4), "wmape":round(wmape,4),
            "r2":round(r2,6), "n":int(mask.sum())}


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  OE2: LightGBM — Predicción de Precios Hardware Perú")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    CFG["output_dir"].mkdir(parents=True, exist_ok=True)
    CFG["results_dir"].mkdir(parents=True, exist_ok=True)

    # ── 1. Cargar ────────────────────────────────────────────
    train_df, val_df, test_df, p_low, p_high = load_and_clean(CFG)

    # ── 2. Features ──────────────────────────────────────────
    print("\n" + "="*60)
    print("  2. CONSTRUYENDO FEATURES")
    print("="*60)
    train_feat, le = build_features(train_df, CFG, fit=True)
    val_feat,   _  = build_features(val_df,   CFG, label_encoders=le)
    test_feat,  _  = build_features(test_df,  CFG, label_encoders=le)

    feat_cols = get_feature_cols(train_feat)
    print(f"  Features usadas ({len(feat_cols)}): {feat_cols}")

    X_train = train_feat[feat_cols].values
    y_train = train_feat[CFG["target"]].values
    X_val   = val_feat[feat_cols].values
    y_val   = val_feat[CFG["target"]].values
    X_test  = test_feat[feat_cols].values
    y_test  = test_feat[CFG["target"]].values

    print(f"\n  X_train: {X_train.shape}")
    print(f"  X_val  : {X_val.shape}")
    print(f"  X_test : {X_test.shape}")

    # ── Naive baseline ────────────────────────────────────────
    print("\n  Naive baseline (lag_1):")
    lag1_val  = val_feat["lag_1"].values
    lag1_test = test_feat["lag_1"].values
    mask_v = (y_val > 0) & np.isfinite(lag1_val)
    mask_t = (y_test > 0) & np.isfinite(lag1_test)
    mape_v = np.mean(np.abs((lag1_val[mask_v]-y_val[mask_v])/y_val[mask_v]))*100
    mape_t = np.mean(np.abs((lag1_test[mask_t]-y_test[mask_t])/y_test[mask_t]))*100
    r2_t   = r2_score(y_test[mask_t], lag1_test[mask_t])
    print(f"    val  MAPE: {mape_v:.4f}%")
    print(f"    test MAPE: {mape_t:.4f}% | R2: {r2_t:.6f}")

    # ── 3. Entrenar LightGBM ──────────────────────────────────
    print("\n" + "="*60)
    print("  3. ENTRENANDO LightGBM")
    print("="*60)

    dtrain = lgb.Dataset(X_train, label=y_train,
                         feature_name=feat_cols, free_raw_data=False)
    dval   = lgb.Dataset(X_val,   label=y_val,
                         feature_name=feat_cols, free_raw_data=False,
                         reference=dtrain)

    callbacks = [
        lgb.early_stopping(CFG["early_stopping"], verbose=True),
        lgb.log_evaluation(period=100),
    ]

    model = lgb.train(
        CFG["lgbm_params"],
        dtrain,
        num_boost_round    = CFG["num_boost_round"],
        valid_sets         = [dtrain, dval],
        valid_names        = ["train", "val"],
        callbacks          = callbacks,
    )

    best_iter = model.best_iteration
    print(f"\n  Mejor iteración: {best_iter}")

    # ── 4. Evaluar ────────────────────────────────────────────
    print("\n" + "="*60)
    print("  4. EVALUACIÓN")
    print("="*60)

    preds_val  = model.predict(X_val,  num_iteration=best_iter)
    preds_test = model.predict(X_test, num_iteration=best_iter)

    # Clip a rango válido
    preds_val  = np.clip(preds_val,  p_low, p_high)
    preds_test = np.clip(preds_test, p_low, p_high)

    metrics_val  = compute_metrics(preds_val,  y_val,  "VAL")
    metrics_test = compute_metrics(preds_test, y_test, "TEST")

    # ── 5. Feature importance ─────────────────────────────────
    print("\n" + "="*60)
    print("  5. IMPORTANCIA DE FEATURES (top 10)")
    print("="*60)
    imp = pd.DataFrame({
        "feature"   : model.feature_name(),
        "importance": model.feature_importance(importance_type="gain"),
    }).sort_values("importance", ascending=False)
    for _, row in imp.head(10).iterrows():
        bar = "█" * int(row["importance"] / imp["importance"].max() * 30)
        print(f"  {row['feature']:<20} {bar} {row['importance']:,.0f}")

    # ── 6. Guardar ────────────────────────────────────────────
    model_path = CFG["output_dir"] / "lgbm_pe2.txt"
    model.save_model(str(model_path))

    results = {
        "model"    : "LightGBM",
        "oe"       : "OE2",
        "timestamp": datetime.now().isoformat(),
        "justificacion": (
            "TFT descartado: solo 9 días de historia (necesita 30+). "
            "LightGBM elegido por robustez con datos tabulares escasos."
        ),
        "config": {
            "num_boost_round": CFG["num_boost_round"],
            "best_iteration" : best_iter,
            "features"       : feat_cols,
            **{k: v for k, v in CFG["lgbm_params"].items()
               if k in ["objective","learning_rate","num_leaves"]},
        },
        "naive_baseline": {
            "test_mape": round(float(mape_t), 4),
            "test_r2"  : round(float(r2_t),   6),
        },
        "metrics_val" : metrics_val,
        "metrics_test": metrics_test,
        "metas_tesis" : {
            "mape_lt_2pct" : metrics_test["mape"]  < 2.0,
            "wmape_lt_2pct": metrics_test["wmape"] < 2.0,
            "r2_gt_085"    : metrics_test["r2"]    > 0.85,
        },
        "checkpoint": str(model_path),
    }
    out = CFG["results_dir"] / "pe2_lgbm_metrics.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print("  OE2 LightGBM COMPLETADO")
    print(f"  MAPE  : {metrics_test['mape']:.4f}%")
    print(f"  WMAPE : {metrics_test['wmape']:.4f}%")
    print(f"  R2    : {metrics_test['r2']:.6f}")
    print(f"  Modelo: {model_path}")
    print(f"  JSON  : {out}")
    print("=" * 60)