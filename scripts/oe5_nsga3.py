"""
oe5_nsga3.py — OE5: Optimización Multiobjetivo con NSGA-III
═══════════════════════════════════════════════════════════════
REFERENCIA:
  Blank, J. & Deb, K. (2020). pymoo: Multi-Objective Optimization
  in Python. IEEE Access, 8, 89497–89509.
  DOI: 10.1109/ACCESS.2020.2990567

PROBLEMA:
  Dado un presupuesto B y un catálogo de N SKUs, encontrar el
  conjunto de portafolios no-dominados (Frente de Pareto) que
  optimizan simultáneamente 4 objetivos:

    f1 = −ROI_esperado          (maximizar → minimizar negativo)
    f2 = +Riesgo_MC             (minimizar varianza ponderada)
    f3 = −N_categorias          (maximizar diversificación)
    f4 = +HHI                   (minimizar concentración Herfindahl)

RESTRICCIONES:
    g1: capital_utilizado ≤ B   (no superar presupuesto)
    g2: n_skus ≥ 5              (mínimo 5 SKUs distintos)

COLUMNAS DEL CSV (oe4a_productos_roi_moderado.csv):
  title_local         → nombre del producto
  price_import_real_base → costo de importación real (escenario base)
  precio_venta_est    → precio de venta estimado
  category            → categoría del producto
  roi_esperado_pct    → ROI esperado unitario

OUTPUTS:
  figures/oe5_fig1_pareto_3d.png
  figures/oe5_fig2_pareto_2d_pairs.png
  figures/oe5_fig3_convergencia.png
  figures/oe5_fig4_portafolios_destacados.png
  results/oe5_pareto_front.csv
  results/oe5_portafolios_nodominados.json
  results/oe5_resumen_nsga3.json
"""

import json, warnings, time
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from mpl_toolkits.mplot3d import Axes3D

from pymoo.core.problem import Problem
from pymoo.algorithms.moo.nsga3 import NSGA3
from pymoo.util.ref_dirs import get_reference_directions
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM
from pymoo.operators.sampling.rnd import IntegerRandomSampling
from pymoo.operators.repair.rounding import RoundingRepair
from pymoo.optimize import minimize
from pymoo.termination import get_termination

warnings.filterwarnings("ignore")
np.random.seed(42)

Path("results").mkdir(parents=True, exist_ok=True)
Path("figures").mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════════════════
# MAPEO DE COLUMNAS REALES del CSV oe4a
# ══════════════════════════════════════════════════════════════
COL_TITULO    = "title_local"
COL_COSTO     = "price_import_real_base"
COL_PVENTA    = "precio_venta_est"
COL_CATEGORIA = "category"
COL_ROI_ESP   = "roi_esperado_pct"

# ══════════════════════════════════════════════════════════════
# COLORES
# ══════════════════════════════════════════════════════════════
DARK   = '#0f0f1a'; PANEL = '#1a1a2e'; GRID = '#2a2a3e'
WHITE  = '#e8e8f0'; CYAN  = '#00d4ff'; GREEN = '#00ff88'
AMBER  = '#ffaa00'; RED   = '#ff4d6d'; PURPLE = '#c084fc'

# ══════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════
PRESUPUESTO   = 5000.0
MAX_UNID_SKU  = 4
MIN_SKUS      = 5
N_CANDIDATOS  = 80
POP_SIZE      = 200
N_GEN         = 150
SEED          = 42

FACTOR_VENTA    = 0.72
FACTOR_ROTACION = 0.90
COSTO_OP        = 0.04
OVERHEAD_BASE   = 0.468

