"""
pe3c_costo_real.py — OE3-C: Brecha con Costo Real de Importación
=================================================================
Fix: renombradas variables arancel_$ → arancel_monto, igv_$ → igv_monto
"""

import json, warnings
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

warnings.filterwarnings("ignore")
Path("figures").mkdir(parents=True, exist_ok=True)
Path("results").mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════════════════
# PARÁMETROS DEL MODELO DE IMPORTACIÓN
# ══════════════════════════════════════════════════════════════
ARANCELES = {
    "cpu"           : 0.00, "procesadores"  : 0.00,
    "gpu"           : 0.00, "tarjetas_video" : 0.00,
    "ram"           : 0.00, "memorias_ram"   : 0.00,
    "ssd"           : 0.00, "discos_ssd"     : 0.00,
    "motherboard"   : 0.00, "psu"            : 0.00,
    "monitores"     : 0.00, "laptops"        : 0.00,
    "computadoras"  : 0.00,
    "auriculares"   : 0.06, "teclados"       : 0.06,
    "mouse"         : 0.06, "videojuegos"    : 0.06,
    "smartwatch"    : 0.06, "unknown"        : 0.06,
    "default"       : 0.06,
}

IGV = 0.18
IPM = 0.02
TAX = IGV + IPM   # 20%

ESCENARIOS = {
    "opt" : {
        "label"           : "Optimista (casilla/courier experto)",
        "envio_pct"       : 0.04,
        "envio_fijo"      : 10.0,
        "despacho_umbral" : 200.0,
        "despacho_costo"  : 0.0,
        "arancel_extra"   : 0.00,
        "color"           : "#00ff88",
    },
    "base": {
        "label"           : "Base (consumidor típico)",
        "envio_pct"       : 0.07,
        "envio_fijo"      : 15.0,
        "despacho_umbral" : 200.0,
        "despacho_costo"  : 50.0,
        "arancel_extra"   : 0.00,
        "color"           : "#00d4ff",
    },
    "cons": {
        "label"           : "Conservador (máximo costo)",
        "envio_pct"       : 0.10,
        "envio_fijo"      : 20.0,
        "despacho_umbral" : 200.0,
        "despacho_costo"  : 60.0,
        "arancel_extra"   : 0.06,
        "color"           : "#ff4d6d",
    },
}

DARK  = '#0f0f1a'; PANEL = '#1a1a2e'; GRID = '#2a2a3e'
WHITE = '#e8e8f0'; CYAN  = '#00d4ff'; GREEN = '#00ff88'
AMBER = '#ffaa00'; RED   = '#ff4d6d'

# ══════════════════════════════════════════════════════════════
# 1. FUNCIÓN DE COSTO REAL  (fix: sin $ en nombres)
# ══════════════════════════════════════════════════════════════
def costo_real_importacion(precio_origen: float,
                            categoria: str,
                            escenario: str) -> dict:
    cfg         = ESCENARIOS[escenario]
    cat_key     = categoria.lower().strip()
    arancel_cat = ARANCELES.get(cat_key, ARANCELES["default"])
    arancel_tot = arancel_cat + cfg["arancel_extra"]

    envio        = precio_origen * cfg["envio_pct"] + cfg["envio_fijo"]
    precio_cif   = precio_origen + envio
    arancel_monto = precio_cif * arancel_tot
    base_igv     = precio_cif + arancel_monto
    igv_monto    = base_igv * TAX
    despacho     = (cfg["despacho_costo"]
                    if precio_cif > cfg["despacho_umbral"] else 0.0)
    total        = precio_cif + arancel_monto + igv_monto + despacho

    return {
        "precio_origen"  : round(precio_origen, 2),
        "envio"          : round(envio, 2),
        "precio_cif"     : round(precio_cif, 2),
        "arancel"        : round(arancel_monto, 2),
        "igv_ipm"        : round(igv_monto, 2),
        "despacho"       : round(despacho, 2),
        "total"          : round(total, 2),
        "overhead_pct"   : round((total / precio_origen - 1) * 100, 1),
    }

