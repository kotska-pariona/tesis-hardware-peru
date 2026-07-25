import pathlib as _pl
p = _pl.Path("agent/pe5_agent.py")
lines = p.read_text(encoding="utf-8").splitlines()

print("=== DEMANDA / ROTACION / STOCK (buscar keywords) ===")
for i, line in enumerate(lines, start=1):
    if any(x in line.lower() for x in [
        "demand", "rotation", "stock", "dias", "days",
        "ventas", "sales", "units", "max_unit", "min_unit"
    ]):
        print(f"{i:4d} | {line}")
