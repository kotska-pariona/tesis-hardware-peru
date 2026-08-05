"""
pe3_competitividad.py — OE3: Análisis de Competitividad de Precios
==================================================================
Responde: ¿Dónde conviene comprar cada componente de hardware en Perú?

Outputs:
  results/pe3_competitividad.json   ← métricas para tesis
  results/pe3_top_deals.csv         ← mejores oportunidades por SKU
  results/pe3_price_gaps.csv        ← brechas local vs importación
  figures/pe3_*.png                 ← 4 visualizaciones para tesis
"""

import json, warnings
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import lightgbm as lgb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import r2_score

warnings.filterwarnings("ignore")

# ══════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════
CFG = {
    "data_dir"   : Path("data/processed"),
    "model_path" : Path("models/pe2_lgbm/lgbm_pe2.txt"),
    "results_dir": Path("results"),
    "figures_dir": Path("figures"),
    "price_min"  : 0.50,
    "price_max"  : 15_000.0,
    "price_p_low": 0.001,
    "price_p_high": 0.999,
    "target"     : "price_usd",
    "group_ids"  : ["sku", "source"],

    # Clasificación de fuentes
    "local_sources" : ["coolbox_pe", "hiraoka_pe", "falabella_pe",
                       "falabella", "hiraoka"],
    "import_sources": ["aliexpress", "amazon_usa", "ebay_usa"],
}

DARK  = '#0f0f1a'
PANEL = '#1a1a2e'
GRID  = '#2a2a3e'
WHITE = '#e8e8f0'
CYAN  = '#00d4ff'
GREEN = '#00ff88'
AMBER = '#ffaa00'
RED   = '#ff4d6d'
PURPLE= '#c084fc'

SOURCE_COLORS = {
    "coolbox_pe"    : "#00d4ff",
    "hiraoka_pe"    : "#00ff88",
    "falabella_pe"  : "#ffaa00",
    "falabella"     : "#ffd166",
    "hiraoka"       : "#06d6a0",
    "aliexpress"    : "#ff4d6d",
    "amazon_usa"    : "#f77f00",
    "ebay_usa"      : "#c084fc",
    "exchangerate_api": "#888",
}

Path("figures").mkdir(parents=True, exist_ok=True)
Path("results").mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════════════════
# 1. CARGA
# ══════════════════════════════════════════════════════════════
def load_all():
    print("\n" + "="*60)
    print("  1. CARGANDO DATOS")
    print("="*60)
    dfs = []
    for split in ["train", "val", "test"]:
        fp = CFG["data_dir"] / f"{split}.csv"
        df = pd.read_csv(fp, low_memory=False)
        df["split"] = split
        dfs.append(df)
    df = pd.concat(dfs, ignore_index=True)
    df["price_date"] = pd.to_datetime(df["price_date"], errors="coerce")
    df = df[df["price_date"].notna() & df[CFG["target"]].notna()].copy()

    # Clip precios
    train_p = df.loc[df["split"]=="train", CFG["target"]]
    mask    = (train_p >= CFG["price_min"]) & (train_p <= CFG["price_max"])
    p_low   = train_p[mask].quantile(CFG["price_p_low"])
    p_high  = train_p[mask].quantile(CFG["price_p_high"])
    df[CFG["target"]] = df[CFG["target"]].clip(lower=p_low, upper=p_high)
    df = df[df[CFG["target"]] >= CFG["price_min"]].copy()

    for col in CFG["group_ids"]:
        if col in df.columns:
            df[col] = df[col].fillna("unknown").astype(str)
    if "category" in df.columns:
        df["category"] = df["category"].fillna("unknown").astype(str)

    df["source_type"] = df["source"].apply(
        lambda s: "local" if s in CFG["local_sources"]
                  else ("importacion" if s in CFG["import_sources"]
                        else "otro"))

    print(f"  Total registros : {len(df):,}")
    print(f"  SKUs únicos     : {df['sku'].nunique():,}")
    print(f"  Fuentes         : {sorted(df['source'].unique())}")
    print(f"  Rango fechas    : {df['price_date'].min().date()} → "
          f"{df['price_date'].max().date()}")
    return df, p_low, p_high