# ══════════════════════════════════════════════════════════════
# 2. CARGAR MATCHES Y APLICAR MODELO
# ══════════════════════════════════════════════════════════════
def load_and_enrich():
    print("\n" + "="*60)
    print("  1. CARGANDO MATCHES Y APLICANDO MODELO DE COSTO")
    print("="*60)

    fp = Path("results/pe3b_matches.csv")
    if not fp.exists():
        raise FileNotFoundError(
            "No se encontró results/pe3b_matches.csv\n"
            "Ejecuta primero: python scripts/pe3b_matching.py")

    df = pd.read_csv(fp, low_memory=False)
    print(f"  Pares cargados: {len(df):,}")

    df["category"] = (df["category"].fillna("unknown")
                                     .astype(str)
                                     .str.lower()
                                     .str.strip())

    print("  Calculando costos reales...")
    for esc in ["opt", "base", "cons"]:
        totales   = []
        overheads = []
        for _, row in df.iterrows():
            r = costo_real_importacion(
                row["price_import"], row["category"], esc)
            totales.append(r["total"])
            overheads.append(r["overhead_pct"])

        df[f"price_import_real_{esc}"] = totales
        df[f"overhead_pct_{esc}"]      = overheads
        df[f"gap_pct_real_{esc}"] = (
            (df["price_local"] - df[f"price_import_real_{esc}"]) /
             df[f"price_import_real_{esc}"] * 100
        ).clip(-200, 500)
        df[f"conviene_local_{esc}"] = (
            df[f"gap_pct_real_{esc}"] <= 0).astype(int)

        n_local = int(df[f"conviene_local_{esc}"].sum())
        n_total = len(df)
        med_gap = df[f"gap_pct_real_{esc}"].median()
        print(f"\n  [{esc.upper()}] {ESCENARIOS[esc]['label']}")
        print(f"    Overhead importación mediano : "
              f"+{df[f'overhead_pct_{esc}'].median():.1f}%")
        print(f"    Brecha mediana ajustada      : {med_gap:+.1f}%")
        print(f"    Conviene comprar LOCAL       : "
              f"{n_local:,} / {n_total:,} "
              f"({n_local/n_total*100:.1f}%)")
        print(f"    Conviene IMPORTAR            : "
              f"{n_total-n_local:,} / {n_total:,} "
              f"({(n_total-n_local)/n_total*100:.1f}%)")

    print(f"\n  Overhead escenario BASE por tramo de precio:")
    tramos = [(0,50),(50,100),(100,200),(200,500),(500,1000),(1000,9999)]
    for lo, hi in tramos:
        mask = (df["price_import"] >= lo) & (df["price_import"] < hi)
        if mask.sum() > 0:
            med = df.loc[mask, "overhead_pct_base"].median()
            print(f"    ${lo:>5}–${hi:<5} → overhead mediano "
                  f"{med:+.1f}%  (n={mask.sum():,})")

    return df

# ══════════════════════════════════════════════════════════════
# 3. ANÁLISIS POR CATEGORÍA
# ══════════════════════════════════════════════════════════════
def analyze_by_category(df):
    print("\n" + "="*60)
    print("  2. BRECHA REAL POR CATEGORÍA (escenario BASE)")
    print("="*60)

    cats_ok = (df[df["category"] != "unknown"]
                 .groupby("category")["gap_pct_real_base"]
                 .count()
                 .loc[lambda x: x >= 10]
                 .index.tolist())

    cat_rows = []
    for cat in cats_ok:
        sub = df[df["category"] == cat]
        cat_rows.append({
            "category"               : cat,
            "n_pares"                : len(sub),
            "gap_raw_median"         : sub["gap_pct"].median(),
            "gap_opt_median"         : sub["gap_pct_real_opt"].median(),
            "gap_base_median"        : sub["gap_pct_real_base"].median(),
            "gap_cons_median"        : sub["gap_pct_real_cons"].median(),
            "pct_conviene_local_base": sub["conviene_local_base"].mean()*100,
            "overhead_base_median"   : sub["overhead_pct_base"].median(),
        })

    cat_df = (pd.DataFrame(cat_rows)
                .sort_values("gap_base_median"))

    print(f"\n  {'Categoría':<20} {'Sin ajuste':>10} "
          f"{'Opt':>8} {'Base':>8} {'Cons':>8} "
          f"{'%Local':>7} {'N':>6}")
    print(f"  {'─'*72}")
    for _, r in cat_df.iterrows():
        print(f"  {r['category']:<20} "
              f"{r['gap_raw_median']:>+9.1f}% "
              f"{r['gap_opt_median']:>+7.1f}% "
              f"{r['gap_base_median']:>+7.1f}% "
              f"{r['gap_cons_median']:>+7.1f}% "
              f"{r['pct_conviene_local_base']:>6.1f}% "
              f"{r['n_pares']:>6,.0f}")

    return cat_df

