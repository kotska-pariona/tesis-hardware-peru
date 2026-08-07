"""
Genera las 4 figuras del paper HDS-ROI para publicación
Output: figures/paper_fig{1,2,3,4}.png  (300 DPI, estilo IEEE)
"""
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path

OUT = Path("figures")
OUT.mkdir(exist_ok=True)

# Estilo IEEE/Elsevier
plt.rcParams.update({
    "font.family":      "serif",
    "font.size":        10,
    "axes.titlesize":   11,
    "axes.labelsize":   10,
    "xtick.labelsize":  9,
    "ytick.labelsize":  9,
    "legend.fontsize":  9,
    "figure.dpi":       150,
    "axes.grid":        True,
    "grid.alpha":       0.3,
    "axes.spines.top":  False,
    "axes.spines.right":False,
})

COLORS = ["#2196F3","#4CAF50","#FF9800","#E91E63","#9C27B0"]

# ─────────────────────────────────────────────────────────────
# FIG 1 — Ablación de Features
# ─────────────────────────────────────────────────────────────
def fig1_ablacion():
    with open("results/exp1_ablacion_features.json") as f:
        data = json.load(f)

    labels   = ["F5\n(Lags only)", "F10\n(+Temporal)", "F15\n(+SKU stats)", "F21\n(Full)"]
    mapes    = [data[k]["mape_test"]   for k in ["F5_lag_only","F10_temporal","F15_sku","F21_full"]]
    r2s      = [data[k]["r2_test"]     for k in ["F5_lag_only","F10_temporal","F15_sku","F21_full"]]
    n_feats  = [data[k]["n_features"]  for k in ["F5_lag_only","F10_temporal","F15_sku","F21_full"]]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8, 3.5))

    # MAPE
    bars = ax1.bar(labels, mapes, color=COLORS[:4], width=0.5, edgecolor="white", linewidth=0.8)
    ax1.axhline(2.0, color="red", linestyle="--", linewidth=1, label="Thesis target (2%)")
    ax1.set_ylabel("MAPE test (%)")
    ax1.set_title("(a) Feature Ablation — MAPE")
    ax1.legend(fontsize=8)
    for bar, v in zip(bars, mapes):
        ax1.text(bar.get_x() + bar.get_width()/2, v + 0.02,
                 f"{v:.4f}%", ha="center", va="bottom", fontsize=8, fontweight="bold")

    # R²
    bars2 = ax2.bar(labels, r2s, color=COLORS[:4], width=0.5, edgecolor="white", linewidth=0.8)
    ax2.axhline(0.85, color="red", linestyle="--", linewidth=1, label="Thesis target (0.85)")
    ax2.set_ylabel("R² test")
    ax2.set_title("(b) Feature Ablation — R²")
    ax2.set_ylim([0.994, 1.0005])
    ax2.legend(fontsize=8)
    for bar, v in zip(bars2, r2s):
        ax2.text(bar.get_x() + bar.get_width()/2, v + 0.00005,
                 f"{v:.6f}", ha="center", va="bottom", fontsize=7, fontweight="bold")

    plt.tight_layout()
    plt.savefig(OUT / "paper_fig1_ablacion.png", dpi=300, bbox_inches="tight")
    plt.close()
    print("  ✅ paper_fig1_ablacion.png")

# ─────────────────────────────────────────────────────────────
# FIG 2 — Sensibilidad r_j
# ─────────────────────────────────────────────────────────────
def fig2_rj():
    with open("results/exp2_sensibilidad_rj.json") as f:
        data = json.load(f)

    rjs      = [float(k) for k in data]
    n_sols   = [data[k]["n_soluciones"] for k in data]
    roi_max  = [data[k]["roi_max"]      for k in data]
    roi_mean = [data[k]["roi_mean"]     for k in data]
    roi_min  = [data[k]["roi_min"]      for k in data]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8, 3.5))

    # Nº soluciones vs r_j
    ax1.plot(rjs, n_sols, "o-", color=COLORS[0], linewidth=2, markersize=7)
    ax1.axvline(0.5, color="red", linestyle="--", linewidth=1.2, label="Chosen $r_j$=0.5")
    ax1.fill_between(rjs, n_sols, alpha=0.15, color=COLORS[0])
    ax1.set_xlabel("$r_j$ threshold")
    ax1.set_ylabel("Pareto front size")
    ax1.set_title("(a) Pareto Solutions vs $r_j$")
    ax1.legend()
    for x, y in zip(rjs, n_sols):
        ax1.annotate(str(y), (x, y), textcoords="offset points",
                     xytext=(0, 8), ha="center", fontsize=9)

    # ROI range vs r_j
    ax2.fill_between(rjs, roi_min, roi_max, alpha=0.2, color=COLORS[1], label="ROI range")
    ax2.plot(rjs, roi_mean, "s-", color=COLORS[1], linewidth=2, markersize=7, label="ROI mean")
    ax2.plot(rjs, roi_max,  "^--", color=COLORS[2], linewidth=1.2, markersize=5, label="ROI max")
    ax2.axvline(0.5, color="red", linestyle="--", linewidth=1.2, label="Chosen $r_j$=0.5")
    ax2.set_xlabel("$r_j$ threshold")
    ax2.set_ylabel("ROI (%)")
    ax2.set_title("(b) ROI Distribution vs $r_j$")
    ax2.legend(fontsize=8)

    plt.tight_layout()
    plt.savefig(OUT / "paper_fig2_sensibilidad_rj.png", dpi=300, bbox_inches="tight")
    plt.close()
    print("  ✅ paper_fig2_sensibilidad_rj.png")

