import pathlib as _pl
lines = _pl.Path("agent/pe5_agent.py").read_text(encoding="utf-8").splitlines()

print("=== run() — buscar donde se usa args.category / self.category ===")
for i, l in enumerate(lines, start=1):
    if "category" in l.lower() and any(k in l for k in ["args.", "self.cat", "filter", "==", "in "]):
        print(f"{i:4d} | {l}")