# ══════════════════════════════════════════════════════════════
# 1. CARGAR Y PREPARAR CATÁLOGO
# ══════════════════════════════════════════════════════════════
def cargar_catalogo(n_top: int = N_CANDIDATOS) -> pd.DataFrame:
    fp = Path("results/oe4a_productos_roi_moderado.csv")
    if not fp.exists():
        raise FileNotFoundError(
            f"No encontrado: {fp}\n"
            "Ejecuta primero: python scripts/oe4a_roi_calculator.py")

    df = pd.read_csv(fp)
    print(f"  Catálogo cargado    : {len(df)} SKUs")
    print(f"  Columnas disponibles: {len(df.columns)}")

    # Verificar columnas críticas
    for col in [COL_TITULO, COL_COSTO, COL_PVENTA, COL_CATEGORIA, COL_ROI_ESP]:
        if col not in df.columns:
            raise KeyError(f"Columna '{col}' no encontrada. "
                           f"Columnas: {df.columns.tolist()}")

    # Limpiar: eliminar filas con costo o precio nulo/cero
    df = df[df[COL_COSTO].notna() & (df[COL_COSTO] > 0)].copy()
    df = df[df[COL_PVENTA].notna() & (df[COL_PVENTA] > 0)].copy()
    df = df[df[COL_ROI_ESP].notna()].copy()

    # Eliminar duplicados por título
    df = df.drop_duplicates(subset=[COL_TITULO]).reset_index(drop=True)

    # Ordenar por ROI esperado y tomar top N
    df = df.sort_values(COL_ROI_ESP, ascending=False).head(n_top)
    df = df.reset_index(drop=True)

    print(f"  Candidatos top-{n_top}   : {len(df)}")
    print(f"  Categorías presentes: {df[COL_CATEGORIA].nunique()} "
          f"→ {sorted(df[COL_CATEGORIA].unique())}")
    print(f"  ROI_esp rango       : [{df[COL_ROI_ESP].min():.1f}%, "
          f"{df[COL_ROI_ESP].max():.1f}%]")
    print(f"  Costo rango         : [${df[COL_COSTO].min():.0f}, "
          f"${df[COL_COSTO].max():.0f}]")

    return df

# ══════════════════════════════════════════════════════════════
# 2. FUNCIONES DE EVALUACIÓN
# ══════════════════════════════════════════════════════════════
def evaluar_portafolio(x: np.ndarray, df: pd.DataFrame) -> dict:
    """
    Dado un vector de cantidades x, calcula los 4 objetivos.
    x[i] = unidades del SKU i (0 a MAX_UNID_SKU)
    """
    mask = x > 0
    n_skus = int(mask.sum())

    if n_skus == 0:
        return {
            "roi": 0.0, "riesgo": 999.0, "n_cats": 0,
            "hhi": 1.0, "capital": 0.0,  "ganancia": 0.0,
            "n_skus": 0, "categorias": [],
        }

    sub       = df[mask].copy()
    cantidades = x[mask].astype(float)

    costos    = sub[COL_COSTO].values
    pventas   = sub[COL_PVENTA].values
    capital_total = (costos * cantidades).sum()

    if capital_total <= 0:
        return {
            "roi": 0.0, "riesgo": 999.0, "n_cats": 0,
            "hhi": 1.0, "capital": 0.0,  "ganancia": 0.0,
            "n_skus": n_skus, "categorias": [],
        }

    # Ganancia esperada usando columnas reales
    # precio_venta_est ya incluye factor_venta y costo_op del perfil moderado
    # Recalculamos con los factores base para consistencia
    ganancia_unit = (
        pventas * FACTOR_VENTA / 0.72
        * (1 - COSTO_OP) / (1 - 0.04)
        - costos
    )
    ganancia_esp = (
        ganancia_unit * FACTOR_ROTACION
        - costos * (1 - FACTOR_ROTACION)
    )
    ganancia_total = (ganancia_esp * cantidades).sum()
    roi = ganancia_total / capital_total * 100

    # Riesgo: desviación estándar ponderada del ROI por SKU
    roi_por_sku = np.where(
        costos > 0,
        ganancia_esp / costos * 100,
        0.0
    )
    pesos  = (costos * cantidades) / capital_total
    riesgo = float(np.sqrt(np.sum(pesos * (roi_por_sku - roi) ** 2)))

    # Diversificación
    cats       = sub[COL_CATEGORIA].values
    categorias = list(set(cats))
    n_cats     = len(categorias)

    # HHI por categoría
    capital_por_cat = {}
    for cat in categorias:
        mask_cat = cats == cat
        capital_por_cat[cat] = (costos[mask_cat] * cantidades[mask_cat]).sum()
    w   = np.array(list(capital_por_cat.values())) / capital_total
    hhi = float(np.sum(w ** 2))

    return {
        "roi"       : float(roi),
        "riesgo"    : riesgo,
        "n_cats"    : n_cats,
        "hhi"       : hhi,
        "capital"   : float(capital_total),
        "ganancia"  : float(ganancia_total),
        "n_skus"    : n_skus,
        "categorias": categorias,
    }

