"""
pe3b_matching.py — OE3-B v3
============================
CAMBIOS v3:
  - Filtro de ratio de precio: price_local/price_import ∈ [0.5, 4.0]
    Elimina falsos matches donde un componente de $44 se empareja
    con una laptop de $7,000 (mismo token "Core i5" en el título).
  - Filtro precio mínimo importación: price_import >= $20
    Descarta accesorios/cables mal clasificados como hardware PC.
  - Documentado en JSON como criterio de validación de matches.
"""

import re, json, warnings
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from rapidfuzz import fuzz, process

warnings.filterwarnings("ignore")

CFG = {
    "data_dir"    : Path("data/processed"),
    "results_dir" : Path("results"),
    "figures_dir" : Path("figures"),
    "target"      : "price_usd",
    "price_min"   : 0.50,
    "price_max"   : 15_000.0,
    "price_p_low" : 0.001,
    "price_p_high": 0.999,
    "local_sources" : ["coolbox_pe","hiraoka_pe","falabella_pe",
                       "falabella","hiraoka"],
    "import_sources": ["aliexpress","amazon_usa","ebay_usa"],
    "match_threshold"  : 85,
    "max_candidates"   : 5,
    # ── NUEVO v3: filtros de validación de precio ──────────────
    "price_ratio_min"  : 0.5,   # local no puede ser < 50% del import
    "price_ratio_max"  : 4.0,   # local no puede ser > 4× el import
    "price_import_min" : 20.0,  # descartar items de importación < $20
}

CATEGORIAS_HARDWARE_PC = {
    "cpu","procesadores","gpu","tarjetas_video","ram","memorias_ram",
    "ssd","discos_ssd","motherboard","psu","monitores","laptops",
    "computadoras","cooler","case",
}
CATEGORIAS_EXCLUIDAS = {
    "celulares","smartphones","smartwatch","tablets","videojuegos",
    "televisores","auriculares","parlantes","teclados","mouse",
    "impresoras","camaras",
}

DARK  = '#0f0f1a'; PANEL = '#1a1a2e'; GRID = '#2a2a3e'
WHITE = '#e8e8f0'; CYAN  = '#00d4ff'; GREEN = '#00ff88'
AMBER = '#ffaa00'; RED   = '#ff4d6d'; PURPLE= '#c084fc'

Path("figures").mkdir(parents=True, exist_ok=True)
Path("results").mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════════════════
# 1. CARGA
# ══════════════════════════════════════════════════════════════
def load_latest():
    print("\n" + "="*60)
    print("  1. CARGANDO DATOS")
    print("="*60)
    dfs = []
    for split in ["train","val","test"]:
        df = pd.read_csv(CFG["data_dir"]/f"{split}.csv", low_memory=False)
        dfs.append(df)
    df = pd.concat(dfs, ignore_index=True)
    df["price_date"] = pd.to_datetime(df["price_date"], errors="coerce")
    df = df[df["price_date"].notna() & df[CFG["target"]].notna()].copy()

    train_p = df[CFG["target"]]
    mask    = (train_p >= CFG["price_min"]) & (train_p <= CFG["price_max"])
    p_low   = train_p[mask].quantile(CFG["price_p_low"])
    p_high  = train_p[mask].quantile(CFG["price_p_high"])
    df[CFG["target"]] = df[CFG["target"]].clip(p_low, p_high)
    df = df[df[CFG["target"]] >= CFG["price_min"]].copy()

    for col in ["sku","source","title","category"]:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()

    df["source_type"] = df["source"].apply(
        lambda s: "local" if s in CFG["local_sources"]
                  else ("importacion" if s in CFG["import_sources"]
                        else "otro"))

    latest = (df.sort_values("price_date")
                .groupby(["sku","source"])
                .last()
                .reset_index())
    latest.rename(columns={CFG["target"]:"price_last"}, inplace=True)

    print(f"  Registros totales : {len(df):,}")
    print(f"  SKU+fuente únicos : {len(latest):,}")
    return latest, p_low, p_high

