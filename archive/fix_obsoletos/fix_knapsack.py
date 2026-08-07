import pathlib as _pl, re

p = _pl.Path("agent/pe5_agent.py")
src = p.read_text(encoding="utf-8")

# ── FIX 1: agregar --budget al argparse ──────────────────────────────────────
OLD_ARG = '    parser.add_argument("--top",    type=int,   default=20)'
NEW_ARG = (
    '    parser.add_argument("--top",    type=int,   default=20)\n'
    '    parser.add_argument("--budget", type=float, default=None,\n'
    '                        help="Presupuesto total en S/. (opcional)")'
)
if OLD_ARG in src:
    src = src.replace(OLD_ARG, NEW_ARG, 1)
    print("  OK  --budget agregado al argparse")
else:
    print("  WARN  anchor argparse no encontrado")

# ── FIX 2: reemplazar allocate_budget completo por knapsack ──────────────────
OLD_ALLOC = '''def allocate_budget(decisions: list[dict], budget: float) -> list[dict]:'''

# Buscar inicio y fin de la función
start = src.find("def allocate_budget(")
if start == -1:
    print("  WARN  allocate_budget no encontrado")
else:
    # Encontrar el siguiente 'def ' al mismo nivel
    next_def = src.find("\ndef ", start + 1)
    old_func = src[start:next_def]

    new_func = '''def allocate_budget(decisions: list[dict], budget: float) -> list[dict]:
    """
    [FIX-6] Knapsack greedy por ROI/precio para maximizar retorno
    sin sobrestock.

    Estrategia:
      1. Filtrar solo BUY con score >= MIN_SCORE_TO_BUY
      2. Calcular demanda_max por SKU desde available_qty / sold_quantity
      3. Ordenar por roi_pen_por_sol (ROI S/. por cada S/. invertido) DESC
      4. Asignar unidades greedy hasta agotar presupuesto o demanda
    """
    import math as _math

    HORIZONTE_DIAS = 30   # ventana de reposición en días

    buys = [d for d in decisions
            if d["decision"] == "BUY" and float(d.get("score", 0)) >= MIN_SCORE_TO_BUY]

    if not buys or budget <= 0:
        return decisions

    # Inicializar campos
    for d in decisions:
        d.setdefault("units_to_buy",    0)
        d.setdefault("budget_assigned", 0.0)
        d.setdefault("budget_pct",      0.0)

    # Calcular demanda máxima por SKU
    for d in buys:
        avail = int(d.get("available_qty") or 0)
        sold  = float(d.get("sold_quantity") or 0)
        # Unidades vendibles en horizonte (mínimo 1, máximo available_qty o MAX_UNITS_PER_SKU)
        demand = max(1, _math.floor((sold / 30.0) * HORIZONTE_DIAS)) if sold > 0 else 1
        d["_demand_max"] = min(
            max(avail, 1) if avail > 0 else MAX_UNITS_PER_SKU,
            MAX_UNITS_PER_SKU,
            demand
        )
        # ROI en S/. por cada S/. invertido (eficiencia de capital)
        price = float(d.get("price_pen") or 1)
        roi_pct = float(d.get("roi_pct") or 0)
        d["_roi_efficiency"] = (roi_pct / 100.0) / price if price > 0 else 0.0

    # Ordenar por eficiencia de capital DESC
    buys_sorted = sorted(buys, key=lambda x: x["_roi_efficiency"], reverse=True)

    remaining = budget
    for d in buys_sorted:
        if remaining <= 0:
            break
        price    = float(d.get("price_pen") or 0)
        if price <= 0:
            continue
        max_units = d["_demand_max"]
        affordable = int(remaining / price)
        units = min(max_units, affordable)
        if units >= 1:
            d["units_to_buy"]    = units
            d["budget_assigned"] = round(units * price, 2)
            d["budget_pct"]      = 0.0   # se recalcula abajo
            remaining -= units * price

    total_assigned = sum(d["budget_assigned"] for d in buys)
    for d in buys:
        d["budget_pct"] = round(d["budget_assigned"] / budget * 100, 2) if budget > 0 else 0.0

    log.info(
        f"[BUDGET-KNAPSACK] Total S/. {budget:,.2f} | "
        f"Asignado S/. {total_assigned:,.2f} | "
        f"Sobrante S/. {remaining:,.2f} | "
        f"SKUs con compra: {len([d for d in buys if d['units_to_buy'] > 0])}"
    )
    return decisions

'''
    src = src[:start] + new_func + src[next_def:]
    print("  OK  allocate_budget reemplazado por knapsack greedy")

p.write_text(src, encoding="utf-8")
print("  OK  guardado")