# ══════════════════════════════════════════════════════════════
# 3. PROBLEMA PYMOO
# ══════════════════════════════════════════════════════════════
class PortfolioOptProblem(Problem):
    def __init__(self, df: pd.DataFrame, presupuesto: float):
        self.df          = df
        self.presupuesto = presupuesto
        n_var = len(df)
        super().__init__(
            n_var        = n_var,
            n_obj        = 4,
            n_ieq_constr = 2,
            xl           = np.zeros(n_var, dtype=int),
            xu           = np.full(n_var, MAX_UNID_SKU, dtype=int),
            vtype        = int,
        )

    def _evaluate(self, X, out, *args, **kwargs):
        n_sol = X.shape[0]
        F = np.zeros((n_sol, 4))
        G = np.zeros((n_sol, 2))

        for i in range(n_sol):
            ev = evaluar_portafolio(X[i].astype(int), self.df)
            F[i, 0] = -ev["roi"]       # f1: −ROI  (max ROI)
            F[i, 1] =  ev["riesgo"]    # f2: riesgo (min)
            F[i, 2] = -ev["n_cats"]    # f3: −cats  (max diversif)
            F[i, 3] =  ev["hhi"]       # f4: HHI   (min concentración)
            G[i, 0] = ev["capital"] - self.presupuesto   # ≤ 0
            G[i, 1] = MIN_SKUS - ev["n_skus"]            # ≤ 0

        out["F"] = F
        out["G"] = G

# ══════════════════════════════════════════════════════════════
# 4. EJECUTAR NSGA-III
# ══════════════════════════════════════════════════════════════
def ejecutar_nsga3(df: pd.DataFrame):
    print(f"\n  Configurando NSGA-III...")
    print(f"    Población     : {POP_SIZE}")
    print(f"    Generaciones  : {N_GEN}")
    print(f"    Variables     : {len(df)} SKUs × {MAX_UNID_SKU} unidades máx")
    print(f"    Objetivos     : 4 (ROI, Riesgo, Diversif., HHI)")
    print(f"    Restricciones : capital ≤ ${PRESUPUESTO:,.0f} | SKUs ≥ {MIN_SKUS}")

    ref_dirs = get_reference_directions(
        "das-dennis", n_dim=4, n_partitions=12)
    print(f"    Puntos ref.   : {len(ref_dirs)} (Das-Dennis, n_partitions=12)")

    problem = PortfolioOptProblem(df, PRESUPUESTO)

    algorithm = NSGA3(
        ref_dirs  = ref_dirs,
        pop_size  = POP_SIZE,
        sampling  = IntegerRandomSampling(),
        crossover = SBX(prob=0.9, eta=15, vtype=float, repair=RoundingRepair()),
        mutation  = PM(prob=1.0/len(df), eta=20, vtype=float, repair=RoundingRepair()),
        eliminate_duplicates = True,
    )

    termination = get_termination("n_gen", N_GEN)

    print(f"\n  Ejecutando optimización... (~2-4 min)\n")
    t0  = time.time()
    res = minimize(
        problem, algorithm, termination,
        seed=SEED, verbose=True, save_history=True,
    )
    elapsed = time.time() - t0

    print(f"\n  ✓ Completado en {elapsed:.1f}s")
    print(f"  Soluciones Pareto: {len(res.F)}")
    return res, problem