# ══════════════════════════════════════════════════════════════
# 4. PUNTO DE EQUILIBRIO
# ══════════════════════════════════════════════════════════════
def punto_equilibrio():
    print("\n" + "="*60)
    print("  3. OVERHEAD POR CATEGORÍA A PRECIO $300")
    print("="*60)

    categorias = ["cpu","gpu","ram","ssd","monitores","laptops"]
    print(f"\n  {'Categoría':<15} {'Optimista':>10} "
          f"{'Base':>10} {'Conservador':>12}")
    print(f"  {'─'*50}")
    for cat in categorias:
        vals = {esc: costo_real_importacion(300, cat, esc)["overhead_pct"]
                for esc in ["opt","base","cons"]}
        print(f"  {cat:<15} {vals['opt']:>+9.1f}% "
              f"{vals['base']:>+9.1f}% {vals['cons']:>+11.1f}%")

    precios = np.linspace(10, 2000, 500)
    eq_rows = []
    for cat in categorias:
        for esc in ["opt","base","cons"]:
            overheads = [costo_real_importacion(p, cat, esc)["overhead_pct"]
                         for p in precios]
            eq_rows.append({
                "categoria": cat, "escenario": esc,
                "precios": precios, "overheads": overheads,
            })
    return eq_rows

# ══════════════════════════════════════════════════════════════
# 5. VISUALIZACIONES
# ══════════════════════════════════════════════════════════════
def plot_all(df, cat_df, eq_rows):
    print("\n" + "="*60)
    print("  4. GENERANDO VISUALIZACIONES")
    print("="*60)

    # ── FIG 1: Distribución brecha por escenario ──────────────
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    fig.patch.set_facecolor(DARK)
    fig.suptitle("OE3-C — Brecha de Precios con Costo Real de Importación",
                 color=WHITE, fontsize=14, fontweight="bold")

    for i, esc in enumerate(["opt","base","cons"]):
        ax  = axes[i]
        ax.set_facecolor(PANEL)
        cfg = ESCENARIOS[esc]
        gap = df[f"gap_pct_real_{esc}"].clip(-100, 300)
        neg = gap[gap < 0]
        pos = gap[gap >= 0]
        if len(neg) > 0:
            ax.hist(neg, bins=50, color=GREEN, alpha=0.75,
                    label=f"Local mejor ({len(neg):,})")
        if len(pos) > 0:
            ax.hist(pos, bins=50, color=RED, alpha=0.75,
                    label=f"Import mejor ({len(pos):,})")
        med = gap.median()
        ax.axvline(0,   color=WHITE, lw=1.5, ls="--")
        ax.axvline(med, color=AMBER, lw=2,   ls=":",
                   label=f"Mediana {med:+.0f}%")
        ax.set_title(f"Escenario {esc.upper()}\n{cfg['label']}",
                     color=cfg["color"], fontsize=10, fontweight="bold")
        ax.set_xlabel("Brecha % (Local − Import ajustado)", color=WHITE)
        ax.set_ylabel("N° pares" if i == 0 else "", color=WHITE)
        ax.tick_params(colors=WHITE); ax.spines[:].set_color(GRID)
        ax.grid(alpha=0.2, color=WHITE)
        ax.legend(facecolor=PANEL, labelcolor=WHITE,
                  edgecolor=GRID, fontsize=8)
        pct_local = df[f"conviene_local_{esc}"].mean() * 100
        ax.text(0.97, 0.97,
                f"Local conviene\n{pct_local:.1f}%",
                transform=ax.transAxes, ha="right", va="top",
                color=GREEN, fontsize=10, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3",
                          facecolor=PANEL, edgecolor=GREEN))

    plt.tight_layout()
    plt.savefig("figures/pe3c_fig1_escenarios.png",
                dpi=150, bbox_inches="tight", facecolor=DARK)
    plt.close()
    print("  ✓ figures/pe3c_fig1_escenarios.png")

    # ── FIG 2: Brecha por categoría — 3 escenarios ────────────
    if len(cat_df) > 0:
        fig, ax = plt.subplots(figsize=(14, 7))
        fig.patch.set_facecolor(DARK); ax.set_facecolor(PANEL)
        cats = cat_df["category"].tolist()
        x    = np.arange(len(cats)); w = 0.25

        for j, (esc, col) in enumerate(
                [("opt",GREEN),("base",CYAN),("cons",RED)]):
            ax.bar(x + (j-1)*w, cat_df[f"gap_{esc}_median"].values,
                   w, color=col, alpha=0.82,
                   label=f"{esc.upper()} — {ESCENARIOS[esc]['label']}")

        ax.plot(x, cat_df["gap_raw_median"].values,
                color=AMBER, lw=2, ls="--", marker="o", ms=5,
                label="Sin ajuste (precio origen)")
        ax.axhline(0, color=WHITE, lw=1.5, ls="--")
        ax.set_xticks(x)
        ax.set_xticklabels(cats, rotation=35, ha="right",
                           color=WHITE, fontsize=9)
        ax.set_ylabel("Brecha Mediana %", color=WHITE)
        ax.set_title(
            "Brecha Real por Categoría — 3 Escenarios de Importación",
            color=WHITE, fontsize=13, fontweight="bold")
        ax.tick_params(colors=WHITE); ax.spines[:].set_color(GRID)
        ax.grid(axis="y", alpha=0.2, color=WHITE)
        ax.legend(facecolor=PANEL, labelcolor=WHITE,
                  edgecolor=GRID, fontsize=9, ncol=2)
        ax.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda v, _: f"{v:+.0f}%"))
        plt.tight_layout()
        plt.savefig("figures/pe3c_fig2_categoria_real.png",
                    dpi=150, bbox_inches="tight", facecolor=DARK)
        plt.close()
        print("  ✓ figures/pe3c_fig2_categoria_real.png")

    # ── FIG 3: Overhead de importación por precio ─────────────
    fig, ax = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor(DARK); ax.set_facecolor(PANEL)
    precios = np.linspace(10, 1500, 400)
    for esc, col in [("opt",GREEN),("base",CYAN),("cons",RED)]:
        ovh = [costo_real_importacion(p, "cpu", esc)["overhead_pct"]
               for p in precios]
        ax.plot(precios, ovh, color=col, lw=2.5,
                label=f"{esc.upper()} — {ESCENARIOS[esc]['label']}")
    ax.axhline(0, color=WHITE, lw=1, ls="--")
    ylim_top = max(
        [costo_real_importacion(10, "cpu", "cons")["overhead_pct"],
         costo_real_importacion(10, "cpu", "base")["overhead_pct"],
         costo_real_importacion(10, "cpu", "opt")["overhead_pct"]]
    ) * 1.05
    for p_mark in [50, 200, 500, 1000]:
        ax.axvline(p_mark, color=GRID, lw=1, ls=":")
        ax.text(p_mark + 5, ylim_top * 0.95,
                f"${p_mark}", color=WHITE, fontsize=8, va="top")
    ax.set_xlabel("Precio de Origen (USD)", color=WHITE)
    ax.set_ylabel("Overhead Total de Importación (%)", color=WHITE)
    ax.set_title(
        "Costo de Importar a Perú según Precio del Producto\n"
        "(envío + aranceles + IGV/IPM + despacho)",
        color=WHITE, fontsize=12, fontweight="bold")
    ax.tick_params(colors=WHITE); ax.spines[:].set_color(GRID)
    ax.grid(alpha=0.2, color=WHITE)
    ax.legend(facecolor=PANEL, labelcolor=WHITE,
              edgecolor=GRID, fontsize=10)
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    plt.tight_layout()
    plt.savefig("figures/pe3c_fig3_overhead_precio.png",
                dpi=150, bbox_inches="tight", facecolor=DARK)
    plt.close()
    print("  ✓ figures/pe3c_fig3_overhead_precio.png")

    # ── FIG 4: Mapa de decisión ───────────────────────────────
    fig, ax = plt.subplots(figsize=(14, 7))
    fig.patch.set_facecolor(DARK); ax.set_facecolor(PANEL)
    sample   = df.sample(min(5000, len(df)), random_state=42)
    colors_s = [GREEN if g <= 0 else RED
                for g in sample["gap_pct_real_base"]]
    ax.scatter(sample["price_import"],
               sample["gap_pct_real_base"].clip(-100, 300),
               c=colors_s, alpha=0.2, s=6)
    ax.axhline(0, color=WHITE, lw=2, ls="--",
               label="Punto de equilibrio (brecha = 0%)")
    ax.fill_between([sample["price_import"].min(),
                     sample["price_import"].max()],
                    -100, 0, alpha=0.05, color=GREEN)
    ax.fill_between([sample["price_import"].min(),
                     sample["price_import"].max()],
                    0, 300, alpha=0.05, color=RED)
    ax.text(0.02, 0.10, "✓ Conviene comprar LOCAL",
            transform=ax.transAxes, color=GREEN,
            fontsize=11, fontweight="bold")
    ax.text(0.02, 0.90, "✗ Conviene IMPORTAR",
            transform=ax.transAxes, color=RED,
            fontsize=11, fontweight="bold")
    ax.set_xlabel("Precio de Importación (USD)", color=WHITE)
    ax.set_ylabel("Brecha % ajustada (Local − Import real)", color=WHITE)
    ax.set_title(
        "Mapa de Decisión: ¿Comprar Local o Importar?\n"
        "(Escenario BASE — consumidor típico peruano)",
        color=WHITE, fontsize=13, fontweight="bold")
    ax.tick_params(colors=WHITE); ax.spines[:].set_color(GRID)
    ax.grid(alpha=0.15, color=WHITE)
    ax.legend(facecolor=PANEL, labelcolor=WHITE,
              edgecolor=GRID, fontsize=10)
    try:
        ax.set_xscale("log")
    except Exception:
        pass
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"{v:+.0f}%"))
    plt.tight_layout()
    plt.savefig("figures/pe3c_fig4_decision_map.png",
                dpi=150, bbox_inches="tight", facecolor=DARK)
    plt.close()
    print("  ✓ figures/pe3c_fig4_decision_map.png")

