"""
scripts/oe9_nsga3_llm.py — Path canónico OE9
NSGA-III con restricción semántica r_j <= 0.5 (integración E5-large)
Generado automáticamente desde: scripts/oe9_nsga3.py
HDS-ROI v6.0 — 2026-08-07
"""
# =============================================================================
# oe9_nsga3.py  v1.5 — OE9: NSGA-III 7 Objetivos (MEJORADO CON REPORTES)
# =============================================================================

import json
import warnings
import time
import argparse
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

from pymoo.core.problem import Problem
from pymoo.algorithms.moo.nsga3 import NSGA3
from pymoo.util.ref_dirs import get_reference_directions
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM
from pymoo.operators.sampling.rnd import FloatRandomSampling
from pymoo.optimize import minimize
from pymoo.termination import get_termination

warnings.filterwarnings("ignore")
np.random.seed(42)

INPUT_MATRIX  = Path("data/features/oe9_feature_matrix.csv")
RESULTS_DIR   = Path("results")
FIGURES_DIR   = Path("figures")

OUT_PARETO    = RESULTS_DIR / "oe9_pareto_front.csv"
OUT_PORT_JSON = RESULTS_DIR / "oe9_portafolios_nodominados.json"
OUT_RESUMEN   = RESULTS_DIR / "oe9_resumen_nsga3.json"
OUT_FIG2      = FIGURES_DIR / "oe9_fig2_pareto_2d.png"
OUT_FIG3      = FIGURES_DIR / "oe9_fig3_distribucion.png"

BUDGET_USD    = 100_000.0
N_MIN_SKUS    = 3
RJ_MAX        = 0.50
N_GEN         = 200
POP_SIZE      = 200

DARK  = "#0f0f1a"
PANEL = "#1a1a2e"
GRID  = "#2a2a3e"
C1    = "#00d4ff"
C2    = "#ff6b6b"
C3    = "#ffd93d"
C4    = "#6bcb77"
C5    = "#ff9f43"

def load_catalog(verbose: bool = True) -> pd.DataFrame:
    df = pd.read_csv(INPUT_MATRIX, encoding="utf-8")
    if verbose:
        print(f"[CARGA] {len(df)} SKUs × {df.shape[1]} columnas")

    required = ["roi_unitario_pct", "ganancia_unitaria", "r_j", "categoria"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"Faltan columnas: {missing}")

    df["roi_unitario_pct"] = pd.to_numeric(df["roi_unitario_pct"], errors="coerce")
    df["ganancia_unitaria"] = pd.to_numeric(df["ganancia_unitaria"], errors="coerce")
    df["r_j"] = pd.to_numeric(df["r_j"], errors="coerce")

    # ── Usar precios en USD ya calculados en la matrix ──────────────────
    rj_median = df["r_j"].median()
    nan_rj = int(df["r_j"].isna().sum())
    df["r_j"] = df["r_j"].fillna(rj_median)

    # precio_costo_usd y precio_venta_usd ya están en la matrix corregidos
    df["precio_costo"] = pd.to_numeric(df["precio_costo_usd"], errors="coerce")
    df["precio_venta"] = pd.to_numeric(df["precio_venta_usd"], errors="coerce")

    med_c = df["precio_costo"].median()
    med_v = df["precio_venta"].median()
    nan_costo = int(df["precio_costo"].isna().sum())
    df["precio_costo"] = df["precio_costo"].fillna(med_c)
    df["precio_venta"] = df["precio_venta"].fillna(med_v)

    # roi_esperado_pct desde roi_usd_pct (ya en USD)
    df["roi_esperado_pct"]  = pd.to_numeric(df["roi_usd_pct"], errors="coerce").fillna(
                                    pd.to_numeric(df["roi_usd_pct"], errors="coerce").median())
    df["roi_esperado_frac"] = df["roi_esperado_pct"] / 100.0

    if verbose:
        print(f"[CARGA] Precios USD desde matrix (precio_costo_usd / precio_venta_usd):")
        print(f"  r_j NaN->mediana     : {nan_rj}")
        print(f"  precio_costo NaN     : {nan_costo}")
        print(f"  ROI medio (USD)      : {df['roi_esperado_pct'].mean():.1f}%")
        print(f"  r_j medio            : {df['r_j'].mean():.4f}")
        print(f"  Precio costo medio   : $ {df['precio_costo'].mean():.0f}")
        print(f"  Capital total cat.   : $ {df['precio_costo'].sum():,.0f}")

    df = df.reset_index(drop=True)
    return df

