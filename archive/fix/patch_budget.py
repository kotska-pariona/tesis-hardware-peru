#!/usr/bin/env python3
"""
patch_budget.py — Agrega modulo de presupuesto a pe5_agent.py
Estrategia: C (CLI + interactivo) + X (proporcional al score)
"""
import pathlib, re, textwrap

p = pathlib.Path("agent/pe5_agent.py")
txt = p.read_text(encoding="utf-8")
original = txt

# ══════════════════════════════════════════════════════════════
# BLOQUE 1 — import json
# ══════════════════════════════════════════════════════════════
if "import json" not in txt:
    txt = txt.replace("import argparse", "import argparse\nimport json", 1)
    print("  OK BLOQUE 1 — import json agregado")
else:
    print("  OK BLOQUE 1 — import json ya existe")

# ══════════════════════════════════════════════════════════════
# BLOQUE 2 — Constantes de presupuesto
# ══════════════════════════════════════════════════════════════
BUDGET_CONSTANTS = (
    "\n# -- Presupuesto --\n"
    "BUDGET_CONFIG_PATH = pathlib.Path('config/budget.json')\n"
    "MAX_UNITS_PER_SKU  = 3\n"
    "MIN_SCORE_TO_BUY   = 60.0\n"
)

if "MAX_UNITS_PER_SKU" not in txt:
    txt = re.sub(
        r"(MIN_POINTS_TREND\s*=\s*\d+[^\n]*\n)",
        r"\1" + BUDGET_CONSTANTS,
        txt, count=1
    )
    print("  OK BLOQUE 2 — constantes de presupuesto agregadas")
else:
    print("  OK BLOQUE 2 — constantes ya existen")

# ══════════════════════════════════════════════════════════════
# BLOQUE 3 — Funciones get_budget / allocate_budget
# ══════════════════════════════════════════════════════════════
ALLOCATE_FUNC = textwrap.dedent("""
    # ─────────────────────────────────────────────────────────────
    def get_budget(cli_budget):
        \"\"\"Obtiene presupuesto: CLI > config guardada > interactivo.\"\"\"
        if cli_budget is not None and cli_budget > 0:
            _save_budget(cli_budget)
            return cli_budget

        if BUDGET_CONFIG_PATH.exists():
            try:
                data = json.loads(BUDGET_CONFIG_PATH.read_text())
                saved = float(data.get("budget", 0))
                if saved > 0:
                    log.info(f"[BUDGET] Presupuesto guardado: S/. {saved:,.2f}")
                    resp = input(
                        f"  Usar presupuesto guardado S/. {saved:,.2f}? [S/n]: "
                    ).strip().lower()
                    if resp in ("", "s", "si", "y", "yes"):
                        return saved
            except Exception:
                pass

        while True:
            try:
                raw = input("  Cuanto tienes para invertir? S/. ").strip()
                budget = float(raw.replace(",", ""))
                if budget > 0:
                    _save_budget(budget)
                    return budget
                print("  Ingresa un monto mayor a 0.")
            except ValueError:
                print("  Ingresa un numero valido (ej: 5000 o 5000.50).")


    def _save_budget(budget):
        \"\"\"Persiste el presupuesto en config/budget.json.\"\"\"
        BUDGET_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        BUDGET_CONFIG_PATH.write_text(
            json.dumps({"budget": budget, "currency": "PEN"}, indent=2)
        )


    def allocate_budget(decisions, budget):
        \"\"\"
        Asigna unidades de compra proporcionales al score (estrategia X).

        units_i = floor( (score_i / sum_scores) * (budget / price_i) )
        min 1 unidad si score >= MIN_SCORE_TO_BUY
        max MAX_UNITS_PER_SKU unidades por SKU
        \"\"\"
        for d in decisions:
            d["units_to_buy"]    = 0
            d["budget_assigned"] = 0.0
            d["budget_pct"]      = 0.0

        buys = [
            d for d in decisions
            if d.get("decision") == "BUY"
            and float(d.get("price_pen", 0) or 0) > 0
            and float(d.get("score", 0) or 0) >= MIN_SCORE_TO_BUY
        ]

        if not buys:
            log.warning("[BUDGET] Sin productos BUY elegibles.")
            return decisions

        sum_scores = sum(float(d["score"]) for d in buys)
        remaining  = budget

        # Primera pasada — proporcional
        for d in sorted(buys, key=lambda x: float(x["score"]), reverse=True):
            if remaining <= 0:
                break
            price = float(d["price_pen"])
            score = float(d["score"])
            budget_share = (score / sum_scores) * budget
            units = int(budget_share / price)
            units = max(1, min(units, MAX_UNITS_PER_SKU))
            cost  = units * price
            if cost <= remaining:
                d["units_to_buy"]    = units
                d["budget_assigned"] = round(cost, 2)
                remaining -= cost
            else:
                units = int(remaining / price)
                if units >= 1:
                    d["units_to_buy"]    = units
                    d["budget_assigned"] = round(units * price, 2)
                    remaining -= units * price

        # Segunda pasada — sobrante a top SKUs
        for d in sorted(
            [x for x in buys if x["units_to_buy"] < MAX_UNITS_PER_SKU],
            key=lambda x: float(x["score"]), reverse=True
        ):
            if remaining <= 0:
                break
            price = float(d["price_pen"])
            add   = min(int(remaining / price), MAX_UNITS_PER_SKU - d["units_to_buy"])
            if add >= 1:
                d["units_to_buy"]    += add
                d["budget_assigned"]  = round(d["budget_assigned"] + add * price, 2)
                remaining -= add * price

        total_assigned = sum(d["budget_assigned"] for d in buys)
        for d in buys:
            d["budget_pct"] = round(d["budget_assigned"] / budget * 100, 2)

        log.info(
            f"[BUDGET] Total S/. {budget:,.2f} | "
            f"Asignado S/. {total_assigned:,.2f} | "
            f"Sobrante S/. {remaining:,.2f} | "
            f"SKUs: {len([d for d in buys if d['units_to_buy'] > 0])}"
        )
        return decisions

""")

