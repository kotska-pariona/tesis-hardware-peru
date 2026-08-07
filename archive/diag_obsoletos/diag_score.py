import pathlib as _pl

p = _pl.Path("agent/pe5_agent.py")
lines = p.read_text(encoding="utf-8").splitlines()

# Ver contexto completo alrededor del score (lineas 450-490)
print("=== CALCULO DE SCORE (lineas 450-490) ===")
for i, line in enumerate(lines[449:490], start=450):
    print(f"{i:4d} | {line}")

# Ver linea 81 (BUDGET_CONFIG_PATH)
print("\n=== LINEA 81 ===")
for i, line in enumerate(lines[78:85], start=79):
    print(f"{i:4d} | {line}")
