import pathlib as _pl
p = _pl.Path("agent/pe5_agent.py")
src = p.read_text(encoding="utf-8")
OLD = "BUDGET_CONFIG_PATH = pathlib.Path('config/budget.json')"
NEW = "BUDGET_CONFIG_PATH = Path('config/budget.json')"
if OLD in src:
    src = src.replace(OLD, NEW, 1)
    print("  OK  pathlib.Path → Path")
else:
    print("  WARN  anchor no encontrado")
p.write_text(src, encoding="utf-8")
