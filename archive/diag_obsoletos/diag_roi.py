import pathlib as _pl

lines = _pl.Path("agent/pe5_agent.py").read_text(encoding="utf-8").splitlines()

print("=== Todo el bloque _analyze_category / price_local (líneas 630-780) ===")
for i, l in enumerate(lines[629:780], start=630):
    print(f"  {i:4d} | {l}")
