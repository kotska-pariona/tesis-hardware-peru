"""
pe2_eval_fix.py — Diagnóstico y re-evaluación con métricas correctas
====================================================================
Problema: MAPE=73% con R2=0.85
Causa:    SKUs con precio bajo ($5-$15) dominan el MAPE
Fix:      1. Usar WMAPE como métrica principal
          2. Segmentar métricas por rango de precio
          3. Identificar qué SKUs generan el MAPE alto
          4. Reentrenar con log-transform del target
"""

import os, sys, json, warnings
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import torch

import lightning as L
from lightning.pytorch.callbacks import (
    EarlyStopping, ModelCheckpoint, LearningRateMonitor
)
from lightning.pytorch.loggers import CSVLogger

from pytorch_forecasting import TemporalFusionTransformer, TimeSeriesDataSet
from pytorch_forecasting.data import GroupNormalizer, NaNLabelEncoder
from pytorch_forecasting.metrics import QuantileLoss, RMSE

warnings.filterwarnings("ignore")
os.environ["PYTHONIOENCODING"] = "utf-8"
torch.set_float32_matmul_precision("medium")

# ══════════════════════════════════════════════════════════════
# CONFIGURACIÓN — igual que antes + log_transform
# ══════════════════════════════════════════════════════════════
CFG = {
    "data_dir"    : Path("data/processed"),
    "output_dir"  : Path("models/pe2_tft_v2"),
    "results_dir" : Path("results"),
    "logs_dir"    : Path("logs/pe2_tft_v2"),

    "price_min"   : 0.50,
    "price_max"   : 15_000.0,
    "price_p_low" : 0.001,
    "price_p_high": 0.999,

    # KEY FIX: log-transform del target para igualar importancia de SKUs baratos/caros
    "log_transform": True,

    "encoder_length"        : 7,
    "prediction_length"     : 1,
    "min_encoder_length"    : 2,

    "hidden_size"           : 64,
    "attention_head_size"   : 4,
    "dropout"               : 0.1,
    "hidden_continuous_size": 32,
    "learning_rate"         : 1e-3,

    "batch_size"            : 128,
    "max_epochs"            : 60,
    "patience"              : 10,
    "gradient_clip_val"     : 0.1,
    "num_workers"           : 0,

    "target"    : "price_usd",
    "group_ids" : ["sku", "source"],
    "static_categoricals": ["category"],
}


# ══════════════════════════════════════════════════════════════
# MÉTRICAS CORRECTAS
# ══════════════════════════════════════════════════════════════
def compute_metrics(preds, actuals, label=""):
    mask = (actuals > 0) & np.isfinite(preds) & np.isfinite(actuals)
    p, a = preds[mask], actuals[mask]

    mae   = float(np.mean(np.abs(p - a)))
    rmse  = float(np.sqrt(np.mean((p - a)**2)))
    mape  = float(np.mean(np.abs((p - a) / a)) * 100)
    wmape = float(np.sum(np.abs(p - a)) / np.sum(a) * 100)   # ← métrica principal
    r2    = float(1 - np.sum((a-p)**2) / np.sum((a-np.mean(a))**2))

    print(f"\n  {'─'*40}")
    print(f"  MÉTRICAS {label} ({mask.sum():,} muestras)")
    print(f"  {'─'*40}")
    print(f"  MAE   : {mae:.4f}")
    print(f"  RMSE  : {rmse:.4f}")
    print(f"  MAPE  : {mape:.4f}%   ← sensible a precios bajos")
    print(f"  WMAPE : {wmape:.4f}%  ← métrica principal (ponderada)")
    print(f"  R2    : {r2:.4f}")
    print(f"\n  METAS TESIS:")
    print(f"  WMAPE < 5%  : {'✓ OK' if wmape < 5.0  else '✗ NO'} ({wmape:.4f}%)")
    print(f"  MAPE  < 5%  : {'✓ OK' if mape  < 5.0  else '✗ NO'} ({mape:.4f}%)")
    print(f"  R2    > 0.85: {'✓ OK' if r2    > 0.85 else '✗ NO'} ({r2:.4f})")

    return {"mae":round(mae,4), "rmse":round(rmse,4),
            "mape":round(mape,4), "wmape":round(wmape,4), "r2":round(r2,4)}