# ══════════════════════════════════════════════════════════════
# 2. EXTRACCIÓN DE MODELO
# ══════════════════════════════════════════════════════════════
HW_PATTERNS = [
    (r'\bRTX\s*(?:40|30|20)\d{2}\s*(?:Ti|Super|XT)?\b',            "GPU"),
    (r'\bGTX\s*(?:16|10)\d{2}\s*(?:Ti|Super)?\b',                  "GPU"),
    (r'\bRX\s*(?:7[0-9]{3}|6[0-9]{3}|5[0-9]{3})\s*(?:XT|GRE)?\b', "GPU"),
    (r'\bArc\s*A\d{3}\b',                                           "GPU"),
    (r'\bCore\s*(?:Ultra\s*)?\bi[3579]-\d{4,5}[A-Z]*\b',           "CPU"),
    (r'\bi[3579]-\d{4,5}[A-Z]*\b',                                  "CPU"),
    (r'\bCore\s*Ultra\s*[579]\s*\d{3}[A-Z]*\b',                    "CPU"),
    (r'\bRyzen\s*[3579]\s*\d{4}[A-Z]*\b',                          "CPU"),
    (r'\bThreadripper\s*(?:PRO\s*)?\d{4}[A-Z]*\b',                 "CPU"),
    (r'\b\d{1,3}\s*GB\s*DDR[45][X]?\s*(?:\d{4,5}\s*MHz)?\b',      "RAM"),
    (r'\b\d{1,3}\s*GB\s*(?:SO-DIMM|DIMM)\b',                       "RAM"),
    (r'\b\d+\s*(?:GB|TB)\s*(?:NVMe|M\.2|SATA|SSD|HDD)\b',         "SSD"),
    (r'\b(?:NVMe|M\.2)\s*\d+\s*(?:GB|TB)\b',                       "SSD"),
    (r'\b\d{2,3}["\']\s*(?:\d{3,4}\s*Hz)?\b',                     "Monitor"),
    (r'\b\d{2,3}\s*Hz\b',                                           "Monitor"),
    (r'\b\d{3,4}\s*W\s*(?:80\+|Gold|Platinum|Bronze)?\b',         "PSU"),
    (r'\b[BZH]\d{3}[A-Z]?\b',                                      "MB"),
    (r'\b[A-Z]{2,6}[-_]?\d{3,6}[A-Z0-9]*\b',                      "GEN"),
]

