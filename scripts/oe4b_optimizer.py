"""
oe4b_optimizer.py — OE4-B / OE10 v4
=====================================
CAMBIOS v4:
  - Fase 2 ahora opera en 2 sub-fases:
      2A — EXPLORACIÓN: añade 1 unidad por iteración hasta alcanzar min_skus
           → garantiza diversidad de SKUs
      2B — CONCENTRACIÓN: añade max unidades posibles para usar el presupuesto
           → maximiza ganancia con el capital restante
  - Penalización soft en 2A: categorías con >20% del capital reciben
    un descuento del 30% en su score para forzar exploración
  - Resultado esperado: 12-18 SKUs distintos, 5-8 categorías
"""

import argparse, json, warnings
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
        "label"            : "Conservador",
        "max_unidades"     : 3,
        "max_pct_categoria": 0.35,
        "penalizacion_pct" : 0.20,   # penalizar si cat > 20% del capital
        "min_cats"         : 4,
        "min_skus"         : 10,
        "min_roi_pct"      : 15.0,
        "max_precio_unit"  : 300.0,
        "color"            : "#00ff88",
        "emoji"            : "🛡️",
    },
    "moderado": {
        "label"            : "Moderado",
        "max_unidades"     : 4,
        "max_pct_categoria": 0.30,
        "penalizacion_pct" : 0.18,
        "min_cats"         : 5,
        "min_skus"         : 12,
        "min_roi_pct"      : 10.0,
        "max_precio_unit"  : 800.0,
        "color"            : "#00d4ff",
        "emoji"            : "⚖️",
    },
    "agresivo": {
        "label"            : "Agresivo",
        "max_unidades"     : 6,
        "max_pct_categoria": 0.35,
        "penalizacion_pct" : 0.15,
        "min_cats"         : 6,
        "min_skus"         : 15,
        "min_roi_pct"      : 8.0,
        "max_precio_unit"  : 2000.0,
        "color"            : "#ff4d6d",
        "emoji"            : "🚀",
    },
}

DARK  = '#0f0f1a'; PANEL = '#1a1a2e'; GRID = '#2a2a3e'
WHITE = '#e8e8f0'; CYAN  = '#00d4ff'; GREEN = '#00ff88'
AMBER = '#ffaa00'; RED   = '#ff4d6d'; PURPLE= '#c084fc'

# ══════════════════════════════════════════════════════════════
# 1. CARGAR CATÁLOGO
# ══════════════════════════════════════════════════════════════
def cargar_catalogo(perfil: str, cats_filtro: list = None) -> pd.DataFrame:
    fp = Path(f"results/oe4a_productos_roi_{perfil}.csv")
    if not fp.exists():
        raise FileNotFoundError(
            "Ejecuta primero: python scripts/oe4a_roi_calculator.py")

    df = pd.read_csv(fp, low_memory=False)
    cfg = PERFILES[perfil]

    # Compatibilidad v1/v2/v3
    if "ganancia_esperada" not in df.columns:
        if "ganancia_unitaria" in df.columns:
            df["ganancia_esperada"] = df["ganancia_unitaria"]
        else:
            raise KeyError("Regenera: python scripts/oe4a_roi_calculator.py")
    if "roi_esperado_pct" not in df.columns:
        df["roi_esperado_pct"] = df.get("roi_unitario_pct", 0)

    df = df[df["price_import_real_base"] <= cfg["max_precio_unit"]].copy()
    df["category"] = df["category"].fillna("unknown").str.lower().str.strip()

    if cats_filtro:
        cats_lower = [c.lower().strip() for c in cats_filtro]
        df = df[df["category"].isin(cats_lower)].copy()
        print(f"  Filtro categorías: {cats_lower}")

    df["titulo_norm"] = (df["title_local"].fillna("")
                          .str.lower().str.strip().str[:60])
    df = (df.sort_values("score_roi_ponderado", ascending=False)
             .drop_duplicates(subset=["titulo_norm"])
             .reset_index(drop=True))

    df = df.head(300).copy()
    print(f"  Productos candidatos (top 300, sin duplicados): {len(df):,}")
    return df

