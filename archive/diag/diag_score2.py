import pathlib as _pl

p = _pl.Path("agent/pe5_agent.py")
lines = p.read_text(encoding="utf-8").splitlines()

# Ver roi_norm y pesos W_ROI etc (lineas 400-455)
print("=== ROI_NORM + PESOS (lineas 400-455) ===")
for i, line in enumerate(lines[399:452], start=400):
    print(f"{i:4d} | {line}")
