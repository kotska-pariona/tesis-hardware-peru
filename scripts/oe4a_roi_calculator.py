"""
oe4a_roi_calculator.py — OE4-A v3
===================================
CAMBIOS v3:
  - agresivo: factor_venta 0.80 → 0.75
    Justificación: el operador agresivo apuesta a volumen,
    por lo que compite más agresivamente en precio que el moderado.
    Precio real de venta ≈ 75% del precio de lista local.
  
Tabla de factores definitiva:
  conservador: factor_venta=0.65, rotacion=0.85, costo_op=0.05
  moderado   : factor_venta=0.72, rotacion=0.90, costo_op=0.04
  agresivo   : factor_venta=0.75, rotacion=0.95, costo_op=0.03  ← CORREGIDO

ROI esperado resultante (estimado):
  conservador: +20% a +50%
  moderado   : +30% a +70%
  agresivo   : +40% a +80%   ← ya no +100%
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
Path("results").mkdir(parents=True, exist_ok=True)
Path("figures").mkdir(parents=True, exist_ok=True)

PERFILES = {
    "conservador": {
        "label"           : "Conservador",
        "factor_venta"    : 0.65,
        "factor_rotacion" : 0.85,
        "costo_operativo" : 0.05,
        "margen_min_pct"  : 15.0,
        "max_precio_unit" : 300.0,
        "min_score_match" : 90,
        "color"           : "#00ff88",
        "descripcion"     : "Vende −35% del precio lista, 85% rotación",
    },
    "moderado": {
        "label"           : "Moderado",
        "factor_venta"    : 0.72,
        "factor_rotacion" : 0.90,
        "costo_operativo" : 0.04,
        "margen_min_pct"  : 10.0,
        "max_precio_unit" : 800.0,
        "min_score_match" : 85,
        "color"           : "#00d4ff",
        "descripcion"     : "Vende −28% del precio lista, 90% rotación",
    },
    "agresivo": {
        "label"           : "Agresivo",
        "factor_venta"    : 0.75,   # ← CORREGIDO: era 0.80
        "factor_rotacion" : 0.95,
        "costo_operativo" : 0.03,
        "margen_min_pct"  : 8.0,
        "max_precio_unit" : 2000.0,
        "min_score_match" : 85,
        "color"           : "#ff4d6d",
        "descripcion"     : "Vende −25% del precio lista, 95% rotación",
    },
}

DEMANDA_CATEGORIA = {
    "gpu": 1.4, "tarjetas_video": 1.4,
    "cpu": 1.3, "procesadores"  : 1.3,
    "ram": 1.5, "memorias_ram"  : 1.5,
    "ssd": 1.4, "discos_ssd"    : 1.4,
    "motherboard": 1.1, "psu"   : 1.0,
    "monitores"  : 1.2, "laptops": 1.3,
    "computadoras": 0.8, "cooler": 0.9,
    "case": 0.8, "default"      : 1.0,
}

DARK  = '#0f0f1a'; PANEL = '#1a1a2e'; GRID = '#2a2a3e'
WHITE = '#e8e8f0'; CYAN  = '#00d4ff'; GREEN = '#00ff88'
AMBER = '#ffaa00'; RED   = '#ff4d6d'

def calcular_roi(perfil: str = "moderado") -> pd.DataFrame:
    print("\n" + "="*60)
    print(f"  CALCULANDO ROI — Perfil: {perfil.upper()} (v3)")
    print("="*60)

    cfg = PERFILES[perfil]
    print(f"  Factor venta     : ×{cfg['factor_venta']} "
          f"(−{(1-cfg['factor_venta'])*100:.0f}% del precio lista)")
    print(f"  Factor rotación  : {cfg['factor_rotacion']*100:.0f}% del stock vendido")
    print(f"  Costo operativo  : {cfg['costo_operativo']*100:.0f}% sobre venta")

    fp = Path("results/pe3c_matches_costo_real.csv")
    if not fp.exists():
        raise FileNotFoundError(
            "Ejecuta primero: python scripts/pe3c_costo_real.py")

    df = pd.read_csv(fp, low_memory=False)
    df["category"] = (df["category"].fillna("unknown")
                                     .astype(str).str.lower().str.strip())

    n0 = len(df)
    df = df[df["match_score"] >= cfg["min_score_match"]]
    df = df[df["price_import_real_base"] <= cfg["max_precio_unit"]]
    df = df[df["price_import_real_base"] > 0].copy()
    print(f"  Pares tras filtros: {len(df):,} (de {n0:,})")

    df["precio_venta_bruto"]    = (df["price_local"] * cfg["factor_venta"]).round(2)
    df["costo_operativo_usd"]   = (df["precio_venta_bruto"] * cfg["costo_operativo"]).round(2)
    df["precio_venta_est"]      = (df["precio_venta_bruto"] - df["costo_operativo_usd"]).round(2)
    df["ganancia_unitaria_bruta"] = (df["precio_venta_est"] - df["price_import_real_base"]).round(2)
    df["roi_unitario_pct"]      = (df["ganancia_unitaria_bruta"] / df["price_import_real_base"] * 100).round(2)

    # ROI esperado ajustado por rotación
    df["ganancia_esperada"] = (
        df["ganancia_unitaria_bruta"] * cfg["factor_rotacion"]
        - df["price_import_real_base"] * (1 - cfg["factor_rotacion"])
    ).round(2)
    df["roi_esperado_pct"] = (
        df["ganancia_esperada"] / df["price_import_real_base"] * 100
    ).round(2)

    n_antes = len(df)
    df = df[df["roi_esperado_pct"] >= cfg["margen_min_pct"]].copy()
    print(f"  Tras filtro ROI_esperado≥{cfg['margen_min_pct']:.0f}%: "
          f"{len(df):,} (−{n_antes-len(df):,})")

    if len(df) == 0:
        return pd.DataFrame()

    df["demanda_cat"]     = df["category"].map(
        lambda c: DEMANDA_CATEGORIA.get(c, DEMANDA_CATEGORIA["default"]))
    df["score_confianza"] = df["match_score"] / 100.0
    df["score_demanda"]   = (df["demanda_cat"] * df["score_confianza"]).round(4)

    roi_norm     = (df["roi_esperado_pct"] / df["roi_esperado_pct"].max()).clip(0,1)
    demanda_norm = (df["score_demanda"]    / df["score_demanda"].max()).clip(0,1)
    df["score_roi_ponderado"] = (0.6 * roi_norm + 0.4 * demanda_norm).round(4)

    df = df.sort_values("score_roi_ponderado", ascending=False)
    df["rank"] = range(1, len(df)+1)

    print(f"\n  Productos elegibles: {len(df):,}")
    print(f"\n  {'Categoría':<20} {'N':>5} "
          f"{'ROI_unit med':>13} {'ROI_esp med':>12} "
          f"{'Costo med':>10} {'Gan.esp med':>12}")
    print(f"  {'─'*76}")
    cat_sum = (df.groupby("category")
                 .agg(n=("roi_esperado_pct","count"),
                      roi_u=("roi_unitario_pct","median"),
                      roi_e=("roi_esperado_pct","median"),
                      costo=("price_import_real_base","median"),
                      gan=("ganancia_esperada","median"))
                 .sort_values("roi_e", ascending=False))
    for cat, r in cat_sum.iterrows():
        print(f"  {cat:<20} {r['n']:>5,.0f} "
              f"{r['roi_u']:>+12.1f}% {r['roi_e']:>+11.1f}% "
              f"${r['costo']:>9.0f} ${r['gan']:>11.0f}")

    print(f"\n  Top 10 productos:")
    print(f"  {'#':>3} {'Título':<40} {'Cat':<14} "
          f"{'Costo':>7} {'Venta':>7} {'ROI_u':>7} {'ROI_esp':>8}")
    print(f"  {'─'*90}")
    for _, r in df.head(10).iterrows():
        title = str(r.get("title_local",""))[:38] or str(r.get("title_import",""))[:38]
        print(f"  {r['rank']:>3} {title:<40} {r['category']:<14} "
              f"${r['price_import_real_base']:>6.0f} "
              f"${r['precio_venta_est']:>6.0f} "
              f"{r['roi_unitario_pct']:>+6.1f}% "
              f"{r['roi_esperado_pct']:>+7.1f}%")
    return df

def plot_roi(df: pd.DataFrame, perfil: str):
    if len(df) == 0:
        return
    cfg = PERFILES[perfil]
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    fig.patch.set_facecolor(DARK)
    fig.suptitle(
        f"OE4-A v3 — ROI Realista | Perfil: {cfg['label']}\n"
        f"({cfg['descripcion']})",
        color=WHITE, fontsize=13, fontweight="bold")

    ax = axes[0]; ax.set_facecolor(PANEL)
    ax.scatter(df["roi_unitario_pct"], df["roi_esperado_pct"],
               c=df["score_demanda"], cmap="RdYlGn",
               alpha=0.4, s=8, vmin=0.5, vmax=1.5)
    lim = max(df["roi_unitario_pct"].max(), df["roi_esperado_pct"].max()) * 1.05
    ax.plot([0,lim],[0,lim], color=WHITE, lw=1, ls="--", alpha=0.5)
    ax.axhline(cfg["margen_min_pct"], color=RED, lw=1.5, ls=":",
               label=f"Mínimo {cfg['margen_min_pct']:.0f}%")
    ax.set_xlabel("ROI Unitario %", color=WHITE)
    ax.set_ylabel("ROI Esperado %", color=WHITE)
    ax.set_title("ROI Unitario vs Esperado", color=WHITE)
    ax.tick_params(colors=WHITE); ax.spines[:].set_color(GRID)
    ax.grid(alpha=0.15, color=WHITE)
    ax.legend(facecolor=PANEL, labelcolor=WHITE, edgecolor=GRID, fontsize=8)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"{v:.0f}%"))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"{v:.0f}%"))

    ax2 = axes[1]; ax2.set_facecolor(PANEL)
    cats_top = (df.groupby("category")["roi_esperado_pct"]
                  .count().nlargest(8).index.tolist())
    data_box = [df[df["category"]==c]["roi_esperado_pct"].values for c in cats_top]
    bp = ax2.boxplot(data_box, patch_artist=True,
                     medianprops=dict(color=AMBER, lw=2))
    for patch in bp["boxes"]:
        patch.set_facecolor(CYAN); patch.set_alpha(0.5)
    ax2.set_xticklabels(cats_top, rotation=35, ha="right", color=WHITE, fontsize=8)
    ax2.set_ylabel("ROI Esperado %", color=WHITE)
    ax2.set_title("ROI Esperado por Categoría", color=WHITE)
    ax2.tick_params(colors=WHITE); ax2.spines[:].set_color(GRID)
    ax2.grid(axis="y", alpha=0.2, color=WHITE)
    ax2.axhline(cfg["margen_min_pct"], color=RED, lw=1.5, ls="--")
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"{v:.0f}%"))

    ax3 = axes[2]; ax3.set_facecolor(PANEL)
    top15 = df.head(15).copy()
    top15["label"] = top15.apply(lambda r: str(r.get("title_local",""))[:32], axis=1)
    y = np.arange(len(top15))
    ax3.barh(y, top15["roi_unitario_pct"].values, color=AMBER, alpha=0.5, label="ROI unitario")
    ax3.barh(y, top15["roi_esperado_pct"].values, color=GREEN, alpha=0.85, label="ROI esperado")
    ax3.set_yticks(y)
    ax3.set_yticklabels(top15["label"].values, color=WHITE, fontsize=7)
    ax3.set_xlabel("ROI %", color=WHITE)
    ax3.set_title("Top 15 — ROI Unitario vs Esperado", color=WHITE)
    ax3.tick_params(colors=WHITE); ax3.spines[:].set_color(GRID)
    ax3.grid(axis="x", alpha=0.2, color=WHITE)
    ax3.legend(facecolor=PANEL, labelcolor=WHITE, edgecolor=GRID, fontsize=8)
    ax3.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"{v:.0f}%"))

    plt.tight_layout()
    plt.savefig(f"figures/oe4a_fig1_roi_{perfil}.png",
                dpi=150, bbox_inches="tight", facecolor=DARK)
    plt.close()
    print(f"  ✓ figures/oe4a_fig1_roi_{perfil}.png")

def save(df: pd.DataFrame, perfil: str):
    cfg = PERFILES[perfil]
    out = f"results/oe4a_productos_roi_{perfil}.csv"
    df.to_csv(out, index=False)
    print(f"\n  ✓ {out} ({len(df):,} productos)")
    resumen = {
        "oe": "OE4-A", "version": "v3", "perfil": perfil,
        "timestamp": datetime.now().isoformat(),
        "config": {k: v for k, v in cfg.items() if k != "color"},
        "nota": (
            f"factor_venta={cfg['factor_venta']} "
            f"(precio_venta = price_local × {cfg['factor_venta']} − costo_op). "
            "ROI_esperado ajustado por rotación de stock."
        ),
        "totales": {
            "productos_elegibles"  : int(len(df)),
            "roi_unitario_med_pct" : round(float(df["roi_unitario_pct"].median()),2),
            "roi_esperado_med_pct" : round(float(df["roi_esperado_pct"].median()),2),
            "roi_unitario_max_pct" : round(float(df["roi_unitario_pct"].max()),2),
            "ganancia_esp_med_unit": round(float(df["ganancia_esperada"].median()),2),
            "costo_med_unit"       : round(float(df["price_import_real_base"].median()),2),
        },
        "por_categoria": (
            df.groupby("category")
              .agg(n=("roi_esperado_pct","count"),
                   roi_unit_med=("roi_unitario_pct","median"),
                   roi_esp_med=("roi_esperado_pct","median"),
                   roi_esp_max=("roi_esperado_pct","max"),
                   costo_med=("price_import_real_base","median"),
                   ganancia_esp_med=("ganancia_esperada","median"))
              .round(2).to_dict(orient="index")
        ),
    }
    jout = f"results/oe4a_resumen_roi_{perfil}.json"
    with open(jout,"w",encoding="utf-8") as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False)
    print(f"  ✓ {jout}")

if __name__ == "__main__":
    print("=" * 60)
    print("  OE4-A v3: Calculadora de ROI Realista")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print("""
FACTORES DEFINITIVOS (v3):
  conservador: ×0.65 venta, 85% rotación → ROI ~+20-50%
  moderado   : ×0.72 venta, 90% rotación → ROI ~+30-70%
  agresivo   : ×0.75 venta, 95% rotación → ROI ~+40-80%  ← corregido
    """)
    for perfil in ["conservador","moderado","agresivo"]:
        df = calcular_roi(perfil)
        if len(df) > 0:
            plot_roi(df, perfil)
            save(df, perfil)
    print("\n" + "="*60)
    print("  OE4-A v3 COMPLETADO")
    print("="*60)