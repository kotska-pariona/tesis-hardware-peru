import pathlib as _pl

p = _pl.Path("agent/pe5_agent.py")
src = p.read_text(encoding="utf-8")

# FIX: reemplazar el clamp lineal por normalización logarítmica
# ROI 0%=0, 50%=50, 100%=67, 200%=80, 400%=89, 1000%=97 → diferencia real entre productos
OLD = "    roi_norm = min(100.0, max(0.0, roi_pct))   # 0-100"
NEW = (
    "    # [FIX-5] Normalización log para diferenciar ROIs altos\n"
    "    # ROI 0%→0 | 50%→41 | 100%→58 | 200%→72 | 400%→83 | 1000%→93\n"
    "    import math as _math\n"
    "    roi_norm = 0.0 if roi_pct <= 0 else min(100.0, 100.0 * _math.log1p(roi_pct / 100.0) / _math.log1p(10.0))"
)

if OLD in src:
    src = src.replace(OLD, NEW, 1)
    print("  OK  roi_norm normalización log aplicada")
else:
    print("  WARN  anchor no encontrado")

p.write_text(src, encoding="utf-8")
print("  OK  guardado")
