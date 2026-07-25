import pathlib

p = pathlib.Path("agent/pe5_agent.py")
src = p.read_text(encoding="utf-8")
lines = src.splitlines()

# Buscar donde quedaron get_budget / allocate_budget en main()
print("=== Ocurrencias de budget en el archivo ===")
for i, line in enumerate(lines, start=1):
    if any(x in line for x in ["get_budget", "allocate_budget", "BUDGET", "budget ="]):
        print(f"{i:4d} | {repr(line)}")
