import pathlib as _pl

lines = _pl.Path("agent/pe5_agent.py").read_text(encoding="utf-8").splitlines()

# Buscar bloque FIX-16
print("=== FIX-16: Filtro local + matching percentil (contexto) ===")
for i, l in enumerate(lines, start=1):
    if "FIX-16" in l or "_local_percentiles" in l or "_anchors" in l or "LOCAL_PRICE_MIN_PEN" in l:
        # Mostrar 2 líneas de contexto
        start = max(0, i-2)
        end   = min(len(lines), i+2)
        for j in range(start, end):
            marker = ">>>" if j == i-1 else "   "
            print(f"  {marker} {j+1:4d} | {lines[j]}")
        print()