def extract_model_key(title: str) -> str:
    if not title or title == "nan":
        return ""
    t = title.upper()
    t = re.sub(r'[_/\\|]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    tokens = []
    for pattern, _ in HW_PATTERNS:
        for m in re.findall(pattern, t, re.IGNORECASE):
            cleaned = re.sub(r'\s+', ' ', m.strip()).upper()
            if cleaned and cleaned not in tokens:
                tokens.append(cleaned)
    if tokens:
        return " | ".join(tokens)
    words = [w for w in t.split() if len(w) > 2 and not w.isdigit()
             and w not in {"THE","AND","FOR","WITH","FROM","NUEVO",
                            "PARA","CON"}]
    return " ".join(words[:5])

def add_model_key(df):
    print("\n  Extrayendo modelo del título...")
    if "title" not in df.columns or df["title"].str.strip().eq("").all():
        df["model_key"] = df["sku"].str.upper().str[:50]
    else:
        df["model_key"] = df["title"].apply(extract_model_key)
        mask_empty = df["model_key"].str.strip() == ""
        df.loc[mask_empty, "model_key"] = (
            df.loc[mask_empty, "sku"].str.upper().str[:50])
    return df

# ══════════════════════════════════════════════════════════════
# 3. FUZZY MATCHING — v3: + filtro ratio de precio
# ══════════════════════════════════════════════════════════════
def fuzzy_match(latest):
    print("\n" + "="*60)
    print("  3. FUZZY MATCHING LOCAL vs IMPORTACIÓN (v3)")
    print(f"     Score ≥ {CFG['match_threshold']}")
    print(f"     Ratio precio: [{CFG['price_ratio_min']}, {CFG['price_ratio_max']}]")
    print(f"     Precio import mín: ${CFG['price_import_min']}")
    print("="*60)

    def is_hardware_pc(cat):
        c = str(cat).lower().strip()
        if c in CATEGORIAS_HARDWARE_PC: return True
        if c in CATEGORIAS_EXCLUIDAS:   return False
        return True

    latest_hw = latest[latest["category"].apply(is_hardware_pc)].copy()
    local_df  = latest_hw[latest_hw["source_type"]=="local"].copy()
    import_df = latest_hw[latest_hw["source_type"]=="importacion"].copy()
    local_df  = local_df[local_df["model_key"].str.strip() != ""]
    import_df = import_df[import_df["model_key"].str.strip() != ""]

    print(f"\n  SKUs locales    : {len(local_df):,}")
    print(f"  SKUs importación: {len(import_df):,}")

    if len(local_df) == 0 or len(import_df) == 0:
        return pd.DataFrame()

    import_keys  = import_df["model_key"].tolist()
    import_index = import_df.reset_index(drop=True)
    matches      = []
    total        = len(local_df)
    local_reset  = local_df.reset_index(drop=True)

    print(f"\n  Procesando {total:,} SKUs locales...")
    for start in range(0, total, 500):
        end   = min(start + 500, total)
        batch = local_reset.iloc[start:end]
        print(f"    {end:>6}/{total} ({end/total*100:.0f}%)", end="\r")
        for _, row_l in batch.iterrows():
            key_l = row_l["model_key"]
            if not key_l or len(key_l) < 4:
                continue
            results = process.extract(
                key_l, import_keys,
                scorer=fuzz.token_sort_ratio,
                limit=CFG["max_candidates"],
                score_cutoff=CFG["match_threshold"],
            )
            for match_key, score, idx in results:
                row_i = import_index.iloc[idx]
                matches.append({
                    "sku_local"       : row_l["sku"],
                    "source_local"    : row_l["source"],
                    "title_local"     : row_l.get("title",""),
                    "model_key_local" : key_l,
                    "price_local"     : row_l["price_last"],
                    "category_local"  : row_l.get("category",""),
                    "sku_import"      : row_i["sku"],
                    "source_import"   : row_i["source"],
                    "title_import"    : row_i.get("title",""),
                    "model_key_import": match_key,
                    "price_import"    : row_i["price_last"],
                    "category_import" : row_i.get("category",""),
                    "match_score"     : score,
                })

    print(f"\n  Pares brutos (score≥{CFG['match_threshold']}): {len(matches):,}")
    if not matches:
        return pd.DataFrame()

    match_df = pd.DataFrame(matches)

    # ── FILTRO v3: precio mínimo de importación ───────────────
    n0 = len(match_df)
    match_df = match_df[
        match_df["price_import"] >= CFG["price_import_min"]
    ].copy()
    print(f"  Tras filtro import≥${CFG['price_import_min']:.0f}: "
          f"{len(match_df):,} (−{n0-len(match_df):,} descartados)")

    # ── FILTRO v3: ratio de precio (anti falsos matches) ──────
    n1 = len(match_df)
    match_df["price_ratio"] = (
        match_df["price_local"] / match_df["price_import"]
    )
    match_df = match_df[
        (match_df["price_ratio"] >= CFG["price_ratio_min"]) &
        (match_df["price_ratio"] <= CFG["price_ratio_max"])
    ].copy()
    print(f"  Tras filtro ratio∈[{CFG['price_ratio_min']},{CFG['price_ratio_max']}]: "
          f"{len(match_df):,} (−{n1-len(match_df):,} falsos matches)")

    # ── Brecha ────────────────────────────────────────────────
    match_df["gap_usd"] = (
        match_df["price_local"] - match_df["price_import"]
    )
    match_df["gap_pct"] = (
        match_df["gap_usd"] / match_df["price_import"] * 100
    ).clip(-200, 500)

    # ── Categoría unificada ───────────────────────────────────
    match_df["category"] = (
        match_df["category_local"].replace("", np.nan)
        .fillna(match_df["category_import"])
        .fillna("unknown")
    )

    # ── Dedup ─────────────────────────────────────────────────
    match_df = (match_df
                .sort_values("match_score", ascending=False)
                .drop_duplicates(subset=["sku_local","sku_import"])
                .reset_index(drop=True))

    print(f"  Pares únicos finales: {len(match_df):,}")

    # ── Resumen ───────────────────────────────────────────────
    print(f"\n  Brecha real (pares validados):")
    print(f"    Mediana gap : {match_df['gap_pct'].median():+.1f}%")
    print(f"    Media gap   : {match_df['gap_pct'].mean():+.1f}%")
    n_lc = (match_df["gap_pct"] < 0).sum()
    n_ic = (match_df["gap_pct"] > 0).sum()
    print(f"    Local más barato  : {n_lc:,} ({n_lc/len(match_df)*100:.1f}%)")
    print(f"    Import más barato : {n_ic:,} ({n_ic/len(match_df)*100:.1f}%)")

    print(f"\n  Brecha por categoría (pares validados):")
    cat_gap = (match_df[match_df["category"]!="unknown"]
               .groupby("category")["gap_pct"]
               .agg(median="median", mean="mean", count="count")
               .sort_values("count", ascending=False)
               .head(15))
    print(f"  {'Categoría':<20} {'Mediana':>8} {'Media':>8} {'N':>6}")
    print(f"  {'─'*44}")
    for cat, row in cat_gap.iterrows():
        print(f"  {cat:<20} {row['median']:>+7.1f}% "
              f"{row['mean']:>+7.1f}% {row['count']:>6,.0f}")

    # ── Muestra de matches validados ──────────────────────────
    print(f"\n  Muestra de matches VALIDADOS (ratio OK):")
    sample = match_df.nlargest(10, "gap_pct")[
        ["title_local","title_import","price_local",
         "price_import","price_ratio","gap_pct","match_score"]]
    print(f"  {'Local':<35} {'Import':<35} "
          f"{'PL':>6} {'PI':>6} {'Ratio':>6} {'Gap':>7}")
    print(f"  {'─'*95}")
    for _, r in sample.iterrows():
        tl = str(r["title_local"])[:33]
        ti = str(r["title_import"])[:33]
        print(f"  {tl:<35} {ti:<35} "
              f"${r['price_local']:>5.0f} ${r['price_import']:>5.0f} "
              f"{r['price_ratio']:>5.2f}× {r['gap_pct']:>+6.1f}%")

    return match_df

# ══════════════════════════════════════════════════════════════
# 4. ANÁLISIS POR CATEGORÍA
# ══════════════════════════════════════════════════════════════
def analyze_by_category(latest):
    print("\n" + "="*60)
    print("  4. ANÁLISIS POR CATEGORÍA (hardware PC)")
    print("="*60)
    cat_df = latest[
        latest["category"].str.lower().str.strip()
        .isin(CATEGORIAS_HARDWARE_PC)
    ].copy()

    if len(cat_df) == 0:
        return pd.DataFrame(), pd.DataFrame(), []

    cat_stats = (cat_df.groupby(["category","source","source_type"])
                       ["price_last"]
                       .agg(n="count", mean="mean", median="median",
                            std="std", min="min", max="max")
                       .reset_index())
    cat_stats["std"] = cat_stats["std"].fillna(0)
    cat_stats["cv"]  = (cat_stats["std"] /
                         cat_stats["mean"].replace(0, np.nan)).fillna(0)

    top_cats = (cat_df.groupby("category")["sku"]
                      .nunique().nlargest(15).index.tolist())

    idx_rows = []
    for cat in top_cats:
        sub      = cat_df[cat_df["category"]==cat]
        p_local  = sub[sub["source_type"]=="local"]["price_last"].median()
        p_import = sub[sub["source_type"]=="importacion"]["price_last"].median()
        n_local  = int((sub["source_type"]=="local").sum())
        n_import = int((sub["source_type"]=="importacion").sum())
        if pd.notna(p_local) and pd.notna(p_import) and p_import > 0:
            idx = p_local / p_import
            gap = (p_local - p_import) / p_import * 100
        else:
            idx = np.nan; gap = np.nan
        idx_rows.append({
            "category": cat, "p_local": p_local,
            "p_import": p_import, "idx_comp": idx,
            "gap_pct": gap, "n_local": n_local,
            "n_import": n_import,
        })
    idx_df = pd.DataFrame(idx_rows).dropna(subset=["idx_comp"])

    if len(idx_df) > 0:
        print(f"\n  Índice de Competitividad (hardware PC):")
        print(f"  {'Categoría':<25} {'P.Local':>8} "
              f"{'P.Import':>8} {'Índice':>7} {'Gap%':>7}")
        print(f"  {'─'*58}")
        for _, r in idx_df.sort_values("gap_pct").iterrows():
            flag = "✓" if r["idx_comp"] <= 1.0 else "↑"
            print(f"  {r['category']:<25} "
                  f"${r['p_local']:>7.0f} ${r['p_import']:>7.0f} "
                  f"{r['idx_comp']:>7.3f} {r['gap_pct']:>+6.1f}% {flag}")

    return cat_stats, idx_df, top_cats

# ══════════════════════════════════════════════════════════════
# 5. VISUALIZACIONES
# ══════════════════════════════════════════════════════════════
def plot_all(latest, match_df, cat_stats, idx_df, top_cats):
    print("\n" + "="*60)
    print("  5. GENERANDO VISUALIZACIONES")
    print("="*60)

    if len(idx_df) > 0:
        fig, ax = plt.subplots(figsize=(14, 6))
        fig.patch.set_facecolor(DARK); ax.set_facecolor(PANEL)
        idx_s = idx_df.sort_values("gap_pct")
        x = np.arange(len(idx_s)); w = 0.35
        ax.bar(x-w/2, idx_s["p_local"],  w, color=GREEN, alpha=0.85, label="Local")
        ax.bar(x+w/2, idx_s["p_import"], w, color=RED,   alpha=0.85, label="Importación")
        ax.set_xticks(x)
        ax.set_xticklabels(idx_s["category"], rotation=35, ha="right",
                           color=WHITE, fontsize=9)
        ax.set_ylabel("Precio Mediano (USD)", color=WHITE)
        ax.set_title("Precio Mediano por Categoría: Local vs Importación\n"
                     "(Hardware PC — pares validados v3)",
                     color=WHITE, fontsize=13, fontweight="bold")
        ax.tick_params(colors=WHITE); ax.spines[:].set_color(GRID)
        ax.grid(axis="y", alpha=0.2, color=WHITE)
        ax.legend(facecolor=PANEL, labelcolor=WHITE, edgecolor=GRID, fontsize=10)
        ax.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda v,_: f"${v:,.0f}"))
        plt.tight_layout()
        plt.savefig("figures/pe3b_fig1_categoria.png",
                    dpi=150, bbox_inches="tight", facecolor=DARK)
        plt.close()
        print("  ✓ figures/pe3b_fig1_categoria.png")

        fig, ax = plt.subplots(figsize=(12, 6))
        fig.patch.set_facecolor(DARK); ax.set_facecolor(PANEL)
        idx_s2    = idx_df.sort_values("gap_pct")
        colors_b  = [GREEN if v <= 0 else RED for v in idx_s2["gap_pct"]]
        bars = ax.barh(idx_s2["category"], idx_s2["gap_pct"],
                       color=colors_b, alpha=0.85)
        ax.axvline(0, color=WHITE, lw=1.5, ls="--")
        ax.set_xlabel("Brecha % (Local − Importación)", color=WHITE)
        ax.set_title("Índice de Competitividad — Hardware PC (v3)",
                     color=WHITE, fontsize=13, fontweight="bold")
        ax.tick_params(colors=WHITE); ax.spines[:].set_color(GRID)
        ax.grid(axis="x", alpha=0.2, color=WHITE)
        for bar, val in zip(bars, idx_s2["gap_pct"]):
            ax.text(val + (2 if val >= 0 else -2),
                    bar.get_y()+bar.get_height()/2,
                    f"{val:+.1f}%", va="center",
                    ha="left" if val >= 0 else "right",
                    color=WHITE, fontsize=9)
        plt.tight_layout()
        plt.savefig("figures/pe3b_fig2_indice.png",
                    dpi=150, bbox_inches="tight", facecolor=DARK)
        plt.close()
        print("  ✓ figures/pe3b_fig2_indice.png")

    if len(match_df) == 0:
        print("  ⚠ Sin matches — omitiendo figuras 3-5")
        return

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.patch.set_facecolor(DARK)
    fig.suptitle("OE3-B v3 — Brecha Validada: Hardware PC",
                 color=WHITE, fontsize=14, fontweight="bold")

    ax = axes[0]; ax.set_facecolor(PANEL)
    gap = match_df["gap_pct"].clip(-150, 300)
    neg = gap[gap < 0]; pos = gap[gap >= 0]
    if len(neg) > 0:
        ax.hist(neg, bins=40, color=GREEN, alpha=0.75,
                label=f"Local más barato ({len(neg):,})")
    if len(pos) > 0:
        ax.hist(pos, bins=40, color=RED, alpha=0.75,
                label=f"Import más barato ({len(pos):,})")
    med = gap.median()
    ax.axvline(0,   color=WHITE, lw=1.5, ls="--")
    ax.axvline(med, color=AMBER, lw=2,   ls=":",
               label=f"Mediana {med:+.1f}%")
    ax.set_xlabel("Brecha % (Local − Importación)", color=WHITE)
    ax.set_ylabel("N° pares", color=WHITE)
    ax.set_title("Distribución de Brecha (pares validados)", color=WHITE)
    ax.tick_params(colors=WHITE); ax.spines[:].set_color(GRID)
    ax.grid(alpha=0.2, color=WHITE)
    ax.legend(facecolor=PANEL, labelcolor=WHITE, edgecolor=GRID, fontsize=9)

    ax2 = axes[1]; ax2.set_facecolor(PANEL)
    sample   = match_df.sample(min(2000, len(match_df)), random_state=42)
    colors_s = [GREEN if g < 0 else RED for g in sample["gap_pct"]]
    ax2.scatter(sample["price_import"], sample["price_local"],
                c=colors_s, alpha=0.3, s=8)
    lim = max(sample["price_import"].max(),
              sample["price_local"].max()) * 1.05
    ax2.plot([0,lim],[0,lim], color=WHITE, lw=1.5, ls="--", label="Paridad")
    ax2.plot([0,lim],[0,lim*CFG["price_ratio_max"]],
             color=AMBER, lw=1, ls=":", alpha=0.6,
             label=f"Límite ×{CFG['price_ratio_max']}")
    ax2.set_xlabel("Precio Importación (USD)", color=WHITE)
    ax2.set_ylabel("Precio Local (USD)", color=WHITE)
    ax2.set_title("Local vs Importación — Matches Validados", color=WHITE)
    ax2.tick_params(colors=WHITE); ax2.spines[:].set_color(GRID)
    ax2.grid(alpha=0.15, color=WHITE)
    ax2.legend(facecolor=PANEL, labelcolor=WHITE, edgecolor=GRID, fontsize=9)
    try:
        ax2.set_xscale("log"); ax2.set_yscale("log")
    except Exception:
        pass
    plt.tight_layout()
    plt.savefig("figures/pe3b_fig3_scatter_matches.png",
                dpi=150, bbox_inches="tight", facecolor=DARK)
    plt.close()
    print("  ✓ figures/pe3b_fig3_scatter_matches.png")

    cat_match = (match_df[match_df["category"]!="unknown"]
                 .groupby("category")["gap_pct"]
                 .agg(median="median", count="count")
                 .reset_index().query("count >= 5")
                 .sort_values("median"))
    if len(cat_match) > 0:
        fig, ax = plt.subplots(figsize=(12, 6))
        fig.patch.set_facecolor(DARK); ax.set_facecolor(PANEL)
        colors_c = [GREEN if v <= 0 else RED for v in cat_match["median"]]
        bars = ax.barh(cat_match["category"], cat_match["median"],
                       color=colors_c, alpha=0.85)
        ax.axvline(0, color=WHITE, lw=1.5, ls="--")
        ax.set_xlabel("Brecha Mediana % (Local − Importación)", color=WHITE)
        ax.set_title("Brecha por Categoría — Pares Validados v3",
                     color=WHITE, fontsize=13, fontweight="bold")
        ax.tick_params(colors=WHITE); ax.spines[:].set_color(GRID)
        ax.grid(axis="x", alpha=0.2, color=WHITE)
        for bar, (_, row) in zip(bars, cat_match.iterrows()):
            v = row["median"]
            ax.text(v + (1 if v >= 0 else -1),
                    bar.get_y()+bar.get_height()/2,
                    f"{v:+.1f}% (n={row['count']:.0f})",
                    va="center",
                    ha="left" if v >= 0 else "right",
                    color=WHITE, fontsize=9)
        plt.tight_layout()
        plt.savefig("figures/pe3b_fig4_gap_categoria.png",
                    dpi=150, bbox_inches="tight", facecolor=DARK)
        plt.close()
        print("  ✓ figures/pe3b_fig4_gap_categoria.png")

    top_gap = match_df.nlargest(20, "gap_pct")[
        ["title_local","source_local","price_local",
         "source_import","price_import","gap_pct","match_score"]]
    if len(top_gap) > 0:
        fig, ax = plt.subplots(figsize=(14, 8))
        fig.patch.set_facecolor(DARK); ax.set_facecolor(PANEL)
        labels = [f"{str(r['title_local'])[:30]}…"
                  if len(str(r['title_local'])) > 30
                  else str(r['title_local'])
                  for _, r in top_gap.iterrows()]
        y = np.arange(len(labels))
        ax.barh(y, top_gap["gap_pct"].values, color=RED, alpha=0.8)
        ax.set_yticks(y)
        ax.set_yticklabels(labels, color=WHITE, fontsize=8)
        ax.set_xlabel("Brecha % (Local más caro)", color=WHITE)
        ax.set_title("Top 20 Productos con Mayor Brecha — Validados v3",
                     color=WHITE, fontsize=13, fontweight="bold")
        ax.tick_params(colors=WHITE); ax.spines[:].set_color(GRID)
        ax.grid(axis="x", alpha=0.2, color=WHITE)
        for i, (_, row) in enumerate(top_gap.iterrows()):
            ax.text(row["gap_pct"]+1, i,
                    f"+{row['gap_pct']:.0f}% (score {row['match_score']:.0f})",
                    va="center", color=WHITE, fontsize=8)
        plt.tight_layout()
        plt.savefig("figures/pe3b_fig5_top_gaps.png",
                    dpi=150, bbox_inches="tight", facecolor=DARK)
        plt.close()
        print("  ✓ figures/pe3b_fig5_top_gaps.png")

