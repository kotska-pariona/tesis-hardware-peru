"""
pe2_train_tft.py — OE2: Temporal Fusion Transformer v6
=======================================================
Fix v6: inferencia manual sin Trainer (evita TensorBoard
        que pytorch_forecasting crea internamente en predict())
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

from pytorch_forecasting import (
    TemporalFusionTransformer, TimeSeriesDataSet
)
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

    "time_varying_known_reals": ["time_idx"],
    "time_varying_unknown_reals": [
        "price_usd", "price_usd_lag_1", "price_usd_lag_2",
        "price_usd_ma_2", "price_usd_ma_3",
        "price_usd_std_2", "price_usd_std_3",
        "price_usd_zscore_90",
    ],
    "static_categoricals": ["category"],
    "static_reals"       : [],
}

# ══════════════════════════════════════════════════════════════
# 1. CARGA
# ══════════════════════════════════════════════════════════════
def load_and_prepare(cfg):
    print("\n" + "="*60)
    print("  1. CARGANDO DATOS")
    print("="*60)
    train = pd.read_csv(cfg["data_dir"] / "train.csv", low_memory=False)
    val   = pd.read_csv(cfg["data_dir"] / "val.csv",   low_memory=False)
    test  = pd.read_csv(cfg["data_dir"] / "test.csv",  low_memory=False)
    print(f"  train: {len(train):,} | {train['price_date'].nunique()} dias")
    print(f"  val  : {len(val):,} | {val['price_date'].nunique()} dias")
    print(f"  test : {len(test):,} | {test['price_date'].nunique()} dias")
    return train, val, test


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


def prepare_all(train_raw, val_raw, test_raw, cfg):
    print("\n" + "="*60)
    print("  2. PREPARANDO SPLITS CON CONTEXTO HISTÓRICO")
    print("="*60)

    all_dates = pd.concat([
        pd.to_datetime(train_raw["price_date"]),
        pd.to_datetime(val_raw["price_date"]),
        pd.to_datetime(test_raw["price_date"]),
    ])
    min_date = all_dates.min()
    print(f"  Rango: {min_date.date()} → {all_dates.max().date()}")

    train_df = clean_df(build_time_idx(train_raw, min_date), cfg)
    val_df   = clean_df(build_time_idx(val_raw,   min_date), cfg)
    test_df  = clean_df(build_time_idx(test_raw,  min_date), cfg)

    # Contexto para val
    ctx_start_val = train_df["time_idx"].max() - cfg["encoder_length"] + 1
    val_ctx = pd.concat([
        train_df[train_df["time_idx"] >= ctx_start_val], val_df
    ], ignore_index=True).drop_duplicates(
        subset=cfg["group_ids"] + ["time_idx"])

    # Contexto para test
    ctx_src        = pd.concat([train_df, val_df], ignore_index=True)
    ctx_start_test = test_df["time_idx"].min() - cfg["encoder_length"]
    test_ctx = pd.concat([
        ctx_src[ctx_src["time_idx"] >= ctx_start_test], test_df
    ], ignore_index=True).drop_duplicates(
        subset=cfg["group_ids"] + ["time_idx"])

    # Filtrar series cortas
    min_obs  = cfg["encoder_length"] + cfg["prediction_length"]
    counts   = train_df.groupby(cfg["group_ids"])["time_idx"].count()
    valid    = counts[counts >= min_obs].reset_index()[cfg["group_ids"]]
    before   = len(train_df)
    train_df = train_df.merge(valid, on=cfg["group_ids"], how="inner")

    print(f"  train_df : {len(train_df):,} (idx {train_df['time_idx'].min()}–{train_df['time_idx'].max()})")
    print(f"  val_ctx  : {len(val_ctx):,} (idx {val_ctx['time_idx'].min()}–{val_ctx['time_idx'].max()})")
    print(f"  test_ctx : {len(test_ctx):,} (idx {test_ctx['time_idx'].min()}–{test_ctx['time_idx'].max()})")
    print(f"  Series filtradas: {before:,} → {len(train_df):,} (min_obs={min_obs})")
    print(f"  SKUs en train: {train_df.groupby(cfg['group_ids']).ngroups:,}")
    return train_df, val_ctx, test_ctx


# ══════════════════════════════════════════════════════════════
# 3. DATASETS
# ══════════════════════════════════════════════════════════════
def build_datasets(train_df, val_ctx, test_ctx, cfg):
    print("\n" + "="*60)
    print("  3. CONSTRUYENDO TimeSeriesDataSet")
    print("="*60)

    unk_reals = [c for c in cfg["time_varying_unknown_reals"]
                 if c in train_df.columns]
    stat_cats = [c for c in cfg["static_categoricals"]
                 if c in train_df.columns]
    cat_enc   = {col: NaNLabelEncoder(add_nan=True)
                 for col in cfg["group_ids"] + stat_cats}

    training = TimeSeriesDataSet(
        train_df,
        time_idx                   = "time_idx",
        target                     = cfg["target"],
        group_ids                  = cfg["group_ids"],
        min_encoder_length         = cfg["min_encoder_length"],
        max_encoder_length         = cfg["encoder_length"],
        min_prediction_length      = cfg["prediction_length"],
        max_prediction_length      = cfg["prediction_length"],
        time_varying_known_reals   = cfg["time_varying_known_reals"],
        time_varying_unknown_reals = unk_reals,
        static_categoricals        = stat_cats,
        static_reals               = cfg["static_reals"],
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
# 4. MODELO
# ══════════════════════════════════════════════════════════════
def build_model(training, cfg):
    print("\n" + "="*60)
    print("  4. CONSTRUYENDO MODELO TFT")
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
# 5. ENTRENAMIENTO
# ══════════════════════════════════════════════════════════════
def train_model(model, training, validation, cfg):
    print("\n" + "="*60)
    print("  5. ENTRENANDO")
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
            filename="tft-{epoch:02d}-{val_loss:.4f}",
            monitor="val_loss", mode="min", save_top_k=1),
        LearningRateMonitor(logging_interval="epoch"),
    ]

    trainer = L.Trainer(
        max_epochs          = cfg["max_epochs"],
        gradient_clip_val   = cfg["gradient_clip_val"],
        callbacks           = callbacks,
        logger              = CSVLogger(str(cfg["logs_dir"]), name="tft"),
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
# 6. EVALUACIÓN — inferencia manual sin Trainer
# ══════════════════════════════════════════════════════════════
def evaluate_model(best_ckpt, testing, cfg):
    """
    Inferencia manual con PyTorch puro.
    Evita que pytorch_forecasting cree un Trainer interno
    que intenta usar TensorBoard (roto por conflicto TF/OpenSSL).
    """
    print("\n" + "="*60)
    print("  6. EVALUANDO EN TEST (inferencia manual)")
    print("="*60)

    # Cargar modelo
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    best_model = TemporalFusionTransformer.load_from_checkpoint(best_ckpt)
    best_model = best_model.to(device)
    best_model.eval()
    print(f"  Modelo cargado en: {device}")

    test_loader = testing.to_dataloader(
        train=False,
        batch_size=cfg["batch_size"] * 2,
        num_workers=cfg["num_workers"],
    )

    all_preds   = []
    all_actuals = []

    with torch.no_grad():
        for batch_x, batch_y in test_loader:
            # Mover batch a GPU
            batch_x = {
                k: v.to(device) if isinstance(v, torch.Tensor) else v
                for k, v in batch_x.items()
            }

            # Forward pass
            out = best_model(batch_x)

            # out.prediction shape: (batch, time, n_quantiles)
            # Tomar quantile 0.5 (índice 1 de [0.1, 0.5, 0.9])
            preds = out.prediction[:, :, 1].cpu()   # mediana

            # Actuals: batch_y[0] shape (batch, time)
            actuals = batch_y[0].cpu()

            all_preds.append(preds)
            all_actuals.append(actuals)

    preds_t   = torch.cat(all_preds,   dim=0).numpy().flatten()
    actuals_t = torch.cat(all_actuals, dim=0).numpy().flatten()

    # Métricas
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
    print(f"  MAPE < 2%   : {'OK' if mape < 2.0 else 'NO'} ({mape:.4f}%)")
    print(f"  R2   > 0.85 : {'OK' if r2 > 0.85 else 'NO'} ({r2:.4f})")

    return {"mae":round(mae,4), "rmse":round(rmse,4),
            "mape":round(mape,4), "r2":round(r2,4),
            "n_samples":int(mask.sum())}


# ══════════════════════════════════════════════════════════════
# 7. GUARDAR
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
                "hidden_size","batch_size","max_epochs"]},
            "metrics": metrics,
            "checkpoint": str(best_ckpt),
            "metas_tesis": {
                "mape_lt_2pct": metrics["mape"] < 2.0,
                "r2_gt_085"   : metrics["r2"]   > 0.85,
            }
        }, f, indent=2, ensure_ascii=False)
    print(f"  Guardado: {out}")


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  OE2: TEMPORAL FUSION TRANSFORMER v6")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print(f"  lightning           : {L.__version__}")
    try:
        import pytorch_forecasting as pf
        print(f"  pytorch-forecasting : {pf.__version__}")
    except ImportError:
        print("  ERROR: pip install pytorch-forecasting"); sys.exit(1)

    train_raw, val_raw, test_raw = load_and_prepare(CFG)
    train_df, val_ctx, test_ctx  = prepare_all(train_raw, val_raw, test_raw, CFG)
    training, validation, testing = build_datasets(train_df, val_ctx, test_ctx, CFG)
    model = build_model(training, CFG)
    trainer, best_ckpt = train_model(model, training, validation, CFG)
    metrics = evaluate_model(best_ckpt, testing, CFG)
    save_results(metrics, CFG, best_ckpt)

    print("\n" + "=" * 60)
    print("  OE2 TFT COMPLETADO")
    print(f"  MAPE : {metrics['mape']:.4f}%")
    print(f"  R2   : {metrics['r2']:.4f}")
    print("=" * 60)