def compute_metrics_by_price_range(preds, actuals):
    """Segmenta métricas por rango de precio para diagnóstico."""
    print("\n  MÉTRICAS POR RANGO DE PRECIO:")
    print(f"  {'Rango':<20} {'N':>7} {'MAPE':>8} {'WMAPE':>8} {'MAE':>8} {'R2':>7}")
    print(f"  {'─'*60}")

    ranges = [
        ("$5-$20   (accesorios)", 5,    20),
        ("$20-$100 (periféricos)", 20,  100),
        ("$100-$500 (mid-range)",  100, 500),
        ("$500-$2k  (high-end)",   500, 2000),
        ("$2k+      (premium)",   2000, 99999),
    ]
    results = {}
    for label, lo, hi in ranges:
        mask = (actuals >= lo) & (actuals < hi) & np.isfinite(preds)
        if mask.sum() < 10:
            continue
        p, a = preds[mask], actuals[mask]
        mape  = float(np.mean(np.abs((p-a)/a))*100)
        wmape = float(np.sum(np.abs(p-a))/np.sum(a)*100)
        mae   = float(np.mean(np.abs(p-a)))
        r2    = float(1 - np.sum((a-p)**2)/np.sum((a-np.mean(a))**2))
        print(f"  {label:<20} {mask.sum():>7,} {mape:>7.1f}% {wmape:>7.1f}% "
              f"{mae:>7.2f} {r2:>7.4f}")
        results[label] = {"n":int(mask.sum()), "mape":round(mape,2),
                          "wmape":round(wmape,2), "r2":round(r2,4)}
    return results


# ══════════════════════════════════════════════════════════════
# CARGA Y LIMPIEZA (igual que antes)
# ══════════════════════════════════════════════════════════════
def load_and_clean(cfg):
    print("\n" + "="*60)
    print("  1. CARGANDO Y LIMPIANDO DATOS")
    print("="*60)
    splits = {}
    for split in ["train", "val", "test"]:
        df = pd.read_csv(cfg["data_dir"] / f"{split}.csv", low_memory=False)
        splits[split] = df

    train_p = splits["train"][cfg["target"]].dropna()
    mask_abs = (train_p >= cfg["price_min"]) & (train_p <= cfg["price_max"])
    train_p_clean = train_p[mask_abs]
    p_low  = train_p_clean.quantile(cfg["price_p_low"])
    p_high = train_p_clean.quantile(cfg["price_p_high"])

    cleaned = {}
    for split, df in splits.items():
        df = df.copy()
        df[cfg["target"]] = df[cfg["target"]].clip(lower=p_low, upper=p_high)
        mask_valid = (
            df[cfg["target"]].notna() &
            (df[cfg["target"]] >= cfg["price_min"]) &
            (df[cfg["target"]] <= cfg["price_max"])
        )
        df = df[mask_valid].copy()
        for col in cfg["static_categoricals"] + cfg["group_ids"]:
            if col in df.columns:
                df[col] = df[col].fillna("unknown").astype(str)
        df["price_date"] = pd.to_datetime(df["price_date"], errors="coerce")
        df = df[df["price_date"].notna()].copy()
        p = df[cfg["target"]]
        print(f"  {split}: {len(df):,} | min={p.min():.2f} | "
              f"med={p.median():.2f} | max={p.max():.2f}")
        cleaned[split] = df

    return cleaned["train"], cleaned["val"], cleaned["test"], p_low, p_high