# ══════════════════════════════════════════════════════════════
# 5. EXTRAER Y CLASIFICAR PORTAFOLIOS
# ══════════════════════════════════════════════════════════════
def extraer_portafolios(res, df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for i, (x, f) in enumerate(zip(res.X, res.F)):
        xi = x.astype(int)
        ev = evaluar_portafolio(xi, df)
        skus_sel = df[xi > 0][COL_TITULO].tolist()
        rows.append({
            "sol_id"      : i,
            "roi_pct"     : round(ev["roi"], 2),
            "riesgo"      : round(ev["riesgo"], 4),
            "n_cats"      : ev["n_cats"],
            "hhi"         : round(ev["hhi"], 4),
            "capital_usd" : round(ev["capital"], 2),
            "ganancia_usd": round(ev["ganancia"], 2),
            "n_skus"      : ev["n_skus"],
            "categorias"  : "|".join(sorted(set(ev["categorias"]))),
            "skus_top3"   : "|".join(skus_sel[:3]),
            "x_vector"    : ",".join(map(str, xi)),
        })

    df_p = pd.DataFrame(rows)

    # Clasificar destacados
    df_p["tipo"] = "normal"
    df_p.loc[df_p["roi_pct"].idxmax(),  "tipo"] = "max_roi"
    df_p.loc[df_p["riesgo"].idxmin(),   "tipo"] = "min_riesgo"
    df_p.loc[df_p["n_cats"].idxmax(),   "tipo"] = "max_diversif"
    df_p.loc[df_p["hhi"].idxmin(),      "tipo"] = "min_concentracion"

    # Portafolio equilibrado: menor distancia al punto utópico normalizado
    df_n = df_p[["roi_pct","riesgo","n_cats","hhi"]].copy()
    eps  = 1e-9
    df_n["roi_pct"] = (df_n["roi_pct"] - df_n["roi_pct"].min()) / (df_n["roi_pct"].max() - df_n["roi_pct"].min() + eps)
    df_n["riesgo"]  = 1 - (df_n["riesgo"]  - df_n["riesgo"].min())  / (df_n["riesgo"].max()  - df_n["riesgo"].min()  + eps)
    df_n["n_cats"]  = (df_n["n_cats"]  - df_n["n_cats"].min())  / (df_n["n_cats"].max()  - df_n["n_cats"].min()  + eps)
    df_n["hhi"]     = 1 - (df_n["hhi"]     - df_n["hhi"].min())     / (df_n["hhi"].max()     - df_n["hhi"].min()     + eps)
    dist = np.sqrt(((df_n.values - np.ones(4)) ** 2).sum(axis=1))
    df_p.loc[dist.argmin(), "tipo"] = "equilibrado"

    return df_p

# ══════════════════════════════════════════════════════════════
# 6. VISUALIZACIONES
# ══════════════════════════════════════════════════════════════
def plot_pareto_3d(df_p: pd.DataFrame):
    fig = plt.figure(figsize=(12, 8))
    fig.patch.set_facecolor(DARK)
    ax  = fig.add_subplot(111, projection="3d")
    ax.set_facecolor(PANEL)

    tipos_cfg = {
        "normal"           : (CYAN,   25, "Pareto"),
        "max_roi"          : (GREEN,  150, "Máx ROI"),
        "min_riesgo"       : (AMBER,  150, "Mín Riesgo"),
        "max_diversif"     : (PURPLE, 150, "Máx Diversif."),
        "min_concentracion": (RED,    150, "Mín HHI"),
        "equilibrado"      : (WHITE,  200, "Equilibrado ★"),
    }

    for tipo, (color, size, label) in tipos_cfg.items():
        sub = df_p[df_p["tipo"] == tipo]
        if len(sub) == 0:
            continue
        ax.scatter(sub["roi_pct"], sub["riesgo"], sub["n_cats"],
                   c=color, s=size, alpha=0.85, label=label,
                   edgecolors="white" if size > 50 else "none",
                   linewidths=0.5)

    for tipo in ["max_roi","min_riesgo","max_diversif","equilibrado"]:
        sub = df_p[df_p["tipo"] == tipo]
        if len(sub) == 0:
            continue
        r = sub.iloc[0]
        ax.text(r["roi_pct"], r["riesgo"], r["n_cats"] + 0.1,
                f"  {tipo.replace('_',' ').title()}\n  ROI={r['roi_pct']:.0f}%",
                color=WHITE, fontsize=7)

    ax.set_xlabel("ROI Esperado (%)",       color=WHITE, labelpad=8)
    ax.set_ylabel("Riesgo (σ ponderada)",   color=WHITE, labelpad=8)
    ax.set_zlabel("N° Categorías",          color=WHITE, labelpad=8)
    ax.set_title(
        f"Frente de Pareto — NSGA-III\n"
        f"4 objetivos | {len(df_p)} soluciones no-dominadas",
        color=WHITE, fontsize=11)
    ax.tick_params(colors=WHITE)
    ax.xaxis.pane.fill = False
    ax.yaxis.pane.fill = False
    ax.zaxis.pane.fill = False
    ax.xaxis.pane.set_edgecolor(GRID)
    ax.yaxis.pane.set_edgecolor(GRID)
    ax.zaxis.pane.set_edgecolor(GRID)
    ax.legend(facecolor=PANEL, labelcolor=WHITE, edgecolor=GRID,
              fontsize=8, loc="upper left")

    plt.tight_layout()
    fname = "figures/oe5_fig1_pareto_3d.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight", facecolor=DARK)
    plt.close()
    print(f"  ✓ {fname}")

