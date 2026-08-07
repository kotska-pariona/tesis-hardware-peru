import pathlib as _pl
lines = _pl.Path("agent/pe5_agent.py").read_text(encoding="utf-8").splitlines()

print("=== run() loop de categorías (610-630) ===")
for i, l in enumerate(lines[609:632], start=610):
    print(f"{i:4d} | {l}")

print("\n=== filtro post-run (898-915) ===")
for i, l in enumerate(lines[897:918], start=898):
    print(f"{i:4d} | {l}")