# ══════════════════════════════════════════════════════════════
# FEATURES (igual que antes)
# ══════════════════════════════════════════════════════════════
def recompute_features(df, cfg):
    df = df.copy()
    df = df.sort_values(cfg["group_ids"] + ["price_date"])
    grp = df.groupby(cfg["group_ids"])[cfg["target"]]

    df["price_usd_lag_1"] = grp.shift(1).fillna(df[cfg["target"]])
    df["price_usd_lag_2"] = grp.shift(2).fillna(df[cfg["target"]])
    df["price_usd_ma_2"]  = (
        grp.transform(lambda x: x.shift(1).rolling(2, min_periods=1).mean())
        .fillna(df[cfg["target"]])
    )
    df["price_usd_ma_3"]  = (
        grp.transform(lambda x: x.shift(1).rolling(3, min_periods=1).mean())
        .fillna(df[cfg["target"]])
    )
    df["price_usd_std_2"] = (
        grp.transform(lambda x: x.shift(1).rolling(2, min_periods=2).std())
        .fillna(0.0)
    )
    df["price_usd_std_3"] = (
        grp.transform(lambda x: x.shift(1).rolling(3, min_periods=2).std())
        .fillna(0.0)
    )
    df["price_usd_zscore_90"] = (
        grp.transform(
            lambda x: (x - x.expanding().mean()) / (x.expanding().std() + 1e-8)
        ).fillna(0.0)
    )
    feature_cols = [
        "price_usd_lag_1","price_usd_lag_2","price_usd_ma_2",
        "price_usd_ma_3","price_usd_std_2","price_usd_std_3",
        "price_usd_zscore_90",
    ]
    for col in feature_cols:
        df[col] = df[col].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return df


# ══════════════════════════════════════════════════════════════
# PREPARAR SPLITS
# ══════════════════════════════════════════════════════════════
def prepare_all(train_df, val_df, test_df, cfg):
    print("\n" + "="*60)
    print("  3. PREPARANDO SPLITS")
    print("="*60)

    all_dates = pd.concat([
        train_df["price_date"], val_df["price_date"], test_df["price_date"]
    ])
    min_date = all_dates.min()
    for df_ref in [train_df, val_df, test_df]:
        df_ref["time_idx"] = (df_ref["price_date"] - min_date).dt.days.astype(int)

    print("  Recalculando features numéricas...")
    train_df = recompute_features(train_df, cfg)
    val_df   = recompute_features(val_df,   cfg)
    test_df  = recompute_features(test_df,  cfg)

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

    min_obs = cfg["encoder_length"] + cfg["prediction_length"]
    counts  = train_df.groupby(cfg["group_ids"])["time_idx"].count()
    valid   = counts[counts >= min_obs].reset_index()[cfg["group_ids"]]
    train_df = train_df.merge(valid, on=cfg["group_ids"], how="inner")

    print(f"  train_df : {len(train_df):,} | SKUs: {train_df.groupby(cfg['group_ids']).ngroups:,}")
    print(f"  val_ctx  : {len(val_ctx):,}")
    print(f"  test_ctx : {len(test_ctx):,}")

    # Naive baseline
    mask = test_df["price_usd_lag_1"].notna() & (test_df[cfg["target"]] > 0)
    if mask.sum() > 0:
        p = test_df.loc[mask, "price_usd_lag_1"].values
        a = test_df.loc[mask, cfg["target"]].values
        wmape_naive = float(np.sum(np.abs(p-a)) / np.sum(a) * 100)
        mape_naive  = float(np.mean(np.abs((p-a)/a)) * 100)
        r2_naive    = float(1 - np.sum((a-p)**2)/np.sum((a-np.mean(a))**2))
        print(f"\n  Naive baseline (lag-1):")
        print(f"    MAPE  : {mape_naive:.4f}%")
        print(f"    WMAPE : {wmape_naive:.4f}%")
        print(f"    R2    : {r2_naive:.4f}")

    return train_df, val_ctx, test_ctx, test_df