def plot_pareto_2d_pairs(df_p: pd.DataFrame):
    pares = [
        ("roi_pct", "riesgo",  "ROI Esperado (%)", "Riesgo (σ)"),
        ("roi_pct", "n_cats",  "ROI Esperado (%)", "N° Categorías"),
        ("roi_pct", "hhi",     "ROI Esperado (%)", "HHI (concentración)"),
        ("riesgo",  "n_cats",  "Riesgo (σ)",       "N° Categorías"),
        ("riesgo",  "hhi",     "Riesgo (σ)",       "HHI"),
        ("n_cats",  "hhi",     "N° Categorías",    "HHI"),
    ]
    tipos_cfg = {
        "normal"           : (CYAN,   20),
        "max_roi"          : (GREEN,  100),
        "min_riesgo"       : (AMBER,  100),
        "max_diversif"     : (PURPLE, 100),
        "min_concentracion": (RED,    100),
        "equilibrado"      : (WHITE,  150),
    }

    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    fig.patch.set_facecolor(DARK)
    fig.suptitle(
        f"Frente de Pareto — Pares de Objetivos | {len(df_p)} soluciones",
        color=WHITE, fontsize=13, fontweight="bold")

    for ax, (xc, yc, xl, yl) in zip(axes.flat, pares):
        ax.set_facecolor(PANEL)
        for tipo, (color, size) in tipos_cfg.items():
            sub   = df_p[df_p["tipo"] == tipo]
            if len(sub) == 0:
                continue
            label = tipo.replace("_"," ").title() if tipo != "normal" else None
            ax.scatter(sub[xc], sub[yc], c=color, s=size, alpha=0.8,
                       label=label,
                       edgecolors="white" if size > 30 else "none",
                       linewidths=0.5, zorder=3 if size > 30 else 2)
        ax.set_xlabel(xl, color=WHITE, fontsize=8)
        ax.set_ylabel(yl, color=WHITE, fontsize=8)
        ax.tick_params(colors=WHITE, labelsize=7)
        ax.spines[:].set_color(GRID)
        ax.grid(alpha=0.15, color=WHITE)
        if xc == "roi_pct":
            ax.xaxis.set_major_formatter(
                mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))

    plt.tight_layout()
    fname = "figures/oe5_fig2_pareto_2d_pairs.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight", facecolor=DARK)
    plt.close()
    print(f"  ✓ {fname}")

