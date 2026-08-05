"""
pe2_debug_tft.py — Diagnóstico del pipeline TFT
================================================
Verifica:
1. Escala de preds vs actuals (normalizado vs real)
2. Distribución del val_loss
3. Calidad de los splits
4. Si el modelo aprende algo en train
"""

import os, warnings
from pathlib import Path
import numpy as np
import pandas as pd
import torch
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import lightning as L
from lightning.pytorch.loggers import CSVLogger
from lightning.pytorch.callbacks import ModelCheckpoint, EarlyStopping

from pytorch_forecasting import TemporalFusionTransformer, TimeSeriesDataSet
from pytorch_forecasting.data import GroupNormalizer, NaNLabelEncoder
from pytorch_forecasting.metrics import QuantileLoss

warnings.filterwarnings("ignore")
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
torch.set_float32_matmul_precision("medium")

DATA_DIR   = Path("data/processed")
OUTPUT_DIR = Path("models/pe2_tft")
LOGS_DIR   = Path("logs/pe2_debug")

CFG = {
    "encoder_length"    : 7,
    "prediction_length" : 1,
    "min_encoder_length": 2,
    "hidden_size"       : 64,
    "attention_head_size": 4,
    "dropout"           : 0.1,
    "hidden_continuous_size": 32,
    "learning_rate"     : 1e-3,
    "batch_size"        : 128,
    "num_workers"       : 0,
    "target"            : "price_usd",
    "group_ids"         : ["sku", "source"],
    "time_varying_known_reals": ["time_idx"],
    "time_varying_unknown_reals": [
        "price_usd", "price_usd_lag_1", "price_usd_lag_2",
        "price_usd_ma_2", "price_usd_ma_3",
        "price_usd_std_2", "price_usd_std_3",
        "price_usd_zscore_90",
    ],
    "static_categoricals": ["category"],
}

# ══════════════════════════════════════════════════════════════
# HELPERS (mismo que pe2_train_tft.py)
# ══════════════════════════════════════════════════════════════
def build_time_idx(df, min_date):
    df = df.copy()
    df["price_date"] = pd.to_datetime(df["price_date"])
    df["time_idx"]   = (df["price_date"] - min_date).dt.days.astype(int)
    return df

def clean_df(df, cfg):
    df = df.copy()
    df = df[df[cfg["target"]].notna() & (df[cfg["target"]] > 0)].copy()
    for col in [c for c in cfg["time_varying_unknown_reals"]
                if c in df.columns and c != "time_idx"]:
        df[col] = df[col].fillna(0.0)
    for col in cfg["static_categoricals"] + cfg["group_ids"]:
        if col in df.columns:
            df[col] = df[col].fillna("unknown").astype(str)
    return df

def prepare_all(cfg):
    train_raw = pd.read_csv(DATA_DIR / "train.csv", low_memory=False)
    val_raw   = pd.read_csv(DATA_DIR / "val.csv",   low_memory=False)
    test_raw  = pd.read_csv(DATA_DIR / "test.csv",  low_memory=False)

    all_dates = pd.concat([
        pd.to_datetime(train_raw["price_date"]),
        pd.to_datetime(val_raw["price_date"]),
        pd.to_datetime(test_raw["price_date"]),
    ])
    min_date = all_dates.min()

    train_df = clean_df(build_time_idx(train_raw, min_date), cfg)
    val_df   = clean_df(build_time_idx(val_raw,   min_date), cfg)
    test_df  = clean_df(build_time_idx(test_raw,  min_date), cfg)

    ctx_start = train_df["time_idx"].max() - cfg["encoder_length"] + 1
    val_ctx = pd.concat([
        train_df[train_df["time_idx"] >= ctx_start], val_df
    ], ignore_index=True).drop_duplicates(
        subset=cfg["group_ids"] + ["time_idx"])

    ctx_src = pd.concat([train_df, val_df], ignore_index=True)
    test_ctx = pd.concat([
        ctx_src[ctx_src["time_idx"] >= test_df["time_idx"].min() - cfg["encoder_length"]],
        test_df
    ], ignore_index=True).drop_duplicates(
        subset=cfg["group_ids"] + ["time_idx"])

    min_obs  = cfg["encoder_length"] + cfg["prediction_length"]
    counts   = train_df.groupby(cfg["group_ids"])["time_idx"].count()
    valid    = counts[counts >= min_obs].reset_index()[cfg["group_ids"]]
    train_df = train_df.merge(valid, on=cfg["group_ids"], how="inner")

    return train_df, val_ctx, test_ctx, val_df, test_df

