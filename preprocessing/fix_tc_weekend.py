"""
fix_tc_weekend.py
Uso: python preprocessing/fix_tc_weekend.py
Correr cada LUNES antes de procesar nuevos datos.
Detecta y corrige TCs inválidos (fines de semana/feriados) usando ffill.
"""
import pandas as pd
import numpy as np
from pathlib import Path

TC_MIN   = 3.50   # rango histórico válido PEN/USD
TC_MAX   = 4.20
SRC_DIR  = Path("data/processed")
OUT_DIR  = Path("data/features")

def corregir_tc(df: pd.DataFrame) -> pd.DataFrame:
    """
    Recalcula price_usd donde el TC implícito es inválido.
    TC implícito = price_pen / price_usd
    Fines de semana heredan el TC del viernes (ffill).
    """
    df = df.copy()
    df["price_date"] = pd.to_datetime(df["price_date"], errors="coerce")

    # Calcular TC implícito por fila
    df["_tc_impl"] = (df["price_pen"] / df["price_usd"]).replace([np.inf, -np.inf], np.nan)

    # TC diario = mediana del TC implícito de ese día
    tc_diario = (
        df.groupby("price_date")["_tc_impl"]
        .median()
        .reset_index()
        .rename(columns={"_tc_impl": "_tc_dia"})
        .sort_values("price_date")
    )

    # Marcar días con TC fuera de rango como NaN
    tc_diario.loc[
        ~tc_diario["_tc_dia"].between(TC_MIN, TC_MAX), "_tc_dia"
    ] = np.nan

    # Forward-fill: fin de semana hereda el viernes
    tc_diario["_tc_dia"] = tc_diario["_tc_dia"].ffill().fillna(3.70)

    print("  TC diario detectado:")
    for _, row in tc_diario.iterrows():
        flag = "✅" if TC_MIN <= row["_tc_dia"] <= TC_MAX else "🔧"
        print(f"    {flag} {row['price_date'].date()}  TC={row['_tc_dia']:.4f}")

    # Merge y recalcular solo filas con TC malo
    df = df.merge(tc_diario, on="price_date", how="left")
    mask_bad = ~df["_tc_impl"].between(TC_MIN, TC_MAX) | df["_tc_impl"].isna()
    n_fix = mask_bad.sum()

    if n_fix > 0:
        df.loc[mask_bad, "price_usd"] = (
            df.loc[mask_bad, "price_pen"] / df.loc[mask_bad, "_tc_dia"]
        ).round(4)
        print(f"  🔧 Corregidas {n_fix} filas")
    else:
        print(f"  ✅ Sin correcciones necesarias")

    df.drop(columns=["_tc_impl", "_tc_dia"], inplace=True)
    return df


def recalcular_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["sku", "price_date"]).reset_index(drop=True)
    grp = df.groupby("sku")["price_usd"]

    df["price_usd_lag_1"]   = grp.shift(1)
    df["price_usd_ma_3"]    = grp.transform(lambda x: x.rolling(3, min_periods=1).mean())
    df["price_usd_ma_5"]    = grp.transform(lambda x: x.rolling(5, min_periods=1).mean())
    df["price_usd_std_3"]   = grp.transform(lambda x: x.rolling(3, min_periods=2).std())
    df["price_usd_std_5"]   = grp.transform(lambda x: x.rolling(5, min_periods=2).std())
    df["price_usd_pct_chg"] = grp.transform(lambda x: x.pct_change())

    cat_mean = df.groupby(["category", "price_date"])["price_usd"].transform("mean")
    df["price_vs_cat_mean"] = (df["price_usd"] / cat_mean.replace(0, np.nan)).round(4)
    df.drop(columns=["price_usd_zscore"], inplace=True, errors="ignore")
    return df


if __name__ == "__main__":
    print("=" * 60)
    print("  FIX TC WEEKEND — CORRECCIÓN AUTOMÁTICA")
    print("=" * 60)

    SPLITS = ["train", "val", "test"]
    dfs = []

    for s in SPLITS:
        # Leer desde processed (originales) si existen, si no desde features
        src = SRC_DIR / f"{s}_features.csv"
        if not src.exists():
            src = OUT_DIR / f"{s}_features.csv"
        df = pd.read_csv(src, low_memory=False)
        df["_split"] = s
        dfs.append(df)

    # Unir, alinear columnas
    all_cols = sorted(set().union(*[set(d.columns) for d in dfs]))
    for i, df in enumerate(dfs):
        for col in all_cols:
            if col not in df.columns:
                dfs[i][col] = np.nan

    full = pd.concat(dfs, ignore_index=True)
    full["price_date"] = pd.to_datetime(full["price_date"], errors="coerce")

    print(f"\n📊 Dataset unificado: {full.shape}")
    print(f"\n🔍 Analizando TC por día...")
    full = corregir_tc(full)

    print(f"\n🔧 Recalculando features temporales...")
    # Limpiar features viejas
    old = [c for c in full.columns if any(c.startswith(p) for p in
           ["price_usd_lag","price_usd_ma","price_usd_std",
            "price_usd_pct","price_usd_zscore","price_vs_cat"])]
    full.drop(columns=old + ["_split"], inplace=True, errors="ignore")
    full["_split"] = np.nan

    # Re-asignar splits
    for s, df in zip(SPLITS, dfs):
        idx = dfs[SPLITS.index(s)].index
        full.loc[full.index.isin(idx), "_split"] = s

    # Reconstruir split column correctamente
    split_col = pd.concat([d[["_split"]] for d in dfs], ignore_index=True)
    full["_split"] = split_col["_split"].values

    full = recalcular_features(full)

    print(f"\n💾 Guardando splits limpios...")
    final_cols = [c for c in full.columns if c != "_split"]

    for s in SPLITS:
        df_s = full[full["_split"] == s][final_cols].reset_index(drop=True)
        df_s.to_csv(OUT_DIR / f"{s}_features.csv", index=False)
        neg = (df_s["price_usd"] < 0).sum()
        fechas = sorted(df_s["price_date"].dt.date.unique())
        print(f"\n  [{s}] shape={df_s.shape}  negativos={neg}  días={len(fechas)}")
        print(f"  [{s}] fechas: {fechas}")
        print(f"  [{s}] mean={df_s['price_usd'].mean():.2f}  "
              f"min={df_s['price_usd'].min():.2f}  "
              f"max={df_s['price_usd'].max():.2f}")

    print()
    print("=" * 60)
    print("  ✅ fix_tc_weekend.py completado")
    print("=" * 60)
