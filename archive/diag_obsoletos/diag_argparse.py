import pathlib as _pl
p = _pl.Path("agent/pe5_agent.py")
lines = p.read_text(encoding="utf-8").splitlines()

print("=== ARGPARSE (buscar add_argument) ===")
for i, line in enumerate(lines, start=1):
    if "add_argument" in line or "ArgumentParser" in line:
        print(f"{i:4d} | {line}")