# ─────────────────────────────────────────────────────────────
# FIG 3 — Escalabilidad temporal
# ─────────────────────────────────────────────────────────────
def fig3_escalabilidad():
    with open("results/exp3_escalabilidad.json") as f:
        data = json.load(f)

    dias  = [data[k]["dias"]   for k in data]
    mapes = [data[k]["mape"]   for k in data]
    r2s   = [data[k]["r2"]     for k in data]
    filas = [data[k]["n_filas"]/1000 for k in data]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8, 3.5))

    # MAPE vs días
    ax1.plot(dias, mapes, "o-", color=COLORS[0], linewidth=2, markersize=7)
    # Marcar mínimo
    idx_min = mapes.index(min(mapes))
    ax1.scatter([dias[idx_min]], [mapes[idx_min]], color="red", s=100, zorder=5,
                label=f"Min MAPE={min(mapes):.4f}% @ {dias[idx_min]}d")
    ax1.axhline(2.0, color="red", linestyle="--", linewidth=1, alpha=0.5, label="Target 2%")
    ax1.set_xlabel("History window (days)")
    ax1.set_ylabel("MAPE test (%)")
    ax1.set_title("(a) MAPE vs History Window")
    ax1.legend(fontsize=8)

    # Filas disponibles vs días
    ax2b = ax2.twinx()
    l1, = ax2.plot(dias, mapes, "o-", color=COLORS[0], linewidth=2, markersize=6, label="MAPE (%)")
    l2, = ax2b.plot(dias, filas, "s--", color=COLORS[2], linewidth=1.5, markersize=6, label="Records (K)")
    ax2.set_xlabel("History window (days)")
    ax2.set_ylabel("MAPE (%)", color=COLORS[0])
    ax2b.set_ylabel("Records (thousands)", color=COLORS[2])
    ax2.set_title("(b) MAPE & Data Volume vs Window")
    lines = [l1, l2]
    ax2.legend(lines, [l.get_label() for l in lines], fontsize=8)

    plt.tight_layout()
    plt.savefig(OUT / "paper_fig3_escalabilidad.png", dpi=300, bbox_inches="tight")
    plt.close()
    print("  ✅ paper_fig3_escalabilidad.png")

# ─────────────────────────────────────────────────────────────
# FIG 4 — Mondrian CP vs Bootstrap
# ─────────────────────────────────────────────────────────────
def fig4_mcp():
    with open("results/exp4_mcp_vs_bootstrap.json") as f:
        data = json.load(f)

    mcp  = data["mondrian_cp"]
    boot = data["bootstrap_ci"]

    estratos_common = [e for e in mcp if e in boot]
    labels   = [e.replace("_", "\n") for e in estratos_common]
    mcp_cov  = [mcp[e]["cobertura"]   for e in estratos_common]
    boot_cov = [boot[e]["cobertura"]  for e in estratos_common]
    mcp_w    = [mcp[e]["ancho_medio"] for e in estratos_common]
    boot_w   = [boot[e]["ancho_medio"]for e in estratos_common]

    x = np.arange(len(labels))
    w = 0.35

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9, 3.8))

    # Cobertura
    b1 = ax1.bar(x - w/2, mcp_cov,  w, label="Mondrian CP", color=COLORS[0],
                 edgecolor="white", linewidth=0.8)
    b2 = ax1.bar(x + w/2, boot_cov, w, label="Bootstrap CI", color=COLORS[2],
                 edgecolor="white", linewidth=0.8)
    ax1.axhline(95, color="red", linestyle="--", linewidth=1.2, label="Target 95%")
    ax1.set_xticks(x); ax1.set_xticklabels(labels, fontsize=8)
    ax1.set_ylabel("Empirical Coverage (%)")
    ax1.set_title("(a) Coverage by Price Stratum")
    ax1.set_ylim([0, 105])
    ax1.legend(fontsize=8)
    for bar, v in zip(b1, mcp_cov):
        ax1.text(bar.get_x()+bar.get_width()/2, v+0.5,
                 f"{v:.1f}%", ha="center", va="bottom", fontsize=7.5, fontweight="bold",
                 color=COLORS[0])
    for bar, v in zip(b2, boot_cov):
        col = "red" if v < 50 else COLORS[2]
        ax1.text(bar.get_x()+bar.get_width()/2, v+0.5,
                 f"{v:.1f}%", ha="center", va="bottom", fontsize=7.5, fontweight="bold",
                 color=col)

    # Ancho de intervalo
    b3 = ax2.bar(x - w/2, mcp_w,  w, label="Mondrian CP", color=COLORS[0],
                 edgecolor="white", linewidth=0.8)
    b4 = ax2.bar(x + w/2, boot_w, w, label="Bootstrap CI", color=COLORS[2],
                 edgecolor="white", linewidth=0.8)
    ax2.set_xticks(x); ax2.set_xticklabels(labels, fontsize=8)
    ax2.set_ylabel("Mean Interval Width (PEN)")
    ax2.set_title("(b) Interval Width by Price Stratum")
    ax2.legend(fontsize=8)
    ax2.set_yscale("log")

    plt.tight_layout()
    plt.savefig(OUT / "paper_fig4_mcp_bootstrap.png", dpi=300, bbox_inches="tight")
    plt.close()
    print("  ✅ paper_fig4_mcp_bootstrap.png")

# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("  Generando figuras del paper HDS-ROI (300 DPI)")
    print("=" * 55)
    fig1_ablacion()
    fig2_rj()
    fig3_escalabilidad()
    fig4_mcp()
    print("\n  ✅ 4 figuras guardadas en figures/")
    print("  paper_fig1_ablacion.png")
    print("  paper_fig2_sensibilidad_rj.png")
    print("  paper_fig3_escalabilidad.png")
    print("  paper_fig4_mcp_bootstrap.png")