# ══════════════════════════════════════════════════════════════
# 2. PREDICCIÓN CON MODELO OE2
# ══════════════════════════════════════════════════════════════
def add_predictions(df, p_low, p_high):
    print("\n" + "="*60)
    print("  2. AÑADIENDO PREDICCIONES (modelo OE2)")
    print("="*60)
    if not CFG["model_path"].exists():
        print("  ⚠ Modelo no encontrado — usando lag_1 como predicción")
        df = df.sort_values(CFG["group_ids"] + ["price_date"])
        df["price_pred"] = (df.groupby(CFG["group_ids"])[CFG["target"]]
                              .shift(1).fillna(df[CFG["target"]]))
        return df

    model = lgb.Booster(model_file=str(CFG["model_path"]))

    df = df.sort_values(CFG["group_ids"] + ["price_date"]).copy()
    grp = df.groupby(CFG["group_ids"])[CFG["target"]]

    df["lag_1"] = grp.shift(1)
    df["lag_2"] = grp.shift(2)
    df["lag_3"] = grp.shift(3)
    df["ma_2"]  = grp.transform(lambda x: x.shift(1).rolling(2,min_periods=1).mean())
    df["ma_3"]  = grp.transform(lambda x: x.shift(1).rolling(3,min_periods=1).mean())
    df["ma_5"]  = grp.transform(lambda x: x.shift(1).rolling(5,min_periods=1).mean())
    df["std_3"] = grp.transform(lambda x: x.shift(1).rolling(3,min_periods=2).std()).fillna(0)
    df["std_5"] = grp.transform(lambda x: x.shift(1).rolling(5,min_periods=2).std()).fillna(0)
    df["pct_change_1"] = (df["lag_1"]/df["lag_2"]-1).fillna(0).clip(-1,1)
    df["pct_change_2"] = (df["lag_2"]/df["lag_3"]-1).fillna(0).clip(-1,1)
    df["day_of_week"]  = df["price_date"].dt.dayofweek
    df["day_of_month"] = df["price_date"].dt.day
    df["month"]        = df["price_date"].dt.month
    df["is_weekend"]   = (df["day_of_week"] >= 5).astype(int)

    sku_stats = df.groupby(CFG["group_ids"])[CFG["target"]].agg(
        sku_mean="mean", sku_std="std", sku_min="min", sku_max="max"
    ).reset_index()
    sku_stats["sku_std"] = sku_stats["sku_std"].fillna(0)
    df = df.merge(sku_stats, on=CFG["group_ids"], how="left")

    for col in ["lag_1","lag_2","lag_3","ma_2","ma_3","ma_5"]:
        df[col] = df[col].fillna(df[CFG["target"]])

    cat_cols = ["sku","source","category"] if "category" in df.columns else ["sku","source"]
    for col in cat_cols:
        le = LabelEncoder()
        df[f"{col}_enc"] = le.fit_transform(df[col].astype(str))

    feat_cols = [
        "lag_1","lag_2","lag_3","ma_2","ma_3","ma_5",
        "std_3","std_5","pct_change_1","pct_change_2",
        "sku_mean","sku_std","sku_min","sku_max",
        "day_of_week","day_of_month","month","is_weekend",
    ] + [f"{c}_enc" for c in cat_cols if f"{c}_enc" in df.columns]

    preds = model.predict(df[feat_cols].values,
                          num_iteration=model.best_iteration)
    df["price_pred"] = np.clip(preds, p_low, p_high)
    print(f"  Predicciones generadas: {len(df):,}")
    return df

