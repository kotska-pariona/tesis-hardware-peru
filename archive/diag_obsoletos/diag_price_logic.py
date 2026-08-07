import pathlib as _pl
lines = _pl.Path("agent/pe5_agent.py").read_text(encoding="utf-8").splitlines()

print("=== price_local_pen — cómo se asigna ===")
for i, l in enumerate(lines, start=1):
    if any(k in l for k in ["price_local", "local_pen", "precio_local", "local_price", "med_local", "median", "mean"]):
        print(f"{i:4d} | {l}")

print("\n=== _analyze_category — primeras 80 líneas ===")
in_fn = False
count = 0
for i, l in enumerate(lines, start=1):
    if "def _analyze_category" in l:
        in_fn = True
    if in_fn:
        print(f"{i:4d} | {l}")
        count += 1
        if count > 80:
            break