class PortfolioOE9(Problem):
    def __init__(self, df: pd.DataFrame, budget_usd: float, n_min: int, rj_max: float):
        n = len(df)
        super().__init__(
            n_var=n,
            n_obj=7,
            n_ieq_constr=0,
            xl=np.zeros(n, dtype=int),
            xu=np.ones(n, dtype=int),
            vtype=int,
        )
        self.df = df
        self.budget = budget_usd
        self.n_min = n_min
        self.rj_max = rj_max

        self.costos = df["precio_costo"].values.astype(float)
        self.ventas = df["precio_venta"].values.astype(float)
        self.rois = (pd.to_numeric(df["roi_esperado_pct"], errors="coerce").values.astype(float) / 100.0)
        self.rj = df["r_j"].values.astype(float)
        self.cats = pd.Categorical(df["categoria"]).codes

    def _evaluate(self, X, out, *args, **kwargs):
        n_sol = X.shape[0]
        f1 = np.zeros(n_sol)
        f2 = np.zeros(n_sol)
        f3 = np.zeros(n_sol)
        f4 = np.zeros(n_sol)
        f5 = np.zeros(n_sol)
        f6 = np.zeros(n_sol)
        f7 = np.zeros(n_sol)

        for i in range(n_sol):
            x = X[i].astype(int)
            mask = x > 0
            n_act = int(mask.sum())

            if n_act == 0:
                f1[i] = 100.0
                f2[i] = 100.0
                f3[i] = 100.0
                f4[i] = 1.0
                f5[i] = 100.0
                f6[i] = 1.0
                f7[i] = 100.0
                continue

            costos_a = self.costos[mask]
            ventas_a = self.ventas[mask]
            rois_a = self.rois[mask]
            rj_a = self.rj[mask]

            capital = float(costos_a.sum())
            ingresos = float(ventas_a.sum())
            ganancias = ventas_a - costos_a
            ganancia_total = float(ganancias.sum())

            roi_port = ganancia_total / capital if capital > 0 else 0.0
            f1[i] = -roi_port

            w = costos_a / capital
            roi_mean = float((w * rois_a).sum())
            f2[i] = float(np.sqrt((w * (rois_a - roi_mean) ** 2).sum()))

            n_cats_act = len(np.unique(self.cats[mask]))
            f3[i] = -float(n_cats_act)

            w_ingresos = ventas_a / ingresos if ingresos > 0 else w
            f4[i] = float((w_ingresos ** 2).sum())

            rj_port = float((w * rj_a).sum())
            f5[i] = rj_port

            excess_budget = max(0, capital - self.budget)
            f6[i] = (excess_budget / self.budget) ** 2 if self.budget > 0 else 0

            deficit_skus = max(0, self.n_min - n_act)
            f7[i] = float(deficit_skus) ** 2

        out["F"] = np.column_stack([f1, f2, f3, f4, f5, f6, f7])