# ══════════════════════════════════════════════════════════════
# 3. ANÁLISIS DE COMPETITIVIDAD
# ══════════════════════════════════════════════════════════════
def analyze_competitiveness(df):
    print("\n" + "="*60)
    print("  3. ANÁLISIS DE COMPETITIVIDAD")
    print("="*60)

    # Último precio por SKU+fuente
    latest = (df.sort_values("price_date")
                .groupby(CFG["group_ids"])
                .last()
                .reset_index()
                [[*CFG["group_ids"], "price_date", CFG["target"],
                  "price_pred", "source_type"]
                 + (["category"] if "category" in df.columns else [])])
    latest.rename(columns={CFG["target"]: "price_last"}, inplace=True)

    # ── 3A. Precio mínimo por SKU ─────────────────────────────
    sku_min = (latest.groupby("sku")
                     .apply(lambda g: g.loc[g["price_last"].idxmin()])
                     .reset_index(drop=True)
                     [["sku","source","price_last","source_type"]]
                     .rename(columns={"source":"best_source",
                                      "price_last":"best_price",
                                      "source_type":"best_type"}))

    # Precio máximo por SKU (para calcular ahorro)
    sku_max_price = (latest.groupby("sku")["price_last"]
                           .max().reset_index()
                           .rename(columns={"price_last":"max_price"}))
    sku_min = sku_min.merge(sku_max_price, on="sku")
    sku_min["saving_usd"] = sku_min["max_price"] - sku_min["best_price"]
    sku_min["saving_pct"] = (sku_min["saving_usd"] /
                              sku_min["max_price"] * 100).clip(0, 100)

    print(f"\n  SKUs con precio mínimo en fuente local    : "
          f"{(sku_min['best_type']=='local').sum():,} "
          f"({(sku_min['best_type']=='local').mean()*100:.1f}%)")
    print(f"  SKUs con precio mínimo en importación     : "
          f"{(sku_min['best_type']=='importacion').sum():,} "
          f"({(sku_min['best_type']=='importacion').mean()*100:.1f}%)")

    # ── 3B. Ganador por fuente ────────────────────────────────
    wins_by_source = sku_min["best_source"].value_counts()
    print(f"\n  Tienda más competitiva (más SKUs al menor precio):")
    for src, cnt in wins_by_source.head(8).items():
        pct = cnt / len(sku_min) * 100
        bar = "█" * int(pct / 2)
        print(f"    {src:<20} {bar} {cnt:,} SKUs ({pct:.1f}%)")

    # ── 3C. Brecha local vs importación ──────────────────────
    local_prices  = latest[latest["source_type"]=="local"]
    import_prices = latest[latest["source_type"]=="importacion"]

    skus_both = set(local_prices["sku"]) & set(import_prices["sku"])
    print(f"\n  SKUs con precio en AMBAS fuentes: {len(skus_both):,}")

    if len(skus_both) > 0:
        lp = (local_prices[local_prices["sku"].isin(skus_both)]
              .groupby("sku")["price_last"].min().reset_index()
              .rename(columns={"price_last":"price_local"}))
        ip = (import_prices[import_prices["sku"].isin(skus_both)]
              .groupby("sku")["price_last"].min().reset_index()
              .rename(columns={"price_last":"price_import"}))
        gap_df = lp.merge(ip, on="sku")
        gap_df["gap_usd"] = gap_df["price_local"] - gap_df["price_import"]
        gap_df["gap_pct"] = (gap_df["gap_usd"] /
                              gap_df["price_import"] * 100)

        print(f"\n  Brecha precio local vs importación:")
        print(f"    Mediana gap : {gap_df['gap_pct'].median():+.1f}%")
        print(f"    Media gap   : {gap_df['gap_pct'].mean():+.1f}%")
        print(f"    SKUs local < import: "
              f"{(gap_df['gap_pct']<0).sum():,} "
              f"({(gap_df['gap_pct']<0).mean()*100:.1f}%)")
        print(f"    SKUs local > import: "
              f"{(gap_df['gap_pct']>0).sum():,} "
              f"({(gap_df['gap_pct']>0).mean()*100:.1f}%)")
    else:
        gap_df = pd.DataFrame()
        print("  ⚠ Sin SKUs en común entre fuentes locales e importación")

    # ── 3D. Competitividad por categoría ─────────────────────
    cat_stats = pd.DataFrame()
    if "category" in latest.columns:
        cat_stats = (latest.groupby(["category","source_type"])["price_last"]
                           .agg(["mean","median","count"])
                           .reset_index()
                           .rename(columns={"mean":"avg_price",
                                            "median":"med_price",
                                            "count":"n_skus"}))
        top_cats = (latest.groupby("category")["price_last"]
                          .count().nlargest(10).index)
        cat_stats = cat_stats[cat_stats["category"].isin(top_cats)]
        print(f"\n  Top 10 categorías analizadas:")
        for cat in top_cats:
            n = latest[latest["category"]==cat]["sku"].nunique()
            print(f"    {cat:<35} {n:>5} SKUs")

    # ── 3E. Top deals (mayor ahorro) ─────────────────────────
    top_deals = (sku_min[sku_min["saving_pct"] > 5]
                 .sort_values("saving_pct", ascending=False)
                 .head(50))

    return latest, sku_min, gap_df, cat_stats, wins_by_source, top_deals

