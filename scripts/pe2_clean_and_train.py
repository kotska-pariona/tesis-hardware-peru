"""
pe2_clean_and_train.py — OE2: TFT con limpieza agresiva de outliers v1
=======================================================================
Problema detectado: train.csv tiene valores aberrantes extremos
  - Precios negativos (hasta -5e18)
  - Precios de cuatrillones de USD
  - Causados por MICE/feature_engineering sobre datos corruptos

Solución:
  1. Limpiar price_usd y todos los lags/features con winsorizing
  2. Recalcular features numéricas desde cero sobre datos limpios
  3. Entrenar TFT sobre datos saneados
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
from pytorch_forecasting.metrics import QuantileLoss

warnings.filterwarnings("ignore")
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["TF_CPP_MIN_LOG_LEVEL"]  = "3"
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
torch.set_float32_matmul_precision("medium")

# ══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════
CFG = {
    "data_dir"    : Path("data/processed"),
    "output_dir"  : Path("models/pe2_tft"),
    "results_dir" : Path("results"),
    "logs_dir"    : Path("logs/pe2_tft"),

    # Rango de precios válidos en USD (hardware de cómputo Perú)
    # Ajustar si hay productos > $5000 legítimos
    "price_min"   : 0.50,       # mínimo absoluto
    "price_max"   : 15_000.0,   # máximo absoluto (~PC gamer top)
    "price_p_low" : 0.001,      # percentil inferior para winsorizing
    "price_p_high": 0.999,      # percentil superior para winsorizing

    # Arquitectura TFT
    "encoder_length"        : 7,
    "prediction_length"     : 1,
    "min_encoder_length"    : 2,

    "hidden_size"           : 64,
    "attention_head_size"   : 4,
    "dropout"               : 0.1,
    "hidden_continuous_size": 32,
    "learning_rate"         : 1e-3,

    "batch_size"            : 128,
    "max_epochs"            : 50,
    "patience"              : 7,
    "gradient_clip_val"     : 0.1,
    "num_workers"           : 0,

    "target"    : "price_usd",
    "group_ids" : ["sku", "source"],
    "static_categoricals": ["category"],
}

# ══════════════════════════════════════════════════════════════
# 1. CARGA Y LIMPIEZA AGRESIVA
# ══════════════════════════════════════════════════════════════
def load_and_clean(cfg):
    print("\n" + "="*60)
    print("  1. CARGANDO Y LIMPIANDO DATOS")
    print("="*60)

    splits = {}
    for split in ["train", "val", "test"]:
        df = pd.read_csv(cfg["data_dir"] / f"{split}.csv", low_memory=False)
        splits[split] = df
        p = df[cfg["target"]].dropna()
        print(f"  {split} RAW: n={len(df):,} | "
              f"min={p.min():.2f} | med={p.median():.2f} | max={p.max():.2f}")

    # ── Calcular límites de precio desde train LIMPIO ────────
    train_p = splits["train"][cfg["target"]].dropna()

    # Paso 1: filtro absoluto (eliminar físicamente imposibles)
    mask_abs = (train_p >= cfg["price_min"]) & (train_p <= cfg["price_max"])
    train_p_clean = train_p[mask_abs]

    # Paso 2: winsorizing sobre los que pasaron el filtro absoluto
    p_low  = train_p_clean.quantile(cfg["price_p_low"])
    p_high = train_p_clean.quantile(cfg["price_p_high"])
    print(f"\n  Límites de precio calculados desde train:")
    print(f"    Absolutos  : [{cfg['price_min']:.2f}, {cfg['price_max']:,.2f}]")
    print(f"    Percentiles: [{p_low:.4f}, {p_high:.4f}]")
    print(f"    Usando     : [{p_low:.4f}, {p_high:.4f}]")

    cleaned = {}
    for split, df in splits.items():
        df = df.copy()
        n_before = len(df)

        # Limpiar target: filtro absoluto + winsorizing
        df[cfg["target"]] = df[cfg["target"]].clip(lower=p_low, upper=p_high)
        mask_valid = (
            df[cfg["target"]].notna() &
            (df[cfg["target"]] >= cfg["price_min"]) &
            (df[cfg["target"]] <= cfg["price_max"])
        )
        df = df[mask_valid].copy()

        # Limpiar categóricas
        for col in cfg["static_categoricals"] + cfg["group_ids"]:
            if col in df.columns:
                df[col] = df[col].fillna("unknown").astype(str)

        # Limpiar price_date
        df["price_date"] = pd.to_datetime(df["price_date"], errors="coerce")
        df = df[df["price_date"].notna()].copy()

        n_after = len(df)
        p = df[cfg["target"]]
        print(f"\n  {split} CLEAN: {n_before:,} → {n_after:,} filas "
              f"({100*(n_before-n_after)/n_before:.1f}% removidas)")
        print(f"    min={p.min():.2f} | med={p.median():.2f} | "
              f"max={p.max():.2f} | std={p.std():.2f}")

        cleaned[split] = df

    return cleaned["train"], cleaned["val"], cleaned["test"], p_low, p_high


# ══════════════════════════════════════════════════════════════
# 2. RECALCULAR FEATURES NUMÉRICAS DESDE CERO
# ══════════════════════════════════════════════════════════════
def recompute_features(df, cfg):
    """
    Recalcula lags y medias móviles sobre price_usd ya limpio.
    Garantiza que NO queden NaN en ninguna feature numérica.
    """
    df = df.copy()
    df = df.sort_values(cfg["group_ids"] + ["price_date"])
    grp = df.groupby(cfg["group_ids"])[cfg["target"]]

    # Lags — fillna con el propio precio (primer registro del SKU)
    df["price_usd_lag_1"] = grp.shift(1).fillna(df[cfg["target"]])
    df["price_usd_lag_2"] = grp.shift(2).fillna(df[cfg["target"]])

    # Medias móviles — min_periods=1 evita NaN, fillna como seguro extra
    df["price_usd_ma_2"] = (
        grp.transform(lambda x: x.shift(1).rolling(2, min_periods=1).mean())
        .fillna(df[cfg["target"]])
    )
    df["price_usd_ma_3"] = (
        grp.transform(lambda x: x.shift(1).rolling(3, min_periods=1).mean())
        .fillna(df[cfg["target"]])
    )

    # Desviaciones estándar — 0 cuando no hay suficientes puntos
    df["price_usd_std_2"] = (
        grp.transform(lambda x: x.shift(1).rolling(2, min_periods=2).std())
        .fillna(0.0)
    )
    df["price_usd_std_3"] = (
        grp.transform(lambda x: x.shift(1).rolling(3, min_periods=2).std())
        .fillna(0.0)
    )

    # Z-score expandido — 0 en el primer registro
    df["price_usd_zscore_90"] = (
        grp.transform(
            lambda x: (x - x.expanding().mean()) / (x.expanding().std() + 1e-8)
        ).fillna(0.0)
    )

    # Verificación final: ninguna feature debe tener NaN
    feature_cols = [
        "price_usd_lag_1", "price_usd_lag_2",
        "price_usd_ma_2",  "price_usd_ma_3",
        "price_usd_std_2", "price_usd_std_3",
        "price_usd_zscore_90",
    ]
    for col in feature_cols:
        n_nan = df[col].isna().sum()
        if n_nan > 0:
            print(f"  ⚠ {col}: {n_nan} NaN restantes → rellenando con 0")
            df[col] = df[col].fillna(0.0)

    return df


# ══════════════════════════════════════════════════════════════
# 3. PREPARAR SPLITS CON TIME_IDX Y CONTEXTO
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

    # Recalcular features sobre datos limpios
    print("  Recalculando features numéricas...")
    train_df = recompute_features(train_df, cfg)
    val_df   = recompute_features(val_df,   cfg)
    test_df  = recompute_features(test_df,  cfg)

    # Contexto para val
    ctx_start = train_df["time_idx"].max() - cfg["encoder_length"] + 1
    val_ctx = pd.concat([
        train_df[train_df["time_idx"] >= ctx_start], val_df
    ], ignore_index=True).drop_duplicates(
        subset=cfg["group_ids"] + ["time_idx"])

    # Contexto para test
    ctx_src = pd.concat([train_df, val_df], ignore_index=True)
    test_ctx = pd.concat([
        ctx_src[ctx_src["time_idx"] >= test_df["time_idx"].min() - cfg["encoder_length"]],
        test_df
    ], ignore_index=True).drop_duplicates(
        subset=cfg["group_ids"] + ["time_idx"])

    # Filtrar series cortas en train
    min_obs  = cfg["encoder_length"] + cfg["prediction_length"]
    counts   = train_df.groupby(cfg["group_ids"])["time_idx"].count()
    valid    = counts[counts >= min_obs].reset_index()[cfg["group_ids"]]
    before   = len(train_df)
    train_df = train_df.merge(valid, on=cfg["group_ids"], how="inner")

    print(f"  train_df : {len(train_df):,} (idx {train_df['time_idx'].min()}–{train_df['time_idx'].max()})")
    print(f"  val_ctx  : {len(val_ctx):,} (idx {val_ctx['time_idx'].min()}–{val_ctx['time_idx'].max()})")
    print(f"  test_ctx : {len(test_ctx):,} (idx {test_ctx['time_idx'].min()}–{test_ctx['time_idx'].max()})")
    print(f"  Series filtradas: {before:,} → {len(train_df):,}")
    print(f"  SKUs en train   : {train_df.groupby(cfg['group_ids']).ngroups:,}")

    # Naive baseline con datos limpios
    mask = test_df["price_usd_lag_1"].notna() & (test_df[cfg["target"]] > 0)
    if mask.sum() > 0:
        p = test_df.loc[mask, "price_usd_lag_1"].values
        a = test_df.loc[mask, cfg["target"]].values
        mape_naive = float(np.mean(np.abs((p - a) / a)) * 100)
        r2_naive   = float(1 - np.sum((a-p)**2) / np.sum((a-np.mean(a))**2))
        print(f"\n  Naive baseline (lag-1) en test LIMPIO:")
        print(f"    MAPE : {mape_naive:.4f}%")
        print(f"    R2   : {r2_naive:.4f}")
        print(f"  → TFT debe superar MAPE={mape_naive:.2f}% y R2={r2_naive:.4f}")

    return train_df, val_ctx, test_ctx, test_df


# ══════════════════════════════════════════════════════════════
# 4. CONSTRUIR DATASETS
# ══════════════════════════════════════════════════════════════
def build_datasets(train_df, val_ctx, test_ctx, cfg):
    print("\n" + "="*60)
    print("  4. CONSTRUYENDO TimeSeriesDataSet")
    print("="*60)

    feature_cols = [
        "price_usd", "price_usd_lag_1", "price_usd_lag_2",
        "price_usd_ma_2",  "price_usd_ma_3",
        "price_usd_std_2", "price_usd_std_3",
        "price_usd_zscore_90",
    ]
    unk_reals = [c for c in feature_cols if c in train_df.columns]
    stat_cats = [c for c in cfg["static_categoricals"]
                 if c in train_df.columns]
    cat_enc   = {col: NaNLabelEncoder(add_nan=True)
                 for col in cfg["group_ids"] + stat_cats}

    # Verificar NaN antes de construir el dataset
    print("  Verificando NaN en features...")
    for col in unk_reals:
        n_nan = train_df[col].isna().sum()
        n_inf = np.isinf(train_df[col]).sum()
        if n_nan > 0 or n_inf > 0:
            print(f"  ⚠ train {col}: {n_nan} NaN, {n_inf} Inf → rellenando")
            train_df[col] = train_df[col].replace(
                [np.inf, -np.inf], np.nan
            ).fillna(0.0)
    for col in unk_reals:
        for ctx_name, ctx_df in [("val_ctx", val_ctx), ("test_ctx", test_ctx)]:
            n = ctx_df[col].isna().sum() + np.isinf(ctx_df[col]).sum()
            if n > 0:
                ctx_df[col] = ctx_df[col].replace(
                    [np.inf, -np.inf], np.nan
                ).fillna(0.0)
    print("  OK — sin NaN/Inf en features")

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
        target_normalizer          = GroupNormalizer(
            groups=cfg["group_ids"], transformation="softplus"),
        add_relative_time_idx      = True,
        add_target_scales          = True,
        add_encoder_length         = True,
        allow_missing_timesteps    = True,
    )
    validation = TimeSeriesDataSet.from_dataset(
        training, val_ctx, predict=True, stop_randomization=True,
        min_prediction_idx=val_ctx["time_idx"].max()
                           - cfg["prediction_length"] + 1,
    )
    testing = TimeSeriesDataSet.from_dataset(
        training, test_ctx, predict=True, stop_randomization=True,
        min_prediction_idx=test_ctx["time_idx"].max()
                           - cfg["prediction_length"] * 2 + 1,
    )
    print(f"  training  : {len(training):,}")
    print(f"  validation: {len(validation):,}")
    print(f"  testing   : {len(testing):,}")
    return training, validation, testing


# ══════════════════════════════════════════════════════════════
# 5. MODELO
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
    print(f"  Parametros: {total:,}")
    if torch.cuda.is_available():
        print(f"  GPU : {torch.cuda.get_device_name(0)}")
        print(f"  VRAM: {torch.cuda.get_device_properties(0).total_memory/1e9:.1f} GB")
    return model


# ══════════════════════════════════════════════════════════════
# 6. ENTRENAMIENTO
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
        train=False, batch_size=cfg["batch_size"] * 2,
        num_workers=cfg["num_workers"])

    callbacks = [
        EarlyStopping(monitor="val_loss", patience=cfg["patience"],
                      mode="min", verbose=True),
        ModelCheckpoint(
            dirpath=str(cfg["output_dir"]),
            filename="tft-clean-{epoch:02d}-{val_loss:.4f}",
            monitor="val_loss", mode="min", save_top_k=1),
        LearningRateMonitor(logging_interval="epoch"),
    ]

    trainer = L.Trainer(
        max_epochs          = cfg["max_epochs"],
        gradient_clip_val   = cfg["gradient_clip_val"],
        callbacks           = callbacks,
        logger              = CSVLogger(str(cfg["logs_dir"]), name="tft_clean"),
        enable_progress_bar = True,
        enable_model_summary= False,
        log_every_n_steps   = 10,
        accelerator         = "gpu" if torch.cuda.is_available() else "cpu",
        devices             = 1,
    )

    print(f"  Dispositivo: {'GPU' if torch.cuda.is_available() else 'CPU'}")
    print(f"  Epochs/patience: {cfg['max_epochs']}/{cfg['patience']}")
    print(f"  Steps/epoch    : {len(train_loader)}")

    trainer.fit(model, train_loader, val_loader)
    best = callbacks[1].best_model_path
    print(f"\n  Mejor checkpoint: {best}")
    return trainer, best


# ══════════════════════════════════════════════════════════════
# 7. EVALUACIÓN MANUAL (sin Trainer interno)
# ══════════════════════════════════════════════════════════════
def evaluate_model(best_ckpt, testing, test_df_clean, cfg):
    print("\n" + "="*60)
    print("  7. EVALUANDO EN TEST")
    print("="*60)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    best_model = TemporalFusionTransformer.load_from_checkpoint(best_ckpt)
    best_model = best_model.to(device)
    best_model.eval()

    test_loader = testing.to_dataloader(
        train=False, batch_size=cfg["batch_size"] * 2,
        num_workers=cfg["num_workers"])

    all_preds, all_actuals = [], []

    with torch.no_grad():
        for batch_x, batch_y in test_loader:
            batch_x = {
                k: v.to(device) if isinstance(v, torch.Tensor) else v
                for k, v in batch_x.items()
            }
            out    = best_model(batch_x)
            # Quantile 0.5 = mediana (índice 1 de [0.1, 0.5, 0.9])
            preds   = out.prediction[:, :, 1].cpu()
            actuals = batch_y[0].cpu()
            all_preds.append(preds)
            all_actuals.append(actuals)

    preds_t   = torch.cat(all_preds,   dim=0).numpy().flatten()
    actuals_t = torch.cat(all_actuals, dim=0).numpy().flatten()

    print(f"  Rango preds  : [{preds_t.min():.4f}, {preds_t.max():.4f}]")
    print(f"  Rango actuals: [{actuals_t.min():.4f}, {actuals_t.max():.4f}]")

    mask = (actuals_t > 0) & np.isfinite(preds_t) & np.isfinite(actuals_t)
    p, a = preds_t[mask], actuals_t[mask]

    mae  = float(np.mean(np.abs(p - a)))
    rmse = float(np.sqrt(np.mean((p - a)**2)))
    mape = float(np.mean(np.abs((p - a) / a)) * 100)
    r2   = float(1 - np.sum((a-p)**2) / np.sum((a-np.mean(a))**2))

    print(f"\n  METRICAS ({mask.sum():,} muestras):")
    print(f"  MAE  : {mae:.4f}")
    print(f"  RMSE : {rmse:.4f}")
    print(f"  MAPE : {mape:.4f}%")
    print(f"  R2   : {r2:.4f}")
    print(f"\n  METAS TESIS:")
    print(f"  MAPE < 2%   : {'✓ OK' if mape < 2.0 else '✗ NO'} ({mape:.4f}%)")
    print(f"  R2   > 0.85 : {'✓ OK' if r2 > 0.85 else '✗ NO'} ({r2:.4f})")

    return {"mae":round(mae,4), "rmse":round(rmse,4),
            "mape":round(mape,4), "r2":round(r2,4),
            "n_samples":int(mask.sum())}


# ══════════════════════════════════════════════════════════════
# 8. GUARDAR
# ══════════════════════════════════════════════════════════════
def save_results(metrics, cfg, best_ckpt):
    cfg["results_dir"].mkdir(parents=True, exist_ok=True)
    out = cfg["results_dir"] / "pe2_tft_metrics.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "model": "TFT", "oe": "OE2",
            "timestamp": datetime.now().isoformat(),
            "config": {k: cfg[k] for k in [
                "encoder_length","prediction_length",
                "hidden_size","batch_size","max_epochs",
                "price_min","price_max"]},
            "metrics": metrics,
            "checkpoint": str(best_ckpt),
            "metas_tesis": {
                "mape_lt_2pct": metrics["mape"] < 2.0,
                "r2_gt_085"   : metrics["r2"]   > 0.85,
            }
        }, f, indent=2, ensure_ascii=False)
    print(f"  Guardado: {out}")
# ══════════════════════════════════════════════════════════════
# MAIN  — reemplazar desde línea ~460 hasta el final
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  OE2: TFT + LIMPIEZA AGRESIVA v1")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # ── Fix: load_and_clean retorna 5 valores ────────────────
    train_df, val_df, test_df, p_low, p_high = load_and_clean(CFG)

    train_df, val_ctx, test_ctx, test_df_clean = prepare_all(
        train_df, val_df, test_df, CFG
    )
    training, validation, testing = build_datasets(
        train_df, val_ctx, test_ctx, CFG
    )
    model = build_model(training, CFG)
    trainer, best_ckpt = train_model(model, training, validation, CFG)
    metrics = evaluate_model(best_ckpt, testing, test_df_clean, CFG)
    save_results(metrics, CFG, best_ckpt)

    print("\n" + "=" * 60)
    print("  OE2 TFT COMPLETADO")
    print(f"  MAPE : {metrics['mape']:.4f}%")
    print(f"  R2   : {metrics['r2']:.4f}")
    print("=" * 60)