# ══════════════════════════════════════════════════════════════
# 2. OPTIMIZADOR v4 — FASE 1 + FASE 2A + FASE 2B
# ══════════════════════════════════════════════════════════════
def optimizar_portafolio(
    df: pd.DataFrame,
    inversion: float,
    perfil: str,
    min_skus_override: int = None,
) -> pd.DataFrame:
    cfg    = PERFILES[perfil]
    min_skus = min_skus_override if min_skus_override else cfg["min_skus"]

    print(f"\n  Optimizando portafolio (v4 — 3 sub-fases)...")
    print(f"  Inversión disponible : ${inversion:,.2f} USD")
    print(f"  Perfil               : {cfg['label']}")
    print(f"  Max unidades/SKU     : {cfg['max_unidades']}")
    print(f"  Max % por categoría  : {cfg['max_pct_categoria']*100:.0f}%")
    print(f"  Penalización soft    : si cat > {cfg['penalizacion_pct']*100:.0f}% del capital")
    print(f"  Min SKUs distintos   : {min_skus}")

    candidatos = df.sort_values("score_roi_ponderado", ascending=False).copy()

    # Seleccionar top categorías por ROI mediano
    cat_roi_med = (candidatos.groupby("category")["roi_esperado_pct"]
                              .median().sort_values(ascending=False))
    top_cats = cat_roi_med.head(max(cfg["min_cats"] + 2, 8)).index.tolist()

    print(f"\n  Top categorías elegibles:")
    for cat in top_cats:
        n   = len(candidatos[candidatos["category"]==cat])
        roi = cat_roi_med.get(cat, 0)
        print(f"    {cat:<20} ROI_esp med: {roi:+.1f}%  ({n} SKUs)")

    presupuesto = inversion
    cat_gasto   = {}
    sel         = {}   # titulo_norm → dict

    # ══════════════════════════════════════════════════════════
    # FASE 1 — 1 SKU por cada categoría top (diversificación base)
    # ══════════════════════════════════════════════════════════
    print(f"\n  FASE 1 — Diversificación base ({cfg['min_cats']} categorías)...")
    cats_cubiertas = set()

    for cat in top_cats:
        if len(cats_cubiertas) >= cfg["min_cats"]:
            break
        if presupuesto < 15:
            break
        cand_cat = candidatos[
            (candidatos["category"] == cat) &
            (~candidatos["titulo_norm"].isin(sel.keys()))
        ].head(1)
        if len(cand_cat) == 0:
            continue
        row   = cand_cat.iloc[0]
        costo = float(row["price_import_real_base"])
        if costo > presupuesto:
            continue
        _add(sel, row, 1)
        presupuesto -= costo
        cat_gasto[cat] = cat_gasto.get(cat, 0) + costo
        cats_cubiertas.add(cat)

    print(f"  Categorías cubiertas: {len(cats_cubiertas)} | "
          f"Presupuesto restante: ${presupuesto:,.2f}")

    # ══════════════════════════════════════════════════════════
    # FASE 2A — EXPLORACIÓN: 1 unidad por iteración hasta min_skus
    # Con penalización soft para categorías sobre-representadas
    # ══════════════════════════════════════════════════════════
    print(f"\n  FASE 2A — Exploración (meta: {min_skus} SKUs distintos)...")
    iter_2a = 0
    max_iter_2a = min_skus * 4

    while len(sel) < min_skus and presupuesto >= 15 and iter_2a < max_iter_2a:
        iter_2a += 1
        mejor_score = -np.inf
        mejor_row   = None
        mejor_cat   = ""

        for _, row in candidatos.iterrows():
            cat   = str(row["category"])
            costo = float(row["price_import_real_base"])
            tit   = str(row["titulo_norm"])

            if costo > presupuesto:
                continue
            ya_tenemos = sel.get(tit, {}).get("cantidad", 0)
            if ya_tenemos >= cfg["max_unidades"]:
                continue

            gasto_cat  = cat_gasto.get(cat, 0.0)
            limite_cat = inversion * cfg["max_pct_categoria"]
            if gasto_cat + costo > limite_cat:
                continue

            # Score base
            score = float(row["score_roi_ponderado"])

            # Penalización soft: si la categoría ya tiene mucho capital
            pct_cat = gasto_cat / inversion
            if pct_cat > cfg["penalizacion_pct"]:
                score *= 0.60   # penalizar 40% el score

            # Bonus por SKU nuevo (no está en sel)
            if tit not in sel:
                score *= 1.25   # bonus 25% por diversificación

            if score > mejor_score:
                mejor_score = score
                mejor_row   = row
                mejor_cat   = cat

        if mejor_row is None:
            break

        costo = float(mejor_row["price_import_real_base"])
        _add(sel, mejor_row, 1)
        presupuesto -= costo
        cat_gasto[mejor_cat] = cat_gasto.get(mejor_cat, 0) + costo

    print(f"  SKUs tras fase 2A: {len(sel)} | "
          f"Presupuesto restante: ${presupuesto:,.2f} | "
          f"Iteraciones: {iter_2a}")

    # ══════════════════════════════════════════════════════════
    # FASE 2B — CONCENTRACIÓN: maximizar ganancia con el resto
    # Ahora sí permite max unidades por SKU
    # ══════════════════════════════════════════════════════════
    print(f"\n  FASE 2B — Concentración (maximizar ganancia restante)...")
    iter_2b = 0
    max_iter_2b = 200

    while presupuesto >= 15 and iter_2b < max_iter_2b:
        iter_2b += 1
        mejor_gan = -np.inf
        mejor_row = None
        mejor_cant = 0
        mejor_cat  = ""

        for _, row in candidatos.iterrows():
            cat   = str(row["category"])
            costo = float(row["price_import_real_base"])
            tit   = str(row["titulo_norm"])

            if costo > presupuesto:
                continue
            ya_tenemos = sel.get(tit, {}).get("cantidad", 0)
            if ya_tenemos >= cfg["max_unidades"]:
                continue

            gasto_cat  = cat_gasto.get(cat, 0.0)
            limite_cat = inversion * cfg["max_pct_categoria"]
            espacio    = limite_cat - gasto_cat
            if espacio < costo:
                continue

            max_add = min(
                cfg["max_unidades"] - ya_tenemos,
                int(presupuesto // costo),
                int(espacio // costo),
            )
            if max_add <= 0:
                continue

            gan = float(row["ganancia_esperada"]) * max_add
            if gan > mejor_gan:
                mejor_gan  = gan
                mejor_row  = row
                mejor_cant = max_add
                mejor_cat  = cat

        if mejor_row is None:
            break

        costo = float(mejor_row["price_import_real_base"])
        _add(sel, mejor_row, mejor_cant)
        presupuesto -= costo * mejor_cant
        cat_gasto[mejor_cat] = cat_gasto.get(mejor_cat, 0) + costo * mejor_cant

    print(f"  SKUs finales: {len(sel)} | "
          f"Capital libre: ${presupuesto:,.2f} | "
          f"Iteraciones 2B: {iter_2b}")

    if not sel:
        print("  ⚠ Sin productos elegibles")
        return pd.DataFrame()

    resultado = pd.DataFrame(list(sel.values()))
    resultado = resultado.sort_values("ganancia_total_usd",
                                      ascending=False).reset_index(drop=True)
    return resultado


def _add(sel: dict, row, cantidad: int):
    """Añade o acumula unidades de un SKU en el dict de seleccionados."""
    tit   = str(row["titulo_norm"])
    costo = float(row["price_import_real_base"])
    if tit in sel:
        prev      = sel[tit]
        nueva_cant = prev["cantidad"] + cantidad
        sel[tit]  = {
            **prev,
            "cantidad"           : nueva_cant,
            "costo_total_usd"    : round(costo * nueva_cant, 2),
            "venta_total_usd"    : round(float(row["precio_venta_est"]) * nueva_cant, 2),
            "ganancia_total_usd" : round(float(row["ganancia_esperada"]) * nueva_cant, 2),
        }
    else:
        sel[tit] = {
            "titulo"            : str(row.get("title_local",""))[:60],
            "titulo_norm"       : tit,
            "categoria"         : str(row["category"]),
            "fuente_import"     : str(row.get("source_import","")),
            "costo_unit_usd"    : round(costo, 2),
            "precio_venta_usd"  : round(float(row["precio_venta_est"]), 2),
            "ganancia_unit_usd" : round(float(row["ganancia_esperada"]), 2),
            "roi_unitario_pct"  : round(float(row["roi_unitario_pct"]), 1),
            "roi_esperado_pct"  : round(float(row["roi_esperado_pct"]), 1),
            "cantidad"          : cantidad,
            "costo_total_usd"   : round(costo * cantidad, 2),
            "venta_total_usd"   : round(float(row["precio_venta_est"]) * cantidad, 2),
            "ganancia_total_usd": round(float(row["ganancia_esperada"]) * cantidad, 2),
            "score_ponderado"   : round(float(row["score_roi_ponderado"]), 4),
            "match_score"       : round(float(row.get("match_score", 0)), 1),
        }

# ══════════════════════════════════════════════════════════════
# 3. REPORTE
# ══════════════════════════════════════════════════════════════
def reportar(resultado: pd.DataFrame, inversion: float, perfil: str):
    cfg = PERFILES[perfil]

    capital_usado  = resultado["costo_total_usd"].sum()
    ganancia_total = resultado["ganancia_total_usd"].sum()
    venta_total    = resultado["venta_total_usd"].sum()
    roi_portafolio = ganancia_total / capital_usado * 100
    n_skus         = len(resultado)
    n_cats         = resultado["categoria"].nunique()
    n_unidades     = resultado["cantidad"].sum()
    capital_libre  = inversion - capital_usado

    print("\n" + "═"*76)
    print(f"  {cfg['emoji']}  PORTAFOLIO RECOMENDADO — {cfg['label'].upper()}")
    print("═"*76)
    print(f"\n  {'Inversión disponible':<34}: ${inversion:>10,.2f} USD")
    print(f"  {'Capital utilizado':<34}: ${capital_usado:>10,.2f} USD "
          f"({capital_usado/inversion*100:.1f}%)")
    print(f"  {'Capital libre':<34}: ${capital_libre:>10,.2f} USD")
    print(f"  {'─'*56}")
    print(f"  {'Venta total estimada':<34}: ${venta_total:>10,.2f} USD")
    print(f"  {'Ganancia esperada (c/rotación)':<34}: ${ganancia_total:>10,.2f} USD")
    print(f"  {'ROI del portafolio (esperado)':<34}: {roi_portafolio:>+10.1f}%")
    print(f"  {'─'*56}")
    print(f"  {'SKUs distintos':<34}: {n_skus:>10,}")
    print(f"  {'Categorías distintas':<34}: {n_cats:>10,}")
    print(f"  {'Unidades totales':<34}: {n_unidades:>10,}")

    print(f"\n  {'#':>3} {'Producto':<38} {'Cat':<14} "
          f"{'Cant':>4} {'Costo':>7} {'Venta':>7} "
          f"{'ROI_u':>6} {'ROI_esp':>8} {'Gan.esp':>8}")
    print(f"  {'─'*112}")
    for i, row in resultado.iterrows():
        titulo = str(row["titulo"])[:36]
        print(f"  {i+1:>3} {titulo:<38} {row['categoria']:<14} "
              f"{row['cantidad']:>4} "
              f"${row['costo_unit_usd']:>6.0f} "
              f"${row['precio_venta_usd']:>6.0f} "
              f"{row['roi_unitario_pct']:>+5.1f}% "
              f"{row['roi_esperado_pct']:>+7.1f}% "
              f"${row['ganancia_total_usd']:>7.0f}")

    print(f"\n  DISTRIBUCIÓN POR CATEGORÍA:")
    cat_sum = (resultado.groupby("categoria")
                        .agg(skus=("titulo","count"),
                             unidades=("cantidad","sum"),
                             capital=("costo_total_usd","sum"),
                             ganancia=("ganancia_total_usd","sum"))
                        .sort_values("capital", ascending=False))
    cat_sum["roi_cat"] = cat_sum["ganancia"] / cat_sum["capital"] * 100
    cat_sum["pct_cap"] = cat_sum["capital"] / capital_usado * 100

    print(f"  {'Categoría':<18} {'SKUs':>5} {'Unid':>5} "
          f"{'Capital':>9} {'%Cap':>6} {'Ganancia':>9} {'ROI_esp':>8}")
    print(f"  {'─'*68}")
    for cat, r in cat_sum.iterrows():
        flag = " ⚠" if r["pct_cap"] > cfg["max_pct_categoria"]*100 else ""
        print(f"  {cat:<18} {r['skus']:>5.0f} {r['unidades']:>5.0f} "
              f"${r['capital']:>8,.0f} {r['pct_cap']:>5.1f}% "
              f"${r['ganancia']:>8,.0f} {r['roi_cat']:>+7.1f}%{flag}")
    print(f"\n  {'─'*68}")
    print(f"  {'TOTAL':<18} {n_skus:>5} {n_unidades:>5} "
          f"${capital_usado:>8,.0f} {'100%':>6} "
          f"${ganancia_total:>8,.0f} {roi_portafolio:>+7.1f}%")
    print("═"*76)

    return {
        "inversion_disponible" : round(inversion, 2),
        "capital_utilizado"    : round(capital_usado, 2),
        "capital_libre"        : round(capital_libre, 2),
        "venta_total_estimada" : round(venta_total, 2),
        "ganancia_esperada"    : round(ganancia_total, 2),
        "roi_portafolio_pct"   : round(roi_portafolio, 2),
        "n_skus"               : int(n_skus),
        "n_categorias"         : int(n_cats),
        "n_unidades_total"     : int(n_unidades),
        "algoritmo"            : (
            "3 sub-fases: (1) diversificación base, "
            "(2A) exploración con penalización soft, "
            "(2B) concentración greedy para maximizar ganancia"
        ),
        "distribucion_cat"     : cat_sum.round(2).to_dict(orient="index"),
    }

# ══════════════════════════════════════════════════════════════
# 4. VISUALIZACIÓN
# ══════════════════════════════════════════════════════════════
def plot_portafolio(resultado: pd.DataFrame, resumen: dict,
                    perfil: str, inversion: float):
    cfg = PERFILES[perfil]
    fig = plt.figure(figsize=(20, 11))
    fig.patch.set_facecolor(DARK)
    fig.suptitle(
        f"Portafolio Óptimo — {cfg['label']} | "
        f"Inversión: ${inversion:,.0f} USD | "
        f"ROI Esperado: {resumen['roi_portafolio_pct']:+.1f}% | "
        f"{resumen['n_skus']} SKUs / {resumen['n_categorias']} categorías",
        color=WHITE, fontsize=13, fontweight="bold", y=0.99,
    )
    gs = fig.add_gridspec(2, 3, hspace=0.48, wspace=0.35)

    cats_uniq = resultado["categoria"].unique()
    palette   = [GREEN, CYAN, AMBER, RED, PURPLE,
                 "#f77f00","#06d6a0","#ffd166","#118ab2","#ef476f",
                 "#a8dadc","#457b9d","#e63946","#2a9d8f","#e9c46a"]
    cat_color = {c: palette[i % len(palette)] for i, c in enumerate(cats_uniq)}

    # Panel 1: Ganancia esperada por producto
    ax1 = fig.add_subplot(gs[0, :2]); ax1.set_facecolor(PANEL)
    top_n = min(18, len(resultado))
    top   = resultado.head(top_n)
    labels = [(f"{r['titulo'][:32]}… ×{r['cantidad']}"
               if len(str(r['titulo'])) > 32
               else f"{r['titulo']} ×{r['cantidad']}")
              for _, r in top.iterrows()]
    bar_colors = [cat_color[r["categoria"]] for _, r in top.iterrows()]
    bars = ax1.barh(range(len(top)), top["ganancia_total_usd"].values,
                    color=bar_colors, alpha=0.85)
    ax1.set_yticks(range(len(top)))
    ax1.set_yticklabels(labels, color=WHITE, fontsize=7.5)
    ax1.set_xlabel("Ganancia Esperada Total (USD)", color=WHITE)
    ax1.set_title(f"Top {top_n} Productos — Ganancia Esperada (ajustada por rotación)",
                  color=WHITE)
    ax1.tick_params(colors=WHITE); ax1.spines[:].set_color(GRID)
    ax1.grid(axis="x", alpha=0.2, color=WHITE)
    for bar, (_, row) in zip(bars, top.iterrows()):
        ax1.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2,
                 f"${row['ganancia_total_usd']:,.0f} "
                 f"(ROI {row['roi_esperado_pct']:+.0f}%)",
                 va="center", color=WHITE, fontsize=7)
    ax1.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:,.0f}"))

    # Panel 2: Pie capital por categoría
    ax2 = fig.add_subplot(gs[0, 2]); ax2.set_facecolor(PANEL)
    cat_data = (resultado.groupby("categoria")["costo_total_usd"]
                          .sum().sort_values(ascending=False))
    wedge_colors = [cat_color.get(c, CYAN) for c in cat_data.index]
    _, texts, autotexts = ax2.pie(
        cat_data.values, labels=cat_data.index,
        autopct="%1.1f%%", colors=wedge_colors, startangle=90,
        textprops={"color": WHITE, "fontsize": 7.5})
    for at in autotexts:
        at.set_color(DARK); at.set_fontsize(7)
    ax2.set_title("Capital por Categoría", color=WHITE)

    # Panel 3: ROI por categoría (doble barra)
    ax3 = fig.add_subplot(gs[1, 0]); ax3.set_facecolor(PANEL)
    cat_roi_u = (resultado.groupby("categoria")
                           .apply(lambda x: np.average(x["roi_unitario_pct"],
                                                       weights=x["costo_total_usd"]))
                           .sort_values())
    cat_roi_e = (resultado.groupby("categoria")
                           .apply(lambda x: np.average(x["roi_esperado_pct"],
                                                       weights=x["costo_total_usd"]))
                           .reindex(cat_roi_u.index))
    y_pos = np.arange(len(cat_roi_u))
    ax3.barh(y_pos - 0.2, cat_roi_u.values, 0.35, color=AMBER, alpha=0.7, label="ROI unitario")
    ax3.barh(y_pos + 0.2, cat_roi_e.values, 0.35, color=GREEN, alpha=0.85, label="ROI esperado")
    ax3.set_yticks(y_pos)
    ax3.set_yticklabels(cat_roi_u.index, color=WHITE, fontsize=8)
    ax3.set_xlabel("ROI %", color=WHITE)
    ax3.set_title("ROI por Categoría", color=WHITE)
    ax3.tick_params(colors=WHITE); ax3.spines[:].set_color(GRID)
    ax3.grid(axis="x", alpha=0.2, color=WHITE)
    ax3.legend(facecolor=PANEL, labelcolor=WHITE, edgecolor=GRID, fontsize=8)
    ax3.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"{v:.0f}%"))

    # Panel 4: Scatter costo vs ganancia
    ax4 = fig.add_subplot(gs[1, 1]); ax4.set_facecolor(PANEL)
    for cat in cats_uniq:
        sub = resultado[resultado["categoria"]==cat]
        ax4.scatter(sub["costo_total_usd"], sub["ganancia_total_usd"],
                    color=cat_color[cat], s=sub["cantidad"]*25+20,
                    alpha=0.8, label=cat, edgecolors="white", linewidths=0.3)
    ax4.set_xlabel("Capital Invertido (USD)", color=WHITE)
    ax4.set_ylabel("Ganancia Esperada (USD)", color=WHITE)
    ax4.set_title("Capital vs Ganancia\n(tamaño = unidades)", color=WHITE)
    ax4.tick_params(colors=WHITE); ax4.spines[:].set_color(GRID)
    ax4.grid(alpha=0.15, color=WHITE)
    ax4.legend(facecolor=PANEL, labelcolor=WHITE, edgecolor=GRID, fontsize=7, ncol=2)
    ax4.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:,.0f}"))
    ax4.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:,.0f}"))

    # Panel 5: KPIs
    ax5 = fig.add_subplot(gs[1, 2]); ax5.set_facecolor(PANEL); ax5.axis("off")
    kpis = [
        ("💰 Inversión",        f"${resumen['inversion_disponible']:,.0f}"),
        ("📦 Capital usado",    f"${resumen['capital_utilizado']:,.0f} "
                                f"({resumen['capital_utilizado']/resumen['inversion_disponible']*100:.0f}%)"),
        ("🏷️  Capital libre",    f"${resumen['capital_libre']:,.0f}"),
        ("", ""),
        ("📈 Venta estimada",   f"${resumen['venta_total_estimada']:,.0f}"),
        ("✅ Ganancia esperada", f"${resumen['ganancia_esperada']:,.0f}"),
        ("🎯 ROI esperado",     f"{resumen['roi_portafolio_pct']:+.1f}%"),
        ("", ""),
        ("📦 SKUs distintos",   f"{resumen['n_skus']}"),
        ("🗂️  Categorías",       f"{resumen['n_categorias']}"),
        ("🔢 Unidades total",   f"{resumen['n_unidades_total']}"),
    ]
    y_pos = 0.97
    for label, value in kpis:
        if label == "":
            y_pos -= 0.035; continue
        color_v = (GREEN if "ROI" in label or "Ganancia" in label
                   else CYAN if "Venta" in label else WHITE)
        ax5.text(0.04, y_pos, label, transform=ax5.transAxes,
                 color=WHITE, fontsize=9, va="top")
        ax5.text(0.96, y_pos, value, transform=ax5.transAxes,
                 color=color_v, fontsize=9, va="top", ha="right", fontweight="bold")
        y_pos -= 0.085

    fname = f"figures/oe4b_portafolio_{perfil}_{int(inversion)}.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight", facecolor=DARK)
    plt.close()
    print(f"\n  ✓ {fname}")
    return fname