# ══════════════════════════════════════════════════════════════
# 4. VISUALIZACIONES
# ══════════════════════════════════════════════════════════════
def plot_all(df, latest, sku_min, gap_df, cat_stats,
             wins_by_source, p_low, p_high):
    print("\n" + "="*60)
    print("  4. GENERANDO VISUALIZACIONES")
    print("="*60)

    # ── FIG 1: Distribución de precios por fuente ─────────────
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.patch.set_facecolor(DARK)
    fig.suptitle("OE3 — Distribución de Precios por Fuente",
                 color=WHITE, fontsize=14, fontweight="bold", y=1.01)

    # Boxplot por fuente
    ax = axes[0]
    ax.set_facecolor(PANEL)
    sources_ordered = (latest.groupby("source")["price_last"]
                              .median().sort_values().index.tolist())
    data_box = [latest[latest["source"]==s]["price_last"].dropna().values
                for s in sources_ordered]
    bp = ax.boxplot(data_box, vert=False, patch_artist=True,
                    medianprops=dict(color=WHITE, linewidth=2),
                    whiskerprops=dict(color=GRID),
                    capprops=dict(color=GRID),
                    flierprops=dict(marker=".", color=GRID,
                                    markersize=2, alpha=0.3))
    for patch, src in zip(bp["boxes"], sources_ordered):
        patch.set_facecolor(SOURCE_COLORS.get(src, CYAN))
        patch.set_alpha(0.75)
    ax.set_yticks(range(1, len(sources_ordered)+1))
    ax.set_yticklabels(sources_ordered, color=WHITE, fontsize=9)
    ax.set_xlabel("Precio (USD)", color=WHITE)
    ax.set_title("Distribución de Precios por Tienda", color=WHITE,
                 fontsize=11)
    ax.tick_params(colors=WHITE)
    ax.spines[:].set_color(GRID)
    ax.set_xscale("log")
    ax.grid(axis="x", alpha=0.2, color=WHITE)
    ax.set_xlim(left=1)

    # Wins por fuente
    ax2 = axes[1]
    ax2.set_facecolor(PANEL)
    top_src = wins_by_source.head(8)
    colors_w = [SOURCE_COLORS.get(s, CYAN) for s in top_src.index]
    bars = ax2.barh(top_src.index[::-1], top_src.values[::-1],
                    color=colors_w[::-1], alpha=0.85)
    ax2.set_xlabel("N° SKUs al precio más bajo", color=WHITE)
    ax2.set_title("Tienda más Competitiva\n(SKUs con precio mínimo)",
                  color=WHITE, fontsize=11)
    ax2.tick_params(colors=WHITE)
    ax2.spines[:].set_color(GRID)
    ax2.grid(axis="x", alpha=0.2, color=WHITE)
    total = wins_by_source.sum()
    for bar, val in zip(bars, top_src.values[::-1]):
        ax2.text(val + total*0.005, bar.get_y()+bar.get_height()/2,
                 f"{val:,} ({val/total*100:.1f}%)",
                 va="center", color=WHITE, fontsize=9)

    plt.tight_layout()
    plt.savefig("figures/pe3_fig1_distribucion.png",
                dpi=150, bbox_inches="tight",
                facecolor=DARK)
    plt.close()
    print("  ✓ figures/pe3_fig1_distribucion.png")

    # ── FIG 2: Brecha local vs importación ───────────────────
    if len(gap_df) > 0:
        fig, axes = plt.subplots(1, 2, figsize=(16, 6))
        fig.patch.set_facecolor(DARK)
        fig.suptitle("OE3 — Brecha de Precios: Local vs Importación",
                     color=WHITE, fontsize=14, fontweight="bold")

        ax = axes[0]
        ax.set_facecolor(PANEL)
        gap_pct = gap_df["gap_pct"].clip(-100, 200)
        n_bins  = min(60, max(20, len(gap_pct)//20))
        neg = gap_pct[gap_pct < 0]
        pos = gap_pct[gap_pct >= 0]
        if len(neg) > 0:
            ax.hist(neg, bins=n_bins//2, color=GREEN, alpha=0.75,
                    label=f"Local más barato ({len(neg):,} SKUs)")
        if len(pos) > 0:
            ax.hist(pos, bins=n_bins//2, color=RED, alpha=0.75,
                    label=f"Local más caro ({len(pos):,} SKUs)")
        ax.axvline(0, color=WHITE, linewidth=1.5, linestyle="--")
        med = gap_pct.median()
        ax.axvline(med, color=AMBER, linewidth=2, linestyle=":",
                   label=f"Mediana: {med:+.1f}%")
        ax.set_xlabel("Diferencia % (Local − Importación)", color=WHITE)
        ax.set_ylabel("N° SKUs", color=WHITE)
        ax.set_title("Distribución de Brecha de Precios", color=WHITE)
        ax.tick_params(colors=WHITE)
        ax.spines[:].set_color(GRID)
        ax.grid(alpha=0.2, color=WHITE)
        ax.legend(facecolor=PANEL, labelcolor=WHITE,
                  edgecolor=GRID, fontsize=9)

        ax2 = axes[1]
        ax2.set_facecolor(PANEL)
        ax2.scatter(gap_df["price_import"], gap_df["price_local"],
                    alpha=0.15, s=8, color=CYAN)
        lim = max(gap_df["price_import"].max(),
                  gap_df["price_local"].max()) * 1.05
        ax2.plot([0, lim], [0, lim], color=WHITE,
                 linewidth=1.5, linestyle="--", label="Paridad")
        ax2.set_xlabel("Precio Importación (USD)", color=WHITE)
        ax2.set_ylabel("Precio Local (USD)", color=WHITE)
        ax2.set_title("Precio Local vs Importación por SKU", color=WHITE)
        ax2.tick_params(colors=WHITE)
        ax2.spines[:].set_color(GRID)
        ax2.grid(alpha=0.15, color=WHITE)
        ax2.legend(facecolor=PANEL, labelcolor=WHITE,
                   edgecolor=GRID, fontsize=9)
        ax2.set_xscale("log")
        ax2.set_yscale("log")

        plt.tight_layout()
        plt.savefig("figures/pe3_fig2_brecha.png",
                    dpi=150, bbox_inches="tight",
                    facecolor=DARK)
        plt.close()
        print("  ✓ figures/pe3_fig2_brecha.png")

    # ── FIG 3: Competitividad por categoría ──────────────────
    if len(cat_stats) > 0:
        fig, ax = plt.subplots(figsize=(14, 7))
        fig.patch.set_facecolor(DARK)
        ax.set_facecolor(PANEL)

        pivot = cat_stats.pivot_table(
            index="category", columns="source_type",
            values="med_price", aggfunc="mean"
        ).fillna(0)
        pivot = pivot.reindex(
            pivot.get("local", pivot.iloc[:,0]).sort_values(
                ascending=False).index
        )

        x    = np.arange(len(pivot))
        w    = 0.35
        cols = {"local": GREEN, "importacion": RED, "otro": AMBER}
        for i, (stype, color) in enumerate(cols.items()):
            if stype in pivot.columns:
                vals = pivot[stype].values
                ax.bar(x + (i-1)*w, vals, w, label=stype.capitalize(),
                       color=color, alpha=0.8)

        ax.set_xticks(x)
        ax.set_xticklabels(pivot.index, rotation=35, ha="right",
                           color=WHITE, fontsize=9)
        ax.set_ylabel("Precio Mediano (USD)", color=WHITE)
        ax.set_title("Precio Mediano por Categoría y Tipo de Fuente",
                     color=WHITE, fontsize=13, fontweight="bold")
        ax.tick_params(colors=WHITE)
        ax.spines[:].set_color(GRID)
        ax.grid(axis="y", alpha=0.2, color=WHITE)
        ax.legend(facecolor=PANEL, labelcolor=WHITE,
                  edgecolor=GRID, fontsize=10)
        ax.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))

        plt.tight_layout()
        plt.savefig("figures/pe3_fig3_categorias.png",
                    dpi=150, bbox_inches="tight",
                    facecolor=DARK)
        plt.close()
        print("  ✓ figures/pe3_fig3_categorias.png")

    # ── FIG 4: Precio actual vs predicho ─────────────────────
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.patch.set_facecolor(DARK)
    fig.suptitle("OE3 — Precio Actual vs Predicho por Fuente",
                 color=WHITE, fontsize=14, fontweight="bold")

    ax = axes[0]
    ax.set_facecolor(PANEL)
    sample = latest.dropna(subset=["price_pred"]).sample(
        min(3000, len(latest)), random_state=42)
    for stype, color in [("local", GREEN), ("importacion", RED),
                          ("otro", AMBER)]:
        m = sample["source_type"] == stype
        if m.sum() > 0:
            ax.scatter(sample[m]["price_last"],
                       sample[m]["price_pred"],
                       alpha=0.25, s=6, color=color,
                       label=stype.capitalize())
    lim = max(sample["price_last"].max(),
              sample["price_pred"].max()) * 1.05
    ax.plot([0, lim], [0, lim], color=WHITE,
            linewidth=1.5, linestyle="--", label="Perfecto")
    ax.set_xlabel("Precio Actual (USD)", color=WHITE)
    ax.set_ylabel("Precio Predicho (USD)", color=WHITE)
    ax.set_title("Actual vs Predicho (muestra)", color=WHITE)
    ax.tick_params(colors=WHITE)
    ax.spines[:].set_color(GRID)
    ax.grid(alpha=0.15, color=WHITE)
    ax.legend(facecolor=PANEL, labelcolor=WHITE,
              edgecolor=GRID, fontsize=9)
    ax.set_xscale("log")
    ax.set_yscale("log")

    ax2 = axes[1]
    ax2.set_facecolor(PANEL)
    latest2 = latest.dropna(subset=["price_pred"]).copy()
    latest2["error_pct"] = ((latest2["price_pred"] -
                              latest2["price_last"]) /
                             latest2["price_last"] * 100).clip(-20, 20)
    for stype, color in [("local", GREEN), ("importacion", RED)]:
        m = latest2["source_type"] == stype
        if m.sum() > 0:
            ax2.hist(latest2[m]["error_pct"], bins=60,
                     color=color, alpha=0.6,
                     label=f"{stype.capitalize()} "
                           f"(μ={latest2[m]['error_pct'].mean():.2f}%)")
    ax2.axvline(0, color=WHITE, linewidth=1.5, linestyle="--")
    ax2.set_xlabel("Error % (Predicho − Actual)", color=WHITE)
    ax2.set_ylabel("N° registros", color=WHITE)
    ax2.set_title("Distribución del Error de Predicción", color=WHITE)
    ax2.tick_params(colors=WHITE)
    ax2.spines[:].set_color(GRID)
    ax2.grid(alpha=0.2, color=WHITE)
    ax2.legend(facecolor=PANEL, labelcolor=WHITE,
               edgecolor=GRID, fontsize=9)

    plt.tight_layout()
    plt.savefig("figures/pe3_fig4_prediccion.png",
                dpi=150, bbox_inches="tight",
                facecolor=DARK)
    plt.close()
    print("  ✓ figures/pe3_fig4_prediccion.png")

