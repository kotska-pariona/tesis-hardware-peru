import pathlib

p = pathlib.Path("agent/pe5_agent.py")
src = p.read_text(encoding="utf-8")

ANCHOR = "    df    = agent.run()\n"

BUDGET_BLOCK = """\
    df    = agent.run()

    # -- Asignacion de presupuesto --
    budget  = get_budget(args.budget)
    log.info(f'[BUDGET] Presupuesto total: S/. {budget:,.2f}')
    records = df.to_dict('records')
    records = allocate_budget(records, budget)
    df      = pd.DataFrame(records)

"""

if ANCHOR in src:
    src = src.replace(ANCHOR, BUDGET_BLOCK, 1)
    print("  OK  bloque budget insertado despues de agent.run()")
else:
    print("  WARN  anchor no encontrado")

p.write_text(src, encoding="utf-8")
print("  OK  guardado")