def make_dataset(train_df, ctx_df, cfg, predict=False, min_pred_idx=None):
    unk_reals = [c for c in cfg["time_varying_unknown_reals"] if c in train_df.columns]
    stat_cats = [c for c in cfg["static_categoricals"] if c in train_df.columns]
    cat_enc   = {col: NaNLabelEncoder(add_nan=True)
                 for col in cfg["group_ids"] + stat_cats}

    training = TimeSeriesDataSet(
        train_df,
        time_idx=cfg["target"] and "time_idx",
        target=cfg["target"],
        group_ids=cfg["group_ids"],
        min_encoder_length=cfg["min_encoder_length"],
        max_encoder_length=cfg["encoder_length"],
        min_prediction_length=cfg["prediction_length"],
        max_prediction_length=cfg["prediction_length"],
        time_varying_known_reals=cfg["time_varying_known_reals"],
        time_varying_unknown_reals=unk_reals,
        static_categoricals=stat_cats,
        categorical_encoders=cat_enc,
        target_normalizer=GroupNormalizer(
            groups=cfg["group_ids"], transformation="softplus"),
        add_relative_time_idx=True,
        add_target_scales=True,
        add_encoder_length=True,
        allow_missing_timesteps=True,
    )
    if ctx_df is None:
        return training

    ds = TimeSeriesDataSet.from_dataset(
        training, ctx_df, predict=predict,
        stop_randomization=predict,
        min_prediction_idx=min_pred_idx,
    )
    return training, ds

# ══════════════════════════════════════════════════════════════
# DIAGNÓSTICO 1: Distribución de precios por split
# ══════════════════════════════════════════════════════════════
def diag_price_distribution(cfg):
    print("\n" + "="*60)
    print("  DIAG 1: DISTRIBUCIÓN DE PRECIOS POR SPLIT")
    print("="*60)
    for split in ["train", "val", "test"]:
        df = pd.read_csv(DATA_DIR / f"{split}.csv", low_memory=False)
        p  = df[cfg["target"]].dropna()
        print(f"  {split:5s}: n={len(p):>8,} | "
              f"min={p.min():>8.2f} | "
              f"med={p.median():>8.2f} | "
              f"max={p.max():>10.2f} | "
              f"std={p.std():>8.2f}")

# ══════════════════════════════════════════════════════════════
# DIAGNÓSTICO 2: Escala de preds vs actuals en el dataloader
# ══════════════════════════════════════════════════════════════
def diag_dataloader_scale(training_ds, val_ctx, cfg):
    print("\n" + "="*60)
    print("  DIAG 2: ESCALA PREDS vs ACTUALS EN DATALOADER")
    print("="*60)

    _, val_ds = make_dataset(
        # reusar training_ds como referencia
        None, None, cfg
    ) if False else (None, TimeSeriesDataSet.from_dataset(
        training_ds, val_ctx, predict=True, stop_randomization=True,
        min_prediction_idx=val_ctx["time_idx"].max()
                           - cfg["prediction_length"] + 1,
    ))

    loader = val_ds.to_dataloader(train=False, batch_size=64, num_workers=0)
    batch_x, batch_y = next(iter(loader))

    actuals_raw = batch_y[0]
    print(f"  batch_y[0] (actuals del loader):")
    print(f"    shape : {actuals_raw.shape}")
    print(f"    min   : {actuals_raw.min():.4f}")
    print(f"    max   : {actuals_raw.max():.4f}")
    print(f"    mean  : {actuals_raw.mean():.4f}")
    print(f"    → {'NORMALIZADO (0-10)' if actuals_raw.max() < 50 else 'ESCALA REAL (USD)'}")

    # target_scale si existe
    if "target_scale" in batch_x:
        ts = batch_x["target_scale"]
        print(f"  target_scale: min={ts.min():.2f}, max={ts.max():.2f}, mean={ts.mean():.2f}")

    return val_ds

# ══════════════════════════════════════════════════════════════
# DIAGNÓSTICO 3: ¿El modelo aprende? Curva de loss
# ══════════════════════════════════════════════════════════════
def diag_training_curve(cfg):
    print("\n" + "="*60)
    print("  DIAG 3: CURVA DE ENTRENAMIENTO (CSV logs)")
    print("="*60)

    log_files = list(LOGS_DIR.glob("**/metrics.csv"))
    if not log_files:
        # Buscar también en logs/pe2_tft
        log_files = list(Path("logs/pe2_tft").glob("**/metrics.csv"))

    if not log_files:
        print("  No se encontraron logs CSV. Ejecutar entrenamiento primero.")
        return

    log_file = sorted(log_files)[-1]
    print(f"  Leyendo: {log_file}")
    df = pd.read_csv(log_file)
    print(df[["epoch", "train_loss_epoch", "val_loss"]].dropna().to_string(index=False))