# ══════════════════════════════════════════════════════════════
# 6. GUARDAR RESULTADOS
# ══════════════════════════════════════════════════════════════
def save_results(df, cat_df):
    print("\n" + "="*60)
    print("  5. GUARDANDO RESULTADOS")
    print("="*60)

    df.to_csv("results/pe3c_matches_costo_real.csv", index=False)
    print(f"  ✓ results/pe3c_matches_costo_real.csv ({len(df):,} pares)")

    resumen = {
        "oe"       : "OE3-C",
        "timestamp": datetime.now().isoformat(),
        "modelo_importacion": {
            "igv_ipm_pct": TAX * 100,
            "escenarios" : {
                esc: {
                    "label"            : cfg["label"],
                    "envio_pct"        : cfg["envio_pct"] * 100,
                    "envio_fijo_usd"   : cfg["envio_fijo"],
                    "despacho_usd"     : cfg["despacho_costo"],
                    "arancel_extra_pct": cfg["arancel_extra"] * 100,
                }
                for esc, cfg in ESCENARIOS.items()
            },
        },
        "resultados_globales": {
            esc: {
                "brecha_mediana_ajustada_pct":
                    round(float(df[f"gap_pct_real_{esc}"].median()), 2),
                "pct_conviene_local":
                    round(float(df[f"conviene_local_{esc}"].mean()*100), 2),
                "pct_conviene_importar":
                    round(float((1-df[f"conviene_local_{esc}"].mean())*100), 2),
                "overhead_mediano_pct":
                    round(float(df[f"overhead_pct_{esc}"].median()), 2),
            }
            for esc in ["opt","base","cons"]
        },
        "por_categoria": (
            cat_df.set_index("category")
                  [["gap_raw_median","gap_opt_median",
                    "gap_base_median","gap_cons_median",
                    "pct_conviene_local_base","n_pares"]]
                  .round(2).to_dict(orient="index")
            if len(cat_df) > 0 else {}
        ),
        "figuras": [
            "figures/pe3c_fig1_escenarios.png",
            "figures/pe3c_fig2_categoria_real.png",
            "figures/pe3c_fig3_overhead_precio.png",
            "figures/pe3c_fig4_decision_map.png",
        ],
    }

    with open("results/pe3c_resumen.json", "w", encoding="utf-8") as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False)
    print("  ✓ results/pe3c_resumen.json")
    return resumen

# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  OE3-C: Brecha con Costo Real de Importación")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    df     = load_and_enrich()
    cat_df = analyze_by_category(df)
    eq     = punto_equilibrio()
    plot_all(df, cat_df, eq)
    res    = save_results(df, cat_df)

    print("\n" + "=" * 60)
    print("  OE3-C COMPLETADO — RESUMEN EJECUTIVO")
    print("=" * 60)
    print(f"\n  {'Escenario':<12} {'Brecha mediana':>15} "
          f"{'Conviene local':>15} {'Conviene import':>16}")
    print(f"  {'─'*60}")
    for esc in ["opt","base","cons"]:
        r = res["resultados_globales"][esc]
        print(f"  {esc.upper():<12} "
              f"{r['brecha_mediana_ajustada_pct']:>+14.1f}% "
              f"{r['pct_conviene_local']:>14.1f}% "
              f"{r['pct_conviene_importar']:>15.1f}%")
    print(f"\n  ⚠  Escenario BASE = recomendado para tesis.")
    print(f"\n  Outputs:")
    for fig in res["figuras"]:
        print(f"    {fig}")
    print(f"    results/pe3c_matches_costo_real.csv")
    print(f"    results/pe3c_resumen.json")