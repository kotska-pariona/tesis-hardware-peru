"""
oe4c_sensitivity.py — OE4-C: Análisis de Sensibilidad del Portafolio
======================================================================
OBJETIVO:
  Evaluar la robustez del ROI del portafolio ante variaciones en los
  parámetros clave del modelo de precio de venta:
    1. factor_venta      : ±5%, ±10%, ±15%
    2. factor_rotacion   : ±5%, ±10%
    3. overhead_import   : ±10%, ±20%
    4. Escenario combinado adverso (todos los factores en su peor caso)
    5. Escenario combinado favorable (todos en su mejor caso)

METODOLOGÍA:
  - One-at-a-time (OAT) sensitivity analysis
  - Monte Carlo simulation (N=1000) para distribución de ROI
  - Tornado chart para identificar el factor más influyente
  - Análisis de break-even: ¿a qué factor_venta el ROI = 0%?

OUTPUTS:
  figures/oe4c_fig1_tornado_{perfil}.png
  figures/oe4c_fig2_montecarlo_{perfil}.png
  figures/oe4c_fig3_breakeven_{perfil}.png
  figures/oe4c_fig4_escenarios_comparados.png
  results/oe4c_sensibilidad_{perfil}.json
  results/oe4c_resumen_sensibilidad.csv
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
np.random.seed(42)

Path("results").mkdir(parents=True, exist_ok=True)
Path("figures").mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════════════════
# CONFIG BASE (igual que oe4a v3)
# ══════════════════════════════════════════════════════════════
BASE_CONFIG = {
    "conservador": {
        "factor_venta"    : 0.65,
        "factor_rotacion" : 0.85,
        "costo_operativo" : 0.05,
        "overhead_import" : 0.468,
        "label"           : "Conservador",
        "color"           : "#00ff88",
        "emoji"           : "🛡️",
        "portafolio_file" : "results/oe4b_portafolio_conservador_2000.csv",
        "inversion"       : 2000.0,
    },
    "moderado": {
        "factor_venta"    : 0.72,
        "factor_rotacion" : 0.90,
        "costo_operativo" : 0.04,
        "overhead_import" : 0.468,
        "label"           : "Moderado",
        "color"           : "#00d4ff",
        "emoji"           : "⚖️",
        "portafolio_file" : "results/oe4b_portafolio_moderado_5000.csv",
        "inversion"       : 5000.0,
    },
    "agresivo": {
        "factor_venta"    : 0.75,
        "factor_rotacion" : 0.95,
        "costo_operativo" : 0.03,
        "overhead_import" : 0.468,
        "label"           : "Agresivo",
        "color"           : "#ff4d6d",
        "emoji"           : "🚀",
        "portafolio_file" : "results/oe4b_portafolio_agresivo_10000.csv",
        "inversion"       : 10000.0,
    },
}

DARK  = '#0f0f1a'; PANEL = '#1a1a2e'; GRID = '#2a2a3e'
WHITE = '#e8e8f0'; CYAN  = '#00d4ff'; GREEN = '#00ff88'
AMBER = '#ffaa00'; RED   = '#ff4d6d'; PURPLE= '#c084fc'

# ══════════════════════════════════════════════════════════════
# 1. CALCULAR ROI DEL PORTAFOLIO DADO UN SET DE PARÁMETROS
# ══════════════════════════════════════════════════════════════
def calcular_roi_portafolio(
    df_port: pd.DataFrame,
    factor_venta: float,
    factor_rotacion: float,
    costo_operativo: float,
    overhead_import: float,
) -> dict:
    df = df_port.copy()

    overhead_base = 0.468
    df["costo_recalc"] = (
        df["costo_unit_usd"] / (1 + overhead_base) * (1 + overhead_import)
    ).round(4)

    df["precio_venta_recalc"] = (
        df["precio_venta_usd"] * factor_venta / 0.72
        * (1 - costo_operativo) / (1 - 0.04)
    ).round(4)

    df["ganancia_unit_recalc"] = (
        df["precio_venta_recalc"] - df["costo_recalc"]
    ).round(4)

    df["ganancia_esp_recalc"] = (
        df["ganancia_unit_recalc"] * factor_rotacion
        - df["costo_recalc"] * (1 - factor_rotacion)
    ).round(4)

    df["ganancia_total_recalc"] = (
        df["ganancia_esp_recalc"] * df["cantidad"]
    ).round(4)

    df["costo_total_recalc"] = (
        df["costo_recalc"] * df["cantidad"]
    ).round(4)

    capital_total  = df["costo_total_recalc"].sum()
    ganancia_total = df["ganancia_total_recalc"].sum()
    roi            = ganancia_total / capital_total * 100 if capital_total > 0 else 0

    return {
        "roi_pct"      : round(roi, 2),
        "ganancia_usd" : round(ganancia_total, 2),
        "capital_usd"  : round(capital_total, 2),
        "n_positivos"  : int((df["ganancia_esp_recalc"] > 0).sum()),
        "n_negativos"  : int((df["ganancia_esp_recalc"] <= 0).sum()),
    }

# ══════════════════════════════════════════════════════════════
# 2. ANÁLISIS OAT (One-At-a-Time)
# ══════════════════════════════════════════════════════════════
def analisis_oat(df_port: pd.DataFrame, cfg: dict, perfil: str):
    base_roi = calcular_roi_portafolio(
        df_port,
        cfg["factor_venta"], cfg["factor_rotacion"],
        cfg["costo_operativo"], cfg["overhead_import"],
    )["roi_pct"]

    variaciones = {
        "factor_venta": [
            ("−15%", cfg["factor_venta"] * 0.85),
            ("−10%", cfg["factor_venta"] * 0.90),
            ("−5%",  cfg["factor_venta"] * 0.95),
            ("base", cfg["factor_venta"]),
            ("+5%",  cfg["factor_venta"] * 1.05),
            ("+10%", cfg["factor_venta"] * 1.10),
            ("+15%", cfg["factor_venta"] * 1.15),
        ],
        "factor_rotacion": [
            ("−10%", max(0.50, cfg["factor_rotacion"] - 0.10)),
            ("−5%",  max(0.50, cfg["factor_rotacion"] - 0.05)),
            ("base", cfg["factor_rotacion"]),
            ("+5%",  min(1.00, cfg["factor_rotacion"] + 0.05)),
            ("+10%", min(1.00, cfg["factor_rotacion"] + 0.10)),
        ],
        "overhead_import": [
            ("+20%", cfg["overhead_import"] * 1.20),
            ("+10%", cfg["overhead_import"] * 1.10),
            ("base", cfg["overhead_import"]),
            ("−10%", cfg["overhead_import"] * 0.90),
            ("−20%", cfg["overhead_import"] * 0.80),
        ],
        "costo_operativo": [
            ("+50%", cfg["costo_operativo"] * 1.50),
            ("+25%", cfg["costo_operativo"] * 1.25),
            ("base", cfg["costo_operativo"]),
            ("−25%", cfg["costo_operativo"] * 0.75),
            ("−50%", cfg["costo_operativo"] * 0.50),
        ],
    }

    resultados = []
    for param, vals in variaciones.items():
        for label, val in vals:
            kwargs = {
                "factor_venta"    : cfg["factor_venta"],
                "factor_rotacion" : cfg["factor_rotacion"],
                "costo_operativo" : cfg["costo_operativo"],
                "overhead_import" : cfg["overhead_import"],
            }
            kwargs[param] = val
            res = calcular_roi_portafolio(df_port, **kwargs)
            resultados.append({
                "parametro" : param,
                "variacion" : label,
                "valor"     : round(val, 4),
                "roi_pct"   : res["roi_pct"],
                "delta_roi" : round(res["roi_pct"] - base_roi, 2),
                "es_base"   : label == "base",
            })

    return pd.DataFrame(resultados), base_roi

# ══════════════════════════════════════════════════════════════
# 3. MONTE CARLO  ← FIX: size=n_sim en beta
# ══════════════════════════════════════════════════════════════
def monte_carlo(df_port: pd.DataFrame, cfg: dict,
                n_sim: int = 1000) -> np.ndarray:
    fv_base = cfg["factor_venta"]
    fr_base = cfg["factor_rotacion"]
    oh_base = cfg["overhead_import"]
    co_base = cfg["costo_operativo"]

    fv_sim = np.clip(np.random.normal(fv_base, fv_base * 0.08, n_sim), 0.45, 0.95)
    # ▼ FIX: size=n_sim  (antes faltaba → devolvía escalar)
    fr_sim = np.clip(np.random.beta(8, 2, size=n_sim) * 0.40 + 0.60, 0.60, 1.00)
    oh_sim = np.clip(np.random.normal(oh_base, oh_base * 0.15, n_sim), 0.20, 1.00)
    co_sim = np.random.uniform(co_base * 0.5, co_base * 1.5, n_sim)

    rois = np.zeros(n_sim)
    for i in range(n_sim):
        res = calcular_roi_portafolio(
            df_port, fv_sim[i], fr_sim[i], co_sim[i], oh_sim[i])
        rois[i] = res["roi_pct"]

    return rois

# ══════════════════════════════════════════════════════════════
# 4. BREAK-EVEN
# ══════════════════════════════════════════════════════════════
def breakeven_factor_venta(df_port: pd.DataFrame, cfg: dict) -> dict:
    fv_range = np.linspace(0.30, 1.00, 200)
    rois = []
    for fv in fv_range:
        res = calcular_roi_portafolio(
            df_port, fv,
            cfg["factor_rotacion"],
            cfg["costo_operativo"],
            cfg["overhead_import"],
        )
        rois.append(res["roi_pct"])

    rois = np.array(rois)

    be_0 = None
    for i in range(len(rois) - 1):
        if rois[i] < 0 and rois[i+1] >= 0:
            be_0 = fv_range[i] + (fv_range[i+1] - fv_range[i]) * (
                -rois[i] / (rois[i+1] - rois[i]))
            break

    be_10 = None
    for i in range(len(rois) - 1):
        if rois[i] < 10 and rois[i+1] >= 10:
            be_10 = fv_range[i] + (fv_range[i+1] - fv_range[i]) * (
                (10 - rois[i]) / (rois[i+1] - rois[i]))
            break

    return {
        "fv_range" : fv_range,
        "rois"     : rois,
        "be_0"     : round(be_0, 3) if be_0 else None,
        "be_10"    : round(be_10, 3) if be_10 else None,
        "fv_base"  : cfg["factor_venta"],
        "roi_base" : float(rois[np.argmin(np.abs(fv_range - cfg["factor_venta"]))]),
    }

# ══════════════════════════════════════════════════════════════
# 5. VISUALIZACIONES
# ══════════════════════════════════════════════════════════════
def plot_tornado(df_oat: pd.DataFrame, base_roi: float,
                 cfg: dict, perfil: str):
    fig, ax = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor(DARK); ax.set_facecolor(PANEL)

    params = df_oat[~df_oat["es_base"]]["parametro"].unique()
    rangos = []
    for p in params:
        sub = df_oat[(df_oat["parametro"] == p) & (~df_oat["es_base"])]
        roi_min = sub["roi_pct"].min()
        roi_max = sub["roi_pct"].max()
        rangos.append((p, roi_min, roi_max, roi_max - roi_min))

    rangos.sort(key=lambda x: x[3], reverse=True)

    labels_map = {
        "factor_venta"    : "Factor de venta\n(precio vs lista local)",
        "factor_rotacion" : "Tasa de rotación\n(% stock vendido)",
        "overhead_import" : "Overhead importación\n(costo real vs FOB)",
        "costo_operativo" : "Costo operativo\n(plataforma + tiempo)",
    }

    y_pos = np.arange(len(rangos))
    for i, (p, rmin, rmax, rango) in enumerate(rangos):
        ax.barh(i, rmin - base_roi, left=base_roi,
                color=RED,   alpha=0.85, height=0.55)
        ax.barh(i, rmax - base_roi, left=base_roi,
                color=GREEN, alpha=0.85, height=0.55)
        ax.text(rmin - 0.5, i, f"{rmin:+.1f}%",
                va="center", ha="right", color=WHITE, fontsize=8)
        ax.text(rmax + 0.5, i, f"{rmax:+.1f}%",
                va="center", ha="left",  color=WHITE, fontsize=8)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(
        [labels_map.get(p, p) for p, *_ in rangos],
        color=WHITE, fontsize=9)
    ax.axvline(base_roi, color=AMBER, lw=2, ls="--",
               label=f"ROI base: {base_roi:+.1f}%")
    ax.axvline(0, color=WHITE, lw=1, ls=":", alpha=0.5)
    ax.set_xlabel("ROI del Portafolio (%)", color=WHITE)
    ax.set_title(
        f"Tornado Chart — Sensibilidad del ROI | {cfg['label']}\n"
        f"ROI base: {base_roi:+.1f}% | "
        f"Factor más influyente: {labels_map.get(rangos[0][0], rangos[0][0]).split(chr(10))[0]}",
        color=WHITE, fontsize=11)
    ax.tick_params(colors=WHITE); ax.spines[:].set_color(GRID)
    ax.grid(axis="x", alpha=0.2, color=WHITE)
    ax.legend(facecolor=PANEL, labelcolor=WHITE, edgecolor=GRID)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))

    plt.tight_layout()
    fname = f"figures/oe4c_fig1_tornado_{perfil}.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight", facecolor=DARK)
    plt.close()
    print(f"  ✓ {fname}")

def plot_montecarlo(rois_mc: np.ndarray, base_roi: float,
                    cfg: dict, perfil: str):
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.patch.set_facecolor(DARK)
    fig.suptitle(
        f"Monte Carlo (N=1,000) — Distribución de ROI | {cfg['label']}",
        color=WHITE, fontsize=12, fontweight="bold")

    ax = axes[0]; ax.set_facecolor(PANEL)
    n_pos = (rois_mc > 0).sum()
    n_neg = (rois_mc <= 0).sum()
    ax.hist(rois_mc[rois_mc > 0],  bins=40, color=GREEN, alpha=0.7,
            label=f"ROI > 0% ({n_pos / len(rois_mc) * 100:.1f}%)")
    ax.hist(rois_mc[rois_mc <= 0], bins=10, color=RED,   alpha=0.7,
            label=f"ROI ≤ 0% ({n_neg / len(rois_mc) * 100:.1f}%)")
    ax.axvline(base_roi,                    color=AMBER, lw=2.5, ls="--",
               label=f"ROI base: {base_roi:+.1f}%")
    ax.axvline(np.percentile(rois_mc,  5),  color=RED,   lw=1.5, ls=":",
               label=f"P5: {np.percentile(rois_mc, 5):+.1f}%")
    ax.axvline(np.percentile(rois_mc, 95),  color=GREEN, lw=1.5, ls=":",
               label=f"P95: {np.percentile(rois_mc, 95):+.1f}%")
    ax.axvline(0, color=WHITE, lw=1, ls="-", alpha=0.4)
    ax.set_xlabel("ROI del Portafolio (%)", color=WHITE)
    ax.set_ylabel("Frecuencia", color=WHITE)
    ax.set_title("Distribución de ROI (1,000 simulaciones)", color=WHITE)
    ax.tick_params(colors=WHITE); ax.spines[:].set_color(GRID)
    ax.grid(alpha=0.15, color=WHITE)
    ax.legend(facecolor=PANEL, labelcolor=WHITE, edgecolor=GRID, fontsize=8)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))

    ax2 = axes[1]; ax2.set_facecolor(PANEL)
    ax2.boxplot(rois_mc, vert=True, patch_artist=True,
                medianprops=dict(color=AMBER, lw=2.5),
                boxprops=dict(facecolor=CYAN, alpha=0.4),
                whiskerprops=dict(color=WHITE),
                capprops=dict(color=WHITE),
                flierprops=dict(marker="o", color=RED, alpha=0.3, markersize=3))
    ax2.axhline(0,        color=WHITE, lw=1,   ls=":", alpha=0.5)
    ax2.axhline(base_roi, color=AMBER, lw=2,   ls="--")
    ax2.set_xticklabels([cfg["label"]], color=WHITE)
    ax2.set_ylabel("ROI (%)", color=WHITE)
    ax2.set_title("Boxplot + Estadísticas", color=WHITE)
    ax2.tick_params(colors=WHITE); ax2.spines[:].set_color(GRID)
    ax2.grid(axis="y", alpha=0.2, color=WHITE)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))

    stats = [
        ("Media",     f"{np.mean(rois_mc):+.1f}%"),
        ("Mediana",   f"{np.median(rois_mc):+.1f}%"),
        ("Std Dev",   f"{np.std(rois_mc):.1f}pp"),
        ("P5",        f"{np.percentile(rois_mc,  5):+.1f}%"),
        ("P25",       f"{np.percentile(rois_mc, 25):+.1f}%"),
        ("P75",       f"{np.percentile(rois_mc, 75):+.1f}%"),
        ("P95",       f"{np.percentile(rois_mc, 95):+.1f}%"),
        ("Prob(>0%)", f"{(rois_mc > 0).mean() * 100:.1f}%"),
        ("Prob(>20%)",f"{(rois_mc > 20).mean() * 100:.1f}%"),
        ("ROI base",  f"{base_roi:+.1f}%"),
    ]
    y_t = 0.97
    for label, val in stats:
        color_v = GREEN if "Prob" in label or "Media" in label else WHITE
        ax2.text(1.35, y_t, label, transform=ax2.transAxes,
                 color=WHITE, fontsize=8.5, va="top")
        ax2.text(1.85, y_t, val,   transform=ax2.transAxes,
                 color=color_v, fontsize=8.5, va="top", ha="right",
                 fontweight="bold")
        y_t -= 0.09

    plt.tight_layout()
    fname = f"figures/oe4c_fig2_montecarlo_{perfil}.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight", facecolor=DARK)
    plt.close()
    print(f"  ✓ {fname}")

def plot_breakeven(be: dict, cfg: dict, perfil: str):
    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor(DARK); ax.set_facecolor(PANEL)

    ax.fill_between(be["fv_range"], be["rois"], 0,
                    where=be["rois"] >= 0,
                    color=GREEN, alpha=0.15, label="Zona de ganancia")
    ax.fill_between(be["fv_range"], be["rois"], 0,
                    where=be["rois"] < 0,
                    color=RED,   alpha=0.20, label="Zona de pérdida")
    ax.plot(be["fv_range"], be["rois"],
            color=cfg["color"], lw=2.5, label="ROI vs factor_venta")
    ax.axhline(0,  color=WHITE, lw=1.5, ls="--", alpha=0.6,
               label="Break-even ROI=0%")
    ax.axhline(10, color=AMBER, lw=1.5, ls=":",  alpha=0.8,
               label="ROI mínimo 10%")
    ax.axvline(be["fv_base"], color=cfg["color"], lw=2, ls="--",
               label=f"Factor base: {be['fv_base']:.2f} → ROI {be['roi_base']:+.1f}%")

    if be["be_0"]:
        ax.axvline(be["be_0"], color=RED, lw=1.5, ls=":",
                   label=f"Break-even 0%: fv={be['be_0']:.2f} "
                         f"(−{(be['fv_base'] - be['be_0']) / be['fv_base'] * 100:.0f}% del base)")
    if be["be_10"]:
        ax.axvline(be["be_10"], color=AMBER, lw=1.5, ls=":",
                   label=f"Break-even 10%: fv={be['be_10']:.2f}")

    ax.set_xlabel("Factor de Venta (precio_venta / precio_lista_local)", color=WHITE)
    ax.set_ylabel("ROI del Portafolio (%)", color=WHITE)
    ax.set_title(
        f"Análisis Break-Even — {cfg['label']}\n"
        f"Factor base: {be['fv_base']:.2f} | ROI base: {be['roi_base']:+.1f}%",
        color=WHITE, fontsize=11)
    ax.tick_params(colors=WHITE); ax.spines[:].set_color(GRID)
    ax.grid(alpha=0.15, color=WHITE)
    ax.legend(facecolor=PANEL, labelcolor=WHITE, edgecolor=GRID, fontsize=8)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.2f}"))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.set_xlim(0.30, 1.00)

    plt.tight_layout()
    fname = f"figures/oe4c_fig3_breakeven_{perfil}.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight", facecolor=DARK)
    plt.close()
    print(f"  ✓ {fname}")

def plot_escenarios_comparados(resultados_todos: dict):
    escenarios = [
        ("Adverso extremo",    {"factor_venta": -0.15, "factor_rotacion": -0.10,
                                 "overhead_import": +0.20}, RED),
        ("Adverso moderado",   {"factor_venta": -0.08, "factor_rotacion": -0.05,
                                 "overhead_import": +0.10}, AMBER),
        ("Base",               {}, CYAN),
        ("Favorable moderado", {"factor_venta": +0.05, "factor_rotacion": +0.05,
                                 "overhead_import": -0.10}, "#90ee90"),
        ("Favorable extremo",  {"factor_venta": +0.10, "factor_rotacion": +0.10,
                                 "overhead_import": -0.20}, GREEN),
    ]

    fig, ax = plt.subplots(figsize=(14, 6))
    fig.patch.set_facecolor(DARK); ax.set_facecolor(PANEL)

    perfiles = ["conservador", "moderado", "agresivo"]
    x        = np.arange(len(perfiles))
    offsets  = np.linspace(-0.30, 0.30, len(escenarios))
    width    = 0.15

    for j, (esc_label, deltas, color) in enumerate(escenarios):
        rois_esc = []
        for perfil in perfiles:
            cfg   = BASE_CONFIG[perfil]
            df_p  = resultados_todos[perfil]["df_port"]
            fv = cfg["factor_venta"]    * (1 + deltas.get("factor_venta", 0))
            fr = min(1.0, cfg["factor_rotacion"]  * (1 + deltas.get("factor_rotacion", 0)))
            oh = cfg["overhead_import"] * (1 + deltas.get("overhead_import", 0))
            co = cfg["costo_operativo"]
            res = calcular_roi_portafolio(df_p, fv, fr, co, oh)
            rois_esc.append(res["roi_pct"])

        bars = ax.bar(x + offsets[j], rois_esc, width,
                      label=esc_label, color=color, alpha=0.85)
        for bar, roi in zip(bars, rois_esc):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.5,
                    f"{roi:+.0f}%",
                    ha="center", va="bottom", color=WHITE, fontsize=7)

    ax.axhline(0, color=WHITE, lw=1, ls="--", alpha=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(
        [f"{BASE_CONFIG[p]['emoji']} {BASE_CONFIG[p]['label']}" for p in perfiles],
        color=WHITE, fontsize=10)
    ax.set_ylabel("ROI del Portafolio (%)", color=WHITE)
    ax.set_title(
        "Comparación de Escenarios — 3 Perfiles × 5 Escenarios\n"
        "(Adverso extremo → Base → Favorable extremo)",
        color=WHITE, fontsize=12)
    ax.tick_params(colors=WHITE); ax.spines[:].set_color(GRID)
    ax.grid(axis="y", alpha=0.2, color=WHITE)
    ax.legend(facecolor=PANEL, labelcolor=WHITE, edgecolor=GRID,
              fontsize=8, loc="upper left")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))

    plt.tight_layout()
    fname = "figures/oe4c_fig4_escenarios_comparados.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight", facecolor=DARK)
    plt.close()
    print(f"  ✓ {fname}")

# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 64)
    print("  OE4-C: Análisis de Sensibilidad del Portafolio")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 64)

    resultados_todos = {}
    resumen_rows     = []

    for perfil in ["conservador", "moderado", "agresivo"]:
        cfg = BASE_CONFIG[perfil]
        print(f"\n{'─'*64}")
        print(f"  {cfg['emoji']}  PERFIL: {cfg['label'].upper()}")
        print(f"{'─'*64}")

        fp = Path(cfg["portafolio_file"])
        if not fp.exists():
            print(f"  ⚠ No encontrado: {fp}")
            print(f"     Ejecuta: python scripts/oe4b_optimizer.py "
                  f"--inversion {int(cfg['inversion'])} --perfil {perfil}")
            continue

        df_port = pd.read_csv(fp)
        print(f"  Portafolio cargado: {len(df_port)} SKUs, "
              f"{df_port['cantidad'].sum()} unidades")

        base_res = calcular_roi_portafolio(
            df_port, cfg["factor_venta"], cfg["factor_rotacion"],
            cfg["costo_operativo"], cfg["overhead_import"])
        base_roi = base_res["roi_pct"]
        print(f"  ROI base recalculado: {base_roi:+.1f}%")

        # OAT
        print(f"\n  Análisis OAT...")
        df_oat, _ = analisis_oat(df_port, cfg, perfil)
        plot_tornado(df_oat, base_roi, cfg, perfil)
        for param in df_oat["parametro"].unique():
            sub  = df_oat[(df_oat["parametro"] == param) & (~df_oat["es_base"])]
            rmin = sub["roi_pct"].min()
            rmax = sub["roi_pct"].max()
            print(f"    {param:<22}: ROI [{rmin:+.1f}%, {rmax:+.1f}%]  "
                  f"rango={rmax - rmin:.1f}pp")

        # Monte Carlo
        print(f"\n  Monte Carlo (N=1,000)...")
        rois_mc = monte_carlo(df_port, cfg, n_sim=1000)
        plot_montecarlo(rois_mc, base_roi, cfg, perfil)
        prob_pos = (rois_mc > 0).mean()  * 100
        prob_20  = (rois_mc > 20).mean() * 100
        p5, p95  = np.percentile(rois_mc, [5, 95])
        print(f"    Media: {np.mean(rois_mc):+.1f}% | "
              f"Std: {np.std(rois_mc):.1f}pp | "
              f"P5-P95: [{p5:+.1f}%, {p95:+.1f}%]")
        print(f"    Prob(ROI>0%): {prob_pos:.1f}% | "
              f"Prob(ROI>20%): {prob_20:.1f}%")

        # Break-even
        print(f"\n  Análisis Break-Even...")
        be = breakeven_factor_venta(df_port, cfg)
        plot_breakeven(be, cfg, perfil)
        if be["be_0"]:
            margen = (cfg["factor_venta"] - be["be_0"]) / cfg["factor_venta"] * 100
            print(f"    Break-even ROI=0%  : fv={be['be_0']:.3f} "
                  f"(−{margen:.1f}% del factor base)")
        if be["be_10"]:
            margen10 = (cfg["factor_venta"] - be["be_10"]) / cfg["factor_venta"] * 100
            print(f"    Break-even ROI=10% : fv={be['be_10']:.3f} "
                  f"(−{margen10:.1f}% del factor base)")

        # JSON
        factor_mas_sensible = (
            df_oat[~df_oat["es_base"]]
            .groupby("parametro")["delta_roi"]
            .apply(lambda x: x.abs().max())
            .idxmax()
        )
        resumen_json = {
            "perfil"              : perfil,
            "roi_base_pct"        : base_roi,
            "factor_mas_sensible" : factor_mas_sensible,
            "montecarlo": {
                "n_sim"            : 1000,
                "media_pct"        : round(float(np.mean(rois_mc)), 2),
                "std_pp"           : round(float(np.std(rois_mc)), 2),
                "p5_pct"           : round(float(p5), 2),
                "p95_pct"          : round(float(p95), 2),
                "prob_roi_pos_pct" : round(float(prob_pos), 2),
                "prob_roi_20_pct"  : round(float(prob_20), 2),
            },
            "breakeven": {
                "fv_roi_0"              : be["be_0"],
                "fv_roi_10"             : be["be_10"],
                "margen_seguridad_pct"  : round(
                    (cfg["factor_venta"] - be["be_0"]) /
                    cfg["factor_venta"] * 100, 1) if be["be_0"] else None,
            },
            "oat_rangos": {
                p: {
                    "roi_min"  : round(float(df_oat[df_oat["parametro"] == p]["roi_pct"].min()), 2),
                    "roi_max"  : round(float(df_oat[df_oat["parametro"] == p]["roi_pct"].max()), 2),
                    "rango_pp" : round(float(
                        df_oat[df_oat["parametro"] == p]["roi_pct"].max() -
                        df_oat[df_oat["parametro"] == p]["roi_pct"].min()), 2),
                }
                for p in df_oat["parametro"].unique()
            },
        }
        jout = f"results/oe4c_sensibilidad_{perfil}.json"
        with open(jout, "w", encoding="utf-8") as f:
            json.dump(resumen_json, f, indent=2, ensure_ascii=False)
        print(f"\n  ✓ {jout}")

        resultados_todos[perfil] = {
            "df_port" : df_port,
            "base_roi": base_roi,
            "mc_rois" : rois_mc,
            "be"      : be,
        }
        resumen_rows.append({
            "perfil"                : perfil,
            "roi_base_pct"          : base_roi,
            "mc_media_pct"          : round(float(np.mean(rois_mc)), 2),
            "mc_std_pp"             : round(float(np.std(rois_mc)), 2),
            "mc_p5_pct"             : round(float(p5), 2),
            "mc_p95_pct"            : round(float(p95), 2),
            "prob_roi_positivo_pct" : round(float(prob_pos), 2),
            "prob_roi_mayor20_pct"  : round(float(prob_20), 2),
            "be_fv_roi0"            : be["be_0"],
            "be_fv_roi10"           : be["be_10"],
            "factor_mas_sensible"   : factor_mas_sensible,
        })

    # Figura comparada
    if len(resultados_todos) == 3:
        print(f"\n{'─'*64}")
        print("  Generando comparación 3 perfiles × 5 escenarios...")
        plot_escenarios_comparados(resultados_todos)

    # CSV resumen
    if resumen_rows:
        pd.DataFrame(resumen_rows).to_csv(
            "results/oe4c_resumen_sensibilidad.csv", index=False)
        print("  ✓ results/oe4c_resumen_sensibilidad.csv")

    print("\n" + "=" * 64)
    print("  OE4-C COMPLETADO")
    print("=" * 64)
    print("""
Outputs generados:
  figures/oe4c_fig1_tornado_{perfil}.png      ← factor más influyente
  figures/oe4c_fig2_montecarlo_{perfil}.png   ← distribución de ROI
  figures/oe4c_fig3_breakeven_{perfil}.png    ← punto de quiebre
  figures/oe4c_fig4_escenarios_comparados.png ← resumen ejecutivo

Siguiente paso:
  python scripts/oe5_nsga3.py
    """)