def plot_convergencia(res):
    n_pareto_hist = []
    best_roi_hist = []
    for gen in res.history:
        pop_F = gen.pop.get("F")
        if pop_F is not None:
            n_pareto_hist.append(len(pop_F))
            best_roi_hist.append(-pop_F[:, 0].min())

    fig, axes = plt.subplots(1, 2, figsize=(13, 4))
    fig.patch.set_facecolor(DARK)
    fig.suptitle("Convergencia NSGA-III", color=WHITE,
                 fontsize=12, fontweight="bold")
    gens = np.arange(1, len(n_pareto_hist) + 1)

    ax = axes[0]; ax.set_facecolor(PANEL)
    ax.plot(gens, n_pareto_hist, color=CYAN, lw=2)
    ax.fill_between(gens, n_pareto_hist, alpha=0.15, color=CYAN)
    ax.set_xlabel("Generación", color=WHITE)
    ax.set_ylabel("Tamaño de población", color=WHITE)
    ax.set_title("Evolución del tamaño de población", color=WHITE)
    ax.tick_params(colors=WHITE); ax.spines[:].set_color(GRID)
    ax.grid(alpha=0.15, color=WHITE)

    ax2 = axes[1]; ax2.set_facecolor(PANEL)
    ax2.plot(gens, best_roi_hist, color=GREEN, lw=2)
    ax2.fill_between(gens, best_roi_hist, alpha=0.15, color=GREEN)
    ax2.set_xlabel("Generación", color=WHITE)
    ax2.set_ylabel("Mejor ROI (%)", color=WHITE)
    ax2.set_title("Evolución del mejor ROI", color=WHITE)
    ax2.tick_params(colors=WHITE); ax2.spines[:].set_color(GRID)
    ax2.grid(alpha=0.15, color=WHITE)
    ax2.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))

    plt.tight_layout()
    fname = "figures/oe5_fig3_convergencia.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight", facecolor=DARK)
    plt.close()
    print(f"  ✓ {fname}")

def plot_portafolios_destacados(df_p: pd.DataFrame):
    tipos_interes = ["max_roi","min_riesgo","max_diversif",
                     "min_concentracion","equilibrado"]
    colores = [GREEN, AMBER, PURPLE, RED, WHITE]

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.patch.set_facecolor(DARK)
    fig.suptitle("Portafolios Destacados del Frente de Pareto",
                 color=WHITE, fontsize=13, fontweight="bold")

    # ── Radar ──────────────────────────────────────────────
    axes[0].set_facecolor(PANEL); axes[0].axis("off")
    cats_radar = ["ROI\n(%)", "Seguridad\n(1−σ)", "Diversif.\n(cats)", "No-conc.\n(1−HHI)"]
    N      = len(cats_radar)
    angles = np.linspace(0, 2*np.pi, N, endpoint=False).tolist()
    angles += angles[:1]

    ax_r = fig.add_axes([0.03, 0.08, 0.44, 0.80], polar=True)
    ax_r.set_facecolor(PANEL)
    ax_r.spines["polar"].set_color(GRID)
    ax_r.set_xticks(angles[:-1])
    ax_r.set_xticklabels(cats_radar, color=WHITE, fontsize=9)
    ax_r.tick_params(colors=WHITE)
    ax_r.set_yticklabels([])
    ax_r.grid(color=GRID, alpha=0.4)

    subs = []
    for tipo in tipos_interes:
        sub = df_p[df_p["tipo"] == tipo]
        if len(sub) > 0:
            subs.append(sub.iloc[0])

    if subs:
        roi_v  = [s["roi_pct"] for s in subs]
        risk_v = [s["riesgo"]  for s in subs]
        cat_v  = [s["n_cats"]  for s in subs]
        hhi_v  = [s["hhi"]     for s in subs]
        eps    = 1e-9

        def norm(v, vals):
            mn, mx = min(vals), max(vals)
            return (v - mn) / (mx - mn + eps)
        def norm_inv(v, vals):
            mn, mx = min(vals), max(vals)
            return 1 - (v - mn) / (mx - mn + eps)

        for i, (s, color) in enumerate(zip(subs, colores)):
            vals = [norm(roi_v[i], roi_v), norm_inv(risk_v[i], risk_v),
                    norm(cat_v[i], cat_v), norm_inv(hhi_v[i], hhi_v)]
            vals += vals[:1]
            ax_r.plot(angles, vals, color=color, lw=2, alpha=0.9,
                      label=tipos_interes[i].replace("_"," ").title())
            ax_r.fill(angles, vals, color=color, alpha=0.10)

        ax_r.legend(facecolor=PANEL, labelcolor=WHITE, edgecolor=GRID,
                    fontsize=7, loc="upper right",
                    bbox_to_anchor=(1.35, 1.15))

    ax_r.set_title("Radar: 4 Objetivos Normalizados",
                   color=WHITE, fontsize=10, pad=15)

    # ── Tabla ──────────────────────────────────────────────
    ax_t = axes[1]; ax_t.set_facecolor(PANEL); ax_t.axis("off")
    col_labels = ["Tipo", "ROI", "Riesgo", "Cats", "HHI", "Capital", "SKUs"]
    table_data = []
    for tipo in tipos_interes:
        sub = df_p[df_p["tipo"] == tipo]
        if len(sub) == 0:
            continue
        r = sub.iloc[0]
        table_data.append([
            tipo.replace("_"," ").title(),
            f"{r['roi_pct']:+.1f}%",
            f"{r['riesgo']:.2f}",
            str(int(r['n_cats'])),
            f"{r['hhi']:.3f}",
            f"${r['capital_usd']:,.0f}",
            str(int(r['n_skus'])),
        ])

    if table_data:
        tbl = ax_t.table(cellText=table_data, colLabels=col_labels,
                         cellLoc="center", loc="center")
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(9)
        tbl.scale(1.2, 2.0)
        for (r, c), cell in tbl.get_celld().items():
            cell.set_facecolor(PANEL if r > 0 else GRID)
            cell.set_edgecolor(GRID)
            cell.set_text_props(
                color=colores[r-1] if r > 0 else WHITE)

    ax_t.set_title("Comparativa de Portafolios Destacados",
                   color=WHITE, fontsize=10, pad=10)

    plt.tight_layout()
    fname = "figures/oe5_fig4_portafolios_destacados.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight", facecolor=DARK)
    plt.close()
    print(f"  ✓ {fname}")

# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 68)
    print("  OE5: Optimización Multiobjetivo NSGA-III")
    print(f"  pymoo 0.6.2 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 68)
    print(f"""
PROBLEMA:
  Presupuesto  : ${PRESUPUESTO:,.0f} USD
  Candidatos   : {N_CANDIDATOS} SKUs (top por ROI_esp, perfil moderado)
  Objetivos    : 4 (ROI, Riesgo, Diversificación, HHI)
  Restricciones: capital ≤ ${PRESUPUESTO:,.0f} | SKUs ≥ {MIN_SKUS}
  Algoritmo    : NSGA-III (Deb & Jain, 2014)
  Referencia   : Blank & Deb (2020) IEEE Access
""")

    # 1. Catálogo
    print("─" * 68)
    print("  [1/5] Cargando catálogo...")
    df_cat = cargar_catalogo(N_CANDIDATOS)

    # 2. NSGA-III
    print("\n" + "─" * 68)
    print("  [2/5] Ejecutando NSGA-III...")
    res, problem = ejecutar_nsga3(df_cat)

    # 3. Extraer Pareto
    print("\n" + "─" * 68)
    print("  [3/5] Extrayendo frente de Pareto...")
    df_pareto = extraer_portafolios(res, df_cat)
    print(f"  Soluciones no-dominadas : {len(df_pareto)}")
    print(f"  ROI rango    : [{df_pareto['roi_pct'].min():.1f}%, "
          f"{df_pareto['roi_pct'].max():.1f}%]")
    print(f"  Riesgo rango : [{df_pareto['riesgo'].min():.3f}, "
          f"{df_pareto['riesgo'].max():.3f}]")
    print(f"  Cats rango   : [{df_pareto['n_cats'].min()}, "
          f"{df_pareto['n_cats'].max()}]")
    print(f"  HHI rango    : [{df_pareto['hhi'].min():.3f}, "
          f"{df_pareto['hhi'].max():.3f}]")

    print("\n  PORTAFOLIOS DESTACADOS:")
    print(f"  {'Tipo':<22} {'ROI':>8} {'Riesgo':>8} {'Cats':>6} "
          f"{'HHI':>7} {'Capital':>10} {'SKUs':>5}")
    print("  " + "─" * 70)
    for tipo in ["max_roi","min_riesgo","max_diversif",
                 "min_concentracion","equilibrado"]:
        sub = df_pareto[df_pareto["tipo"] == tipo]
        if len(sub) == 0:
            continue
        r = sub.iloc[0]
        print(f"  {tipo:<22} {r['roi_pct']:>+7.1f}% {r['riesgo']:>8.3f} "
              f"{r['n_cats']:>6} {r['hhi']:>7.3f} "
              f"${r['capital_usd']:>8,.0f} {r['n_skus']:>5}")

    # 4. Figuras
    print("\n" + "─" * 68)
    print("  [4/5] Generando figuras...")
    plot_pareto_3d(df_pareto)
    plot_pareto_2d_pairs(df_pareto)
    plot_convergencia(res)
    plot_portafolios_destacados(df_pareto)

    # 5. Guardar
    print("\n" + "─" * 68)
    print("  [5/5] Guardando resultados...")

    df_pareto.drop(columns=["x_vector"]).to_csv(
        "results/oe5_pareto_front.csv", index=False)
    print("  ✓ results/oe5_pareto_front.csv")

    destacados = {}
    for tipo in ["max_roi","min_riesgo","max_diversif",
                 "min_concentracion","equilibrado"]:
        sub = df_pareto[df_pareto["tipo"] == tipo]
        if len(sub) == 0:
            continue
        r  = sub.iloc[0]
        xi = np.array(list(map(int, r["x_vector"].split(","))))
        skus_detalle = []
        for j, cant in enumerate(xi):
            if cant > 0:
                sku = df_cat.iloc[j]
                skus_detalle.append({
                    "titulo"    : str(sku[COL_TITULO]),
                    "categoria" : str(sku[COL_CATEGORIA]),
                    "cantidad"  : int(cant),
                    "costo_unit": float(sku[COL_COSTO]),
                    "roi_esp"   : float(sku[COL_ROI_ESP]),
                })
        destacados[tipo] = {
            "roi_pct"     : r["roi_pct"],
            "riesgo"      : r["riesgo"],
            "n_cats"      : int(r["n_cats"]),
            "hhi"         : r["hhi"],
            "capital_usd" : r["capital_usd"],
            "ganancia_usd": r["ganancia_usd"],
            "n_skus"      : int(r["n_skus"]),
            "skus"        : skus_detalle,
        }

    with open("results/oe5_portafolios_nodominados.json","w",
              encoding="utf-8") as f:
        json.dump(destacados, f, indent=2, ensure_ascii=False)
    print("  ✓ results/oe5_portafolios_nodominados.json")

    resumen = {
        "timestamp"           : datetime.now().isoformat(),
        "algoritmo"           : "NSGA-III",
        "referencia"          : "Blank & Deb (2020) IEEE Access 10.1109/ACCESS.2020.2990567",
        "pymoo_version"       : "0.6.2",
        "presupuesto_usd"     : PRESUPUESTO,
        "n_candidatos"        : N_CANDIDATOS,
        "pop_size"            : POP_SIZE,
        "n_gen"               : N_GEN,
        "n_objetivos"         : 4,
        "n_restricciones"     : 2,
        "n_soluciones_pareto" : len(df_pareto),
        "roi_min_pct"         : round(df_pareto["roi_pct"].min(), 2),
        "roi_max_pct"         : round(df_pareto["roi_pct"].max(), 2),
        "riesgo_min"          : round(df_pareto["riesgo"].min(), 4),
        "riesgo_max"          : round(df_pareto["riesgo"].max(), 4),
        "cats_min"            : int(df_pareto["n_cats"].min()),
        "cats_max"            : int(df_pareto["n_cats"].max()),
        "hhi_min"             : round(df_pareto["hhi"].min(), 4),
        "hhi_max"             : round(df_pareto["hhi"].max(), 4),
    }
    with open("results/oe5_resumen_nsga3.json","w",encoding="utf-8") as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False)
    print("  ✓ results/oe5_resumen_nsga3.json")

    print("\n" + "=" * 68)
    print("  OE5 COMPLETADO ✅")
    print("=" * 68)
    print("""
Outputs:
  figures/oe5_fig1_pareto_3d.png              ← frente Pareto 3D
  figures/oe5_fig2_pareto_2d_pairs.png        ← 6 pares de objetivos
  figures/oe5_fig3_convergencia.png           ← evolución generacional
  figures/oe5_fig4_portafolios_destacados.png ← radar + tabla
  results/oe5_pareto_front.csv
  results/oe5_portafolios_nodominados.json
  results/oe5_resumen_nsga3.json

Siguiente:
  python scripts/oe6_tft_tcn.py
    """)