# ══════════════════════════════════════════════════════════════
# 5. GUARDAR RESULTADOS
# ══════════════════════════════════════════════════════════════
def save_results(sku_min, gap_df, cat_stats, wins_by_source, latest):
    print("\n" + "="*60)
    print("  5. GUARDANDO RESULTADOS")
    print("="*60)

    # Top deals CSV
    top_deals = (sku_min[sku_min["saving_pct"] > 1]
                 .sort_values("saving_pct", ascending=False)
                 .head(100))
    top_deals.to_csv("results/pe3_top_deals.csv", index=False)
    print(f"  ✓ results/pe3_top_deals.csv ({len(top_deals)} deals)")

    # Price gaps CSV
    if len(gap_df) > 0:
        gap_df.to_csv("results/pe3_price_gaps.csv", index=False)
        print(f"  ✓ results/pe3_price_gaps.csv ({len(gap_df):,} SKUs)")

    # Métricas JSON
    local_wins  = int((sku_min["best_type"]=="local").sum())
    import_wins = int((sku_min["best_type"]=="importacion").sum())
    total_skus  = len(sku_min)

    metrics = {
        "oe"       : "OE3",
        "timestamp": datetime.now().isoformat(),
        "dataset"  : {
            "total_registros": int(len(latest)),
            "skus_unicos"    : int(latest["sku"].nunique()),
            "fuentes"        : sorted(latest["source"].unique().tolist()),
            "fecha_min"      : str(latest["price_date"].min().date()),
            "fecha_max"      : str(latest["price_date"].max().date()),
        },
        "competitividad": {
            "total_skus_analizados": total_skus,
            "skus_mejor_precio_local"      : local_wins,
            "skus_mejor_precio_importacion": import_wins,
            "pct_local_gana"   : round(local_wins/total_skus*100, 2),
            "pct_import_gana"  : round(import_wins/total_skus*100, 2),
            "tienda_mas_competitiva": wins_by_source.index[0],
            "wins_por_fuente": wins_by_source.head(8).to_dict(),
        },
        "brecha_local_vs_importacion": {} if len(gap_df)==0 else {
            "skus_comparados"  : int(len(gap_df)),
            "gap_mediana_pct"  : round(float(gap_df["gap_pct"].median()), 2),
            "gap_media_pct"    : round(float(gap_df["gap_pct"].mean()), 2),
            "skus_local_mas_barato": int((gap_df["gap_pct"]<0).sum()),
            "skus_import_mas_barato": int((gap_df["gap_pct"]>0).sum()),
            "pct_local_mas_barato": round(
                (gap_df["gap_pct"]<0).mean()*100, 2),
        },
        "figuras": [
            "figures/pe3_fig1_distribucion.png",
            "figures/pe3_fig2_brecha.png",
            "figures/pe3_fig3_categorias.png",
            "figures/pe3_fig4_prediccion.png",
        ],
    }

    with open("results/pe3_competitividad.json", "w",
              encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    print("  ✓ results/pe3_competitividad.json")
    return metrics

# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  OE3: Análisis de Competitividad de Precios")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    df, p_low, p_high          = load_all()
    df                         = add_predictions(df, p_low, p_high)
    latest, sku_min, gap_df, \
    cat_stats, wins_by_source, \
    top_deals                  = analyze_competitiveness(df)
    plot_all(df, latest, sku_min, gap_df, cat_stats,
             wins_by_source, p_low, p_high)
    metrics = save_results(sku_min, gap_df, cat_stats,
                           wins_by_source, latest)

    print("\n" + "=" * 60)
    print("  OE3 COMPLETADO")
    print("=" * 60)
    print(f"\n  SKUs analizados       : {metrics['competitividad']['total_skus_analizados']:,}")
    print(f"  Tienda más competitiva: {metrics['competitividad']['tienda_mas_competitiva']}")
    print(f"  Local gana en         : {metrics['competitividad']['pct_local_gana']:.1f}% de SKUs")
    print(f"  Importación gana en   : {metrics['competitividad']['pct_import_gana']:.1f}% de SKUs")
    if metrics["brecha_local_vs_importacion"]:
        gap = metrics["brecha_local_vs_importacion"]
        print(f"  Brecha mediana        : {gap['gap_mediana_pct']:+.1f}%")
    print(f"\n  Outputs:")
    print(f"    results/pe3_competitividad.json")
    print(f"    results/pe3_top_deals.csv")
    print(f"    results/pe3_price_gaps.csv")
    print(f"    figures/pe3_fig1_distribucion.png")
    print(f"    figures/pe3_fig2_brecha.png")
    print(f"    figures/pe3_fig3_categorias.png")
    print(f"    figures/pe3_fig4_prediccion.png")