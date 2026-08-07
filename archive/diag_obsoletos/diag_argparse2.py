import pathlib as _pl
p = _pl.Path("agent/pe5_agent.py")
lines = p.read_text(encoding="utf-8").splitlines()

print("=== ARGPARSE COMPLETO (lineas 858-880) ===")
for i, line in enumerate(lines[857:882], start=858):
    print(f"{i:4d} | {line}")