# ══════════════════════════════════════════════════════════════
# 5. GUARDAR
# ══════════════════════════════════════════════════════════════
def guardar(resultado: pd.DataFrame, resumen: dict,
            perfil: str, inversion: float, figura: str):
    base = f"results/oe4b_portafolio_{perfil}_{int(inversion)}"
    resultado.drop(columns=["titulo_norm"], errors="ignore").to_csv(
        f"{base}.csv", index=False)
    print(f"  ✓ {base}.csv")
    output = {
        "oe": "OE4-B / OE10", "version": "v4",
        "timestamp": datetime.now().isoformat(),
        "perfil": perfil, "resumen": resumen, "figura": figura,
        "productos": (resultado.drop(columns=["titulo_norm"], errors="ignore")
                               .to_dict(orient="records")),
    }
    with open(f"{base}.json","w",encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"  ✓ {base}.json")

# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Optimizador portafolio v4")
    parser.add_argument("--inversion", type=float, default=5000.0)
    parser.add_argument("--perfil",    type=str,   default="moderado",
                        choices=["conservador","moderado","agresivo"])
    parser.add_argument("--cats",      type=str,   default=None)
    parser.add_argument("--min_skus",  type=int,   default=None)
    args = parser.parse_args()

    cats = [c.strip() for c in args.cats.split(",")] if args.cats else None

    print("=" * 72)
    print("  OE4-B / OE10 v4: Optimizador de Portafolio (3 sub-fases)")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 72)
    print(f"\n  Inversión : ${args.inversion:,.2f} USD")
    print(f"  Perfil    : {args.perfil}")
    if cats:
        print(f"  Categorías: {cats}")

    df        = cargar_catalogo(args.perfil, cats)
    resultado = optimizar_portafolio(df, args.inversion, args.perfil, args.min_skus)

    if len(resultado) > 0:
        resumen = reportar(resultado, args.inversion, args.perfil)
        figura  = plot_portafolio(resultado, resumen, args.perfil, args.inversion)
        guardar(resultado, resumen, args.perfil, args.inversion, figura)
    else:
        print("  ⚠ Sin portafolio. Reduce --inversion o cambia --perfil.")