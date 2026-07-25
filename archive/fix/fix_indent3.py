import pathlib, re

p = pathlib.Path("agent/pe5_agent.py")
src = p.read_text(encoding="utf-8")

# ── 1. Limpiar el bloque mal insertado dentro de _save() ──────────────────────
# Eliminar las 4 líneas del budget que quedaron en _save (líneas ~759-762)
src = src.replace(
    "        # CSV\n"
    "        # -- Asignacion de presupuesto --\n"
    "    budget = get_budget(args.budget)\n"
    "    log.info(f'[BUDGET] Presupuesto total: S/. {budget:,.2f}')\n"
    "    records = allocate_budget(records, budget)\n",
    "        # CSV\n"
)

# ── 2. Corregir indentación de df.to_csv y lo que sigue dentro de _save() ─────
src = src.replace(
    "    df.to_csv(DECISIONS_CSV, index=False, encoding=\"utf-8\")\n",
    "        df.to_csv(DECISIONS_CSV, index=False, encoding=\"utf-8\")\n"
)

# ── 3. Insertar budget ANTES de agent._save() en main() ───────────────────────
ANCHOR = "    agent._save(df)"
BUDGET_BLOCK = (
    "    # -- Asignacion de presupuesto --\n"
    "    budget = get_budget(args.budget)\n"
    "    log.info(f'[BUDGET] Presupuesto total: S/. {budget:,.2f}')\n"
    "    records = allocate_budget(records, budget)\n"
    "\n"
)

if ANCHOR in src:
    src = src.replace(ANCHOR, BUDGET_BLOCK + ANCHOR, 1)
    print("  OK  bloque budget reubicado antes de agent._save()")
else:
    print("  WARN  ancla 'agent._save(df)' no encontrada — busca manualmente")

p.write_text(src, encoding="utf-8")
print("  OK  pe5_agent.py guardado")