if "def allocate_budget(" not in txt:
    txt = txt.replace("def compute_decision(", ALLOCATE_FUNC + "\ndef compute_decision(", 1)
    print("  OK BLOQUE 3 — funciones get_budget/allocate_budget agregadas")
else:
    print("  OK BLOQUE 3 — allocate_budget ya existe")

# ══════════════════════════════════════════════════════════════
# BLOQUE 4 — argumento --budget en argparse
# ══════════════════════════════════════════════════════════════
ARG_BUDGET = (
    '    parser.add_argument(\n'
    '        "--budget", type=float, default=None,\n'
    '        help="Presupuesto en S/. (ej: --budget 5000)"\n'
    '    )\n'
    '    parser.add_argument("--output"'
)

if '"--budget"' not in txt:
    if 'parser.add_argument("--output"' in txt:
        txt = txt.replace('    parser.add_argument("--output"', ARG_BUDGET, 1)
        print("  OK BLOQUE 4 — argumento --budget agregado")
    else:
        print("  WARN BLOQUE 4 — ancla --output no encontrada")
else:
    print("  OK BLOQUE 4 — --budget ya existe")

# ══════════════════════════════════════════════════════════════
# BLOQUE 5 — Llamada en main() antes de df.to_csv()
# ══════════════════════════════════════════════════════════════
BUDGET_CALL = (
    "    # -- Asignacion de presupuesto --\n"
    "    budget = get_budget(args.budget)\n"
    "    log.info(f'[BUDGET] Presupuesto total: S/. {budget:,.2f}')\n"
    "    records = allocate_budget(records, budget)\n\n"
    "    df.to_csv("
)

if "get_budget(args.budget)" not in txt:
    if "    df.to_csv(" in txt:
        txt = txt.replace("    df.to_csv(", BUDGET_CALL, 1)
        print("  OK BLOQUE 5 — llamadas en main() agregadas")
    else:
        print("  WARN BLOQUE 5 — ancla df.to_csv() no encontrada")
else:
    print("  OK BLOQUE 5 — llamadas ya existen")

# ══════════════════════════════════════════════════════════════
# GUARDAR
# ══════════════════════════════════════════════════════════════
if txt != original:
    p.write_text(txt, encoding="utf-8")
    print("\n  OK pe5_agent.py guardado con modulo de presupuesto")
else:
    print("\n  WARN Sin cambios — revisa las anclas manualmente")