# ══════════════════════════════════════════════════════════════
# DIAGNÓSTICO 4: Overlap de SKUs entre splits
# ══════════════════════════════════════════════════════════════
def diag_sku_overlap(cfg):
    print("\n" + "="*60)
    print("  DIAG 4: OVERLAP DE SKUs ENTRE SPLITS")
    print("="*60)
    train = pd.read_csv(DATA_DIR / "train.csv", low_memory=False)
    val   = pd.read_csv(DATA_DIR / "val.csv",   low_memory=False)
    test  = pd.read_csv(DATA_DIR / "test.csv",  low_memory=False)

    train_skus = set(train["sku"].astype(str))
    val_skus   = set(val["sku"].astype(str))
    test_skus  = set(test["sku"].astype(str))

    print(f"  SKUs únicos train : {len(train_skus):,}")
    print(f"  SKUs únicos val   : {len(val_skus):,}")
    print(f"  SKUs únicos test  : {len(test_skus):,}")
    print(f"  val  ∩ train      : {len(val_skus & train_skus):,} "
          f"({100*len(val_skus & train_skus)/len(val_skus):.1f}%)")
    print(f"  test ∩ train      : {len(test_skus & train_skus):,} "
          f"({100*len(test_skus & train_skus)/len(test_skus):.1f}%)")
    print(f"  val  NUEVO (no en train): {len(val_skus - train_skus):,}")
    print(f"  test NUEVO (no en train): {len(test_skus - train_skus):,}")

# ══════════════════════════════════════════════════════════════
# DIAGNÓSTICO 5: Variación de precios por SKU (¿hay señal?)
# ══════════════════════════════════════════════════════════════
def diag_price_variation(cfg):
    print("\n" + "="*60)
    print("  DIAG 5: ¿HAY VARIACIÓN DE PRECIOS? (señal para predecir)")
    print("="*60)
    train = pd.read_csv(DATA_DIR / "train.csv", low_memory=False)
    train["price_date"] = pd.to_datetime(train["price_date"])

    # Variación por SKU
    grp = train.groupby("sku")[cfg["target"]]
    variation = grp.std() / grp.mean()  # CV (coeficiente de variación)
    variation = variation.dropna()

    print(f"  SKUs con CV > 0.01 (hay variación): "
          f"{(variation > 0.01).sum():,} / {len(variation):,} "
          f"({100*(variation > 0.01).mean():.1f}%)")
    print(f"  SKUs con CV = 0    (precio fijo)  : "
          f"{(variation == 0).sum():,} / {len(variation):,} "
          f"({100*(variation == 0).mean():.1f}%)")
    print(f"  CV mediano: {variation.median():.4f}")
    print(f"  CV p95    : {variation.quantile(0.95):.4f}")

    # Días únicos por SKU
    days_per_sku = train.groupby("sku")["price_date"].nunique()
    print(f"\n  Días de historia por SKU:")
    print(f"    min  : {days_per_sku.min()}")
    print(f"    med  : {days_per_sku.median():.0f}")
    print(f"    max  : {days_per_sku.max()}")
    print(f"    ≥ 7d : {(days_per_sku >= 7).sum():,} SKUs "
          f"({100*(days_per_sku >= 7).mean():.1f}%)")
    print(f"    ≥ 5d : {(days_per_sku >= 5).sum():,} SKUs "
          f"({100*(days_per_sku >= 5).mean():.1f}%)")

# ══════════════════════════════════════════════════════════════
# DIAGNÓSTICO 6: Naive baseline (precio de ayer = precio hoy)
# ══════════════════════════════════════════════════════════════
def diag_naive_baseline(cfg):
    print("\n" + "="*60)
    print("  DIAG 6: NAIVE BASELINE (lag-1)")
    print("="*60)
    test = pd.read_csv(DATA_DIR / "test.csv", low_memory=False)
    test["price_date"] = pd.to_datetime(test["price_date"])
    test = test.sort_values(["sku", "source", "price_date"])

    if "price_usd_lag_1" in test.columns:
        mask = test["price_usd_lag_1"].notna() & (test[cfg["target"]] > 0)
        p = test.loc[mask, "price_usd_lag_1"].values
        a = test.loc[mask, cfg["target"]].values
        mae  = np.mean(np.abs(p - a))
        mape = np.mean(np.abs((p - a) / a)) * 100
        r2   = 1 - np.sum((a-p)**2) / np.sum((a-np.mean(a))**2)
        print(f"  Naive lag-1 en test ({mask.sum():,} muestras):")
        print(f"    MAE  : {mae:.4f}")
        print(f"    MAPE : {mape:.4f}%")
        print(f"    R2   : {r2:.4f}")
        print(f"\n  → El TFT debe superar estos valores para ser útil")
    else:
        print("  Columna price_usd_lag_1 no encontrada en test.csv")

# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  DIAGNÓSTICO TFT — OE2")
    print("=" * 60)

    diag_price_distribution(CFG)
    diag_sku_overlap(CFG)
    diag_price_variation(CFG)
    diag_naive_baseline(CFG)
    diag_training_curve(CFG)

    print("\n" + "=" * 60)
    print("  DIAGNÓSTICO COMPLETADO")
    print("=" * 60)