# ══════════════════════════════════════════════════════════════
# 6. GUARDAR
# ══════════════════════════════════════════════════════════════
def save_results(match_df, cat_stats, idx_df, latest):
    print("\n" + "="*60)
    print("  6. GUARDANDO RESULTADOS")
    print("="*60)

    if len(match_df) > 0:
        match_df.to_csv("results/pe3b_matches.csv", index=False)
        print(f"  ✓ results/pe3b_matches.csv ({len(match_df):,} pares)")

    if len(cat_stats) > 0:
        cat_stats.to_csv("results/pe3b_category_stats.csv", index=False)
        print(f"  ✓ results/pe3b_category_stats.csv")

    comp = {}
    if len(match_df) > 0:
        n_lc = int((match_df["gap_pct"] < 0).sum())
        n_ic = int((match_df["gap_pct"] > 0).sum())
        comp = {
            "version"               : "v3 — filtro ratio precio",
            "pares_matcheados"      : int(len(match_df)),
            "threshold_fuzzy"       : CFG["match_threshold"],
            "price_ratio_min"       : CFG["price_ratio_min"],
            "price_ratio_max"       : CFG["price_ratio_max"],
            "price_import_min"      : CFG["price_import_min"],
            "score_mediano"         : round(float(match_df["match_score"].median()),1),
            "gap_mediana_pct"       : round(float(match_df["gap_pct"].median()),2),
            "gap_media_pct"         : round(float(match_df["gap_pct"].mean()),2),
            "pct_local_mas_barato"  : round(n_lc/len(match_df)*100,2),
            "pct_import_mas_barato" : round(n_ic/len(match_df)*100,2),
        }

    idx_comp = {}
    if len(idx_df) > 0:
        idx_comp = (idx_df.set_index("category")
                          [["p_local","p_import","idx_comp","gap_pct"]]
                          .round(2).to_dict(orient="index"))

    results = {
        "oe"       : "OE3-B",
        "version"  : "v3",
        "timestamp": datetime.now().isoformat(),
        "metodo"   : (
            "Fuzzy matching (rapidfuzz token_sort_ratio, "
            f"score≥{CFG['match_threshold']}) + "
            "filtro ratio precio [0.5×, 4.0×] + "
            f"precio import≥${CFG['price_import_min']}. "
            "Scope: hardware PC (CPU, GPU, RAM, SSD, MB, PSU, "
            "Monitores, Laptops, Computadoras, Cooler, Case)."
        ),
        "matching_por_modelo"                 : comp,
        "indice_competitividad_por_categoria" : idx_comp,
    }
    with open("results/pe3b_competitividad.json","w",
              encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print("  ✓ results/pe3b_competitividad.json")
    return results

# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  OE3-B v3: Matching Validado por Ratio de Precio")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    latest, p_low, p_high = load_latest()
    latest                = add_model_key(latest)
    match_df              = fuzzy_match(latest)
    cat_stats, idx_df, \
    top_cats              = analyze_by_category(latest)
    plot_all(latest, match_df, cat_stats, idx_df, top_cats)
    results               = save_results(match_df, cat_stats, idx_df, latest)

    print("\n" + "=" * 60)
    print("  OE3-B v3 COMPLETADO")
    print("=" * 60)
    m = results.get("matching_por_modelo", {})
    if m:
        print(f"\n  Pares validados   : {m.get('pares_matcheados',0):,}")
        print(f"  Score mediano     : {m.get('score_mediano',0):.1f}/100")
        print(f"  Brecha mediana    : {m.get('gap_mediana_pct',0):+.1f}%")
        print(f"  Local más barato  : {m.get('pct_local_mas_barato',0):.1f}%")
        print(f"  Import más barato : {m.get('pct_import_mas_barato',0):.1f}%")
    print(f"\n  Siguiente:")
    print(f"    python scripts/pe3c_costo_real.py")
    print(f"    python scripts/oe4a_roi_calculator.py")