# ══════════════════════════════════════════════════════════════
# DATASETS
# ══════════════════════════════════════════════════════════════
def build_datasets(train_df, val_ctx, test_ctx, cfg):
    print("\n" + "="*60)
    print("  4. CONSTRUYENDO TimeSeriesDataSet")
    print("="*60)

    feature_cols = [
        "price_usd", "price_usd_lag_1", "price_usd_lag_2",
        "price_usd_ma_2", "price_usd_ma_3",
        "price_usd_std_2", "price_usd_std_3",
        "price_usd_zscore_90",
    ]
    unk_reals = [c for c in feature_cols if c in train_df.columns]
    stat_cats = [c for c in cfg["static_categoricals"] if c in train_df.columns]
    cat_enc   = {col: NaNLabelEncoder(add_nan=True)
                 for col in cfg["group_ids"] + stat_cats}

    # Limpiar NaN/Inf en todos los splits
    for col in unk_reals:
        for df in [train_df, val_ctx, test_ctx]:
            df[col] = df[col].replace([np.inf, -np.inf], np.nan).fillna(0.0)

    # KEY FIX: log-transform del target para igualar escala $5 vs $5000
    # GroupNormalizer con log1p hace que el modelo aprenda en escala logarítmica
    # → errores proporcionales en lugar de absolutos → MAPE mejora dramáticamente
    target_normalizer = GroupNormalizer(
        groups=cfg["group_ids"],
        transformation="log1p",          # ← log(1+x): correcto para precios
        center=True,
    )

    training = TimeSeriesDataSet(
        train_df,
        time_idx                   = "time_idx",
        target                     = cfg["target"],
        group_ids                  = cfg["group_ids"],
        min_encoder_length         = cfg["min_encoder_length"],
        max_encoder_length         = cfg["encoder_length"],
        min_prediction_length      = cfg["prediction_length"],
        max_prediction_length      = cfg["prediction_length"],
        time_varying_known_reals   = ["time_idx"],
        time_varying_unknown_reals = unk_reals,
        static_categoricals        = stat_cats,
        categorical_encoders       = cat_enc,
        target_normalizer          = target_normalizer,
        add_relative_time_idx      = True,
        add_target_scales          = True,
        add_encoder_length         = True,
        allow_missing_timesteps    = True,
    )
    validation = TimeSeriesDataSet.from_dataset(
        training, val_ctx, predict=True, stop_randomization=True,
        min_prediction_idx=val_ctx["time_idx"].max() - cfg["prediction_length"] + 1,
    )
    testing = TimeSeriesDataSet.from_dataset(
        training, test_ctx, predict=True, stop_randomization=True,
        min_prediction_idx=test_ctx["time_idx"].max() - cfg["prediction_length"]*2 + 1,
    )
    print(f"  training  : {len(training):,}")
    print(f"  validation: {len(validation):,}")
    print(f"  testing   : {len(testing):,}")
    print(f"  Normalizer: log1p (escala logarítmica)")
    return training, validation, testing


# ══════════════════════════════════════════════════════════════
# MODELO
# ══════════════════════════════════════════════════════════════
def build_model(training, cfg):
    print("\n" + "="*60)
    print("  5. CONSTRUYENDO MODELO TFT")
    print("="*60)
    model = TemporalFusionTransformer.from_dataset(
        training,
        learning_rate              = cfg["learning_rate"],
        hidden_size                = cfg["hidden_size"],
        attention_head_size        = cfg["attention_head_size"],
        dropout                    = cfg["dropout"],
        hidden_continuous_size     = cfg["hidden_continuous_size"],
        loss                       = QuantileLoss(quantiles=[0.1, 0.5, 0.9]),
        log_interval               = 50,
        reduce_on_plateau_patience = 4,
        optimizer                  = "adam",
    )
    total = sum(p.numel() for p in model.parameters())
    print(f"  Parámetros: {total:,}")
    if torch.cuda.is_available():
        print(f"  GPU : {torch.cuda.get_device_name(0)}")
    return model


# ══════════════════════════════════════════════════════════════
# ENTRENAMIENTO
# ══════════════════════════════════════════════════════════════
def train_model(model, training, validation, cfg):
    print("\n" + "="*60)
    print("  6. ENTRENANDO")
    print("="*60)
    cfg["output_dir"].mkdir(parents=True, exist_ok=True)
    cfg["logs_dir"].mkdir(parents=True, exist_ok=True)

    train_loader = training.to_dataloader(
        train=True, batch_size=cfg["batch_size"],
        num_workers=cfg["num_workers"],
        pin_memory=torch.cuda.is_available())
    val_loader = validation.to_dataloader(
        train=False, batch_size=cfg["batch_size"]*2,
        num_workers=cfg["num_workers"])

    callbacks = [
        EarlyStopping(monitor="val_loss", patience=cfg["patience"],
                      mode="min", verbose=True),
        ModelCheckpoint(
            dirpath=str(cfg["output_dir"]),
            filename="tft-v2-{epoch:02d}-{val_loss:.4f}",
            monitor="val_loss", mode="min", save_top_k=1),
        LearningRateMonitor(logging_interval="epoch"),
    ]
    trainer = L.Trainer(
        max_epochs          = cfg["max_epochs"],
        gradient_clip_val   = cfg["gradient_clip_val"],
        callbacks           = callbacks,
        logger              = CSVLogger(str(cfg["logs_dir"]), name="tft_v2"),
        enable_progress_bar = True,
        enable_model_summary= False,
        log_every_n_steps   = 10,
        accelerator         = "gpu" if torch.cuda.is_available() else "cpu",
        devices             = 1,
    )
    print(f"  Epochs/patience: {cfg['max_epochs']}/{cfg['patience']}")
    print(f"  Steps/epoch    : {len(train_loader)}")
    trainer.fit(model, train_loader, val_loader)
    best = callbacks[1].best_model_path
    print(f"\n  Mejor checkpoint: {best}")
    return trainer, best