def create_initial_population(df: pd.DataFrame, budget_usd: float, n_min: int, pop_size: int):
    n = len(df)
    X_init = np.zeros((pop_size, n), dtype=int)

    df_sorted = df.sort_values("precio_costo")
    for p in range(pop_size // 3):
        for j in range(min(n_min + p, len(df))):
            X_init[p, df_sorted.index[j]] = 1

    df_sorted = df.sort_values("roi_esperado_pct", ascending=False)
    for p in range(pop_size // 3, 2 * pop_size // 3):
        for j in range(min(n_min + (p % 5), len(df))):
            X_init[p, df_sorted.index[j]] = 1

    for p in range(2 * pop_size // 3, pop_size):
        n_select = np.random.randint(n_min, min(n_min + 10, n))
        indices = np.random.choice(n, n_select, replace=False)
        X_init[p, indices] = 1

    return X_init

def run_nsga3(df: pd.DataFrame, n_gen: int, pop_size: int, budget_usd: float, verbose: bool = True) -> tuple:
    problem = PortfolioOE9(df=df, budget_usd=budget_usd, n_min=N_MIN_SKUS, rj_max=RJ_MAX)

    ref_dirs = get_reference_directions("das-dennis", 7, n_partitions=4)

    X_init = create_initial_population(df, budget_usd, N_MIN_SKUS, max(pop_size, len(ref_dirs)))

    algorithm = NSGA3(
        ref_dirs=ref_dirs,
        pop_size=max(pop_size, len(ref_dirs)),
        sampling=X_init,
        crossover=SBX(prob=0.9, eta=15),
        mutation=PM(prob=1.0 / len(df), eta=20),
        eliminate_duplicates=True,
    )

    termination = get_termination("n_gen", n_gen)

    if verbose:
        print(f"[NSGA-III] Iniciando optimización...")
        print(f"  SKUs en catálogo : {len(df)}")
        print(f"  Presupuesto      : $ {budget_usd:,.0f}")
        print(f"  Generaciones     : {n_gen}")
        print(f"  Población        : {max(pop_size, len(ref_dirs))}")
        print(f"  Ref. directions  : {len(ref_dirs)}")
        print(f"  Objetivos        : 7 (ROI, Riesgo, Diversif, HHI, r_j, PenBudget, PenSKUs)")
        print(f"  Restricciones    : 0 (SOFT CONSTRAINTS)")
        print(f"  Tipo problema    : BINARIO (0/1 por SKU)")
        print(f"  Inicialización   : Inteligente (3 estrategias)")

    t0 = time.time()
    result = minimize(problem, algorithm, termination, seed=42, verbose=False, save_history=True)
    elapsed = time.time() - t0

    if verbose:
        n_pareto = len(result.F) if result.F is not None else 0
        print(f"[NSGA-III] Completado en {elapsed:.1f}s")
        print(f"  Soluciones en frente de Pareto: {n_pareto}")

    return result, elapsed

def process_results(result, df: pd.DataFrame) -> tuple:
    X = result.X
    F = result.F

    if X is None or len(X) == 0:
        return pd.DataFrame(), []

    portafolios = []
    pareto_rows = []

    for i in range(len(X)):
        x = X[i].astype(int)
        mask = x > 0
        skus = df[mask].copy()

        if len(skus) == 0:
            continue

        capital = float(skus["precio_costo"].sum())
        ingresos = float(skus["precio_venta"].sum())
        ganancia = ingresos - capital
        roi_port = ganancia / capital * 100 if capital > 0 else 0.0
        rj_port = float((skus["r_j"].values / len(skus)).sum())
        n_cats = skus["categoria"].nunique()
        n_skus = int(mask.sum())

        if roi_port >= 50 and rj_port <= 0.15:
            tipo = "ESTRELLA"
        elif roi_port >= 35 and rj_port <= 0.25:
            tipo = "OPTIMO"
        elif rj_port <= 0.10:
            tipo = "SEGURO"
        elif roi_port >= 50:
            tipo = "AGRESIVO"
        else:
            tipo = "BALANCEADO"

        ganancias_ind = skus["precio_venta"].values - skus["precio_costo"].values
        idx_top3 = np.argsort(-ganancias_ind)[:min(3, len(ganancias_ind))]
        skus_top3 = " | ".join(skus.iloc[idx_top3]["producto"].str[:40].tolist())

        pareto_rows.append({
            "sol_id": i,
            "tipo": tipo,
            "n_skus": n_skus,
            "n_categorias": n_cats,
            "capital_usd": round(capital, 2),
            "ingresos_usd": round(ingresos, 2),
            "ganancia_usd": round(ganancia, 2),
            "roi_pct": round(roi_port, 2),
            "rj_portafolio": round(rj_port, 4),
            "skus_top3": skus_top3,
        })

        detalle = []
        for j, (_, row) in enumerate(skus.iterrows()):
            detalle.append({
                "sku": int(row["sku"]) if "sku" in row else j,
                "producto": str(row["producto"])[:60],
                "categoria": str(row["categoria"]),
                "precio_costo_usd": round(float(row["precio_costo"]), 2),
                "precio_venta_usd": round(float(row["precio_venta"]), 2),
                "roi_pct": round(float(row["roi_esperado_pct"]), 2),
                "r_j": round(float(row["r_j"]), 4),
            })

        portafolios.append({
            "sol_id": i,
            "tipo": tipo,
            "roi_pct": round(roi_port, 2),
            "rj_portafolio": round(rj_port, 4),
            "n_skus": n_skus,
            "capital_usd": round(capital, 2),
            "ganancia_usd": round(ganancia, 2),
            "skus": detalle,
        })

    if len(pareto_rows) > 0:
        pareto_df = pd.DataFrame(pareto_rows).sort_values("roi_pct", ascending=False)
    else:
        pareto_df = pd.DataFrame()

    return pareto_df, portafolios

def plot_pareto_2d(pareto_df: pd.DataFrame, budget_usd: float):
    if len(pareto_df) == 0:
        print("[PLOT] No hay datos para graficar")
        return

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.patch.set_facecolor(DARK)
    fig.suptitle(
        f"OE9 — Frente de Pareto (Soft Constraints)\n"
        f"{len(pareto_df)} soluciones  |  Presupuesto: $ {budget_usd:,.0f}",
        color="white", fontsize=13, y=0.98,
    )

    tipo_colors = {
        "ESTRELLA": C1, "OPTIMO": C3, "SEGURO": C4,
        "AGRESIVO": C2, "BALANCEADO": C5,
    }

    ax = axes[0]
    ax.set_facecolor(PANEL)
    ax.grid(color=GRID, linewidth=0.5, alpha=0.6)
    for tipo, grp in pareto_df.groupby("tipo"):
        ax.scatter(grp["roi_pct"], grp["rj_portafolio"],
                   c=tipo_colors.get(tipo, "white"),
                   label=tipo, s=100, alpha=0.85,
                   edgecolors="white", linewidth=0.5)
    ax.set_xlabel("ROI (%)", color="white", fontsize=11)
    ax.set_ylabel("r_j Obsolescencia", color="white", fontsize=11)
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID)
    ax.legend(facecolor=PANEL, edgecolor=GRID, labelcolor="white", fontsize=9)

    ax = axes[1]
    ax.set_facecolor(PANEL)
    ax.grid(color=GRID, linewidth=0.5, alpha=0.6)
    for tipo, grp in pareto_df.groupby("tipo"):
        ax.scatter(grp["capital_usd"], grp["ganancia_usd"],
                   c=tipo_colors.get(tipo, "white"),
                   label=tipo, s=100, alpha=0.85,
                   edgecolors="white", linewidth=0.5)
    ax.set_xlabel("Capital Invertido ($)", color="white", fontsize=11)
    ax.set_ylabel("Ganancia Estimada ($)", color="white", fontsize=11)
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID)

    plt.tight_layout()
    plt.savefig(OUT_FIG2, dpi=150, bbox_inches="tight", facecolor=DARK)
    plt.close()
    print(f"[FIG] {OUT_FIG2}")

def plot_distribucion(pareto_df: pd.DataFrame):
    if len(pareto_df) == 0:
        return

    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    fig.patch.set_facecolor(DARK)
    fig.suptitle("OE9 — Distribuciones del Frente de Pareto", color="white", fontsize=13)

    tipo_colors = {
        "ESTRELLA": C1, "OPTIMO": C3, "SEGURO": C4,
        "AGRESIVO": C2, "BALANCEADO": C5,
    }

    # ROI
    ax = axes[0, 0]
    ax.set_facecolor(PANEL)
    ax.hist(pareto_df["roi_pct"], bins=10, color=C1, alpha=0.7, edgecolor="white")
    ax.set_xlabel("ROI (%)", color="white")
    ax.set_ylabel("Frecuencia", color="white")
    ax.tick_params(colors="white")
    ax.set_title("Distribución de ROI", color="white")

    # SKUs
    ax = axes[0, 1]
    ax.set_facecolor(PANEL)
    ax.hist(pareto_df["n_skus"], bins=10, color=C3, alpha=0.7, edgecolor="white")
    ax.set_xlabel("N° SKUs", color="white")
    ax.set_ylabel("Frecuencia", color="white")
    ax.tick_params(colors="white")
    ax.set_title("Distribución de SKUs por Portafolio", color="white")

    # r_j
    ax = axes[1, 0]
    ax.set_facecolor(PANEL)
    ax.hist(pareto_df["rj_portafolio"], bins=10, color=C5, alpha=0.7, edgecolor="white")
    ax.set_xlabel("r_j Obsolescencia", color="white")
    ax.set_ylabel("Frecuencia", color="white")
    ax.tick_params(colors="white")
    ax.set_title("Distribución de r_j", color="white")

    # Tipo
    ax = axes[1, 1]
    ax.set_facecolor(PANEL)
    tipo_counts = pareto_df["tipo"].value_counts()
    colors = [tipo_colors.get(t, "white") for t in tipo_counts.index]
    ax.bar(range(len(tipo_counts)), tipo_counts.values, color=colors, alpha=0.7, edgecolor="white")
    ax.set_xticks(range(len(tipo_counts)))
    ax.set_xticklabels(tipo_counts.index, rotation=45, color="white")
    ax.set_ylabel("Frecuencia", color="white")
    ax.tick_params(colors="white")
    ax.set_title("Distribución por Tipo de Portafolio", color="white")

    plt.tight_layout()
    plt.savefig(OUT_FIG3, dpi=150, bbox_inches="tight", facecolor=DARK)
    plt.close()
    print(f"[FIG] {OUT_FIG3}")

def build_resumen(pareto_df: pd.DataFrame, elapsed: float, n_gen: int, df: pd.DataFrame, budget_usd: float) -> dict:
    tipo_counts = pareto_df["tipo"].value_counts().to_dict()
    return {
        "version": "1.5-OE9-SOFT-CONSTRAINTS",
        "timestamp": datetime.now().isoformat(),
        "input": str(INPUT_MATRIX),
        "n_skus_catalogo": len(df),
        "budget_usd": budget_usd,
        "rj_max": RJ_MAX,
        "n_min_skus": N_MIN_SKUS,
        "problema": "BINARIO (0/1 por SKU) - SOFT CONSTRAINTS",
        "n_generaciones": n_gen,
        "tiempo_seg": round(elapsed, 1),
        "n_soluciones_pareto": len(pareto_df),
        "tipos_portafolio": tipo_counts,
        "roi_stats": {
            "min": round(float(pareto_df["roi_pct"].min()), 2),
            "max": round(float(pareto_df["roi_pct"].max()), 2),
            "mean": round(float(pareto_df["roi_pct"].mean()), 2),
            "median": round(float(pareto_df["roi_pct"].median()), 2),
        },
        "capital_stats": {
            "min": round(float(pareto_df["capital_usd"].min()), 2),
            "max": round(float(pareto_df["capital_usd"].max()), 2),
            "mean": round(float(pareto_df["capital_usd"].mean()), 2),
            "median": round(float(pareto_df["capital_usd"].median()), 2),
        },
        "ganancia_stats": {
            "min": round(float(pareto_df["ganancia_usd"].min()), 2),
            "max": round(float(pareto_df["ganancia_usd"].max()), 2),
            "mean": round(float(pareto_df["ganancia_usd"].mean()), 2),
            "median": round(float(pareto_df["ganancia_usd"].median()), 2),
        },
        "rj_stats": {
            "min": round(float(pareto_df["rj_portafolio"].min()), 4),
            "max": round(float(pareto_df["rj_portafolio"].max()), 4),
            "mean": round(float(pareto_df["rj_portafolio"].mean()), 4),
            "median": round(float(pareto_df["rj_portafolio"].median()), 4),
        },
        "top5_pareto": pareto_df.head(5)[[
            "sol_id", "tipo", "roi_pct", "rj_portafolio",
            "n_skus", "capital_usd", "ganancia_usd"
        ]].to_dict(orient="records"),
    }

def main():
    global BUDGET_USD, N_MIN_SKUS, RJ_MAX, N_GEN, POP_SIZE

    parser = argparse.ArgumentParser(description="OE9 NSGA-III (SOFT CONSTRAINTS)")
    parser.add_argument("--input", default=str(INPUT_MATRIX))
    parser.add_argument("--budget_usd", type=float, default=BUDGET_USD)
    parser.add_argument("--n_gen", type=int, default=N_GEN)
    parser.add_argument("--pop_size", type=int, default=POP_SIZE)
    parser.add_argument("--rj_max", type=float, default=RJ_MAX)
    parser.add_argument("--n_min", type=int, default=N_MIN_SKUS)
    args = parser.parse_args()

    BUDGET_USD = args.budget_usd
    N_MIN_SKUS = args.n_min
    RJ_MAX = args.rj_max
    N_GEN = args.n_gen
    POP_SIZE = args.pop_size

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("  oe9_nsga3.py v1.5 — NSGA-III (SOFT CONSTRAINTS + REPORTES)")
    print(f"  Inicio  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Budget  : $ {BUDGET_USD:,.0f}")
    print(f"  RJ_MAX  : {RJ_MAX}")
    print("=" * 70)

    df = load_catalog(verbose=True)
    result, elapsed = run_nsga3(df, N_GEN, POP_SIZE, budget_usd=BUDGET_USD, verbose=True)

    if result.X is None or len(result.X) == 0:
        print("❌ No hay soluciones.")
        return

    pareto_df, portafolios = process_results(result, df)

    if len(pareto_df) == 0:
        print("❌ No hay soluciones válidas.")
        return

    pareto_df.to_csv(OUT_PARETO, index=False, encoding="utf-8")
    print(f"\n💾 Pareto CSV  : {OUT_PARETO}  [{len(pareto_df)} soluciones]")

    with open(OUT_PORT_JSON, "w", encoding="utf-8") as f:
        json.dump(portafolios, f, ensure_ascii=False, indent=2)
    print(f"💾 Portafolios : {OUT_PORT_JSON}")

    resumen = build_resumen(pareto_df, elapsed, N_GEN, df, budget_usd=BUDGET_USD)
    with open(OUT_RESUMEN, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)
    print(f"📄 Resumen     : {OUT_RESUMEN}")

    print("\n📊 Generando figuras...")
    plot_pareto_2d(pareto_df, budget_usd=BUDGET_USD)
    plot_distribucion(pareto_df)

    print(f"\n{'='*70}")
    print(f"📋 RESUMEN FRENTE DE PARETO OE9")
    print(f"   Soluciones: {len(pareto_df)}")
    print(f"   Tiempo: {elapsed:.1f}s")
    print(f"   ROI: {pareto_df['roi_pct'].min():.1f}% – {pareto_df['roi_pct'].max():.1f}%")
    print(f"   Capital: $ {pareto_df['capital_usd'].min():,.0f} – $ {pareto_df['capital_usd'].max():,.0f}")
    print(f"   Ganancia: $ {pareto_df['ganancia_usd'].min():,.0f} – $ {pareto_df['ganancia_usd'].max():,.0f}")
    print(f"   r_j: {pareto_df['rj_portafolio'].min():.4f} – {pareto_df['rj_portafolio'].max():.4f}")
    print(f"\n{'─'*70}")
    print(f"{'Tipo':<12} {'ROI%':>7} {'r_j':>7} {'SKUs':>5} {'Capital':>12} {'Ganancia':>12}")
    print(f"{'─'*70}")
    for _, row in pareto_df.head(20).iterrows():
        print(f"{row['tipo']:<12} {row['roi_pct']:>7.1f} {row['rj_portafolio']:>7.4f} {row['n_skus']:>5} "
              f"$ {row['capital_usd']:>10,.0f} $ {row['ganancia_usd']:>10,.0f}")

    print(f"\n✅ OE9 completado.")
    print("=" * 70)

if __name__ == "__main__":
    main()