# ══════════════════════════════════════════════════════════════
# EVALUACIÓN
# ══════════════════════════════════════════════════════════════
def evaluate_model(best_ckpt, testing, cfg):
    print("\n" + "="*60)
    print("  7. EVALUANDO EN TEST")
    print("="*60)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    best_model = TemporalFusionTransformer.load_from_checkpoint(best_ckpt)
    best_model = best_model.to(device).eval()

    test_loader = testing.to_dataloader(
        train=False, batch_size=cfg["batch_size"]*2,
        num_workers=cfg["num_workers"])

    all_preds, all_actuals = [], []
    with torch.no_grad():
        for batch_x, batch_y in test_loader:
            batch_x = {k: v.to(device) if isinstance(v, torch.Tensor) else v
                       for k, v in batch_x.items()}
            out = best_model(batch_x)
            all_preds.append(out.prediction[:, :, 1].cpu())   # quantile 0.5
            all_actuals.append(batch_y[0].cpu())

    preds_t   = torch.cat(all_preds,   dim=0).numpy().flatten()
    actuals_t = torch.cat(all_actuals, dim=0).numpy().flatten()

    print(f"  Rango preds  : [{preds_t.min():.4f}, {preds_t.max():.4f}]")
    print(f"  Rango actuals: [{actuals_t.min():.4f}, {actuals_t.max():.4f}]")

    # Métricas globales
    metrics = compute_metrics(preds_t, actuals_t, "GLOBAL")

    # Métricas por rango de precio
    mask = (actuals_t > 0) & np.isfinite(preds_t)
    by_range = compute_metrics_by_price_range(preds_t[mask], actuals_t[mask])
    metrics["by_price_range"] = by_range

    return metrics


# ══════════════════════════════════════════════════════════════
# GUARDAR
# ══════════════════════════════════════════════════════════════
def save_results(metrics, cfg, best_ckpt):
    cfg["results_dir"].mkdir(parents=True, exist_ok=True)
    out = cfg["results_dir"] / "pe2_tft_v2_metrics.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "model": "TFT_v2_log1p", "oe": "OE2",
            "timestamp": datetime.now().isoformat(),
            "config": {k: cfg[k] for k in [
                "encoder_length","prediction_length",
                "hidden_size","batch_size","max_epochs","log_transform"]},
            "metrics": metrics,
            "checkpoint": str(best_ckpt),
            "metas_tesis": {
                "wmape_lt_5pct": metrics["wmape"] < 5.0,
                "mape_lt_5pct" : metrics["mape"]  < 5.0,
                "r2_gt_085"    : metrics["r2"]     > 0.85,
            }
        }, f, indent=2, ensure_ascii=False)
    print(f"\n  Guardado: {out}")


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  OE2: TFT v2 — log1p normalizer")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    train_df, val_df, test_df, p_low, p_high = load_and_clean(CFG)
    train_df, val_ctx, test_ctx, test_df_clean = prepare_all(
        train_df, val_df, test_df, CFG
    )
    training, validation, testing = build_datasets(
        train_df, val_ctx, test_ctx, CFG
    )
    model   = build_model(training, CFG)
    trainer, best_ckpt = train_model(model, training, validation, CFG)
    metrics = evaluate_model(best_ckpt, testing, CFG)
    save_results(metrics, CFG, best_ckpt)

    print("\n" + "=" * 60)
    print("  OE2 TFT v2 COMPLETADO")
    print(f"  WMAPE : {metrics['wmape']:.4f}%")
    print(f"  MAPE  : {metrics['mape']:.4f}%")
    print(f"  R2    : {metrics['r2']:.4f}")
    print("=" * 60)