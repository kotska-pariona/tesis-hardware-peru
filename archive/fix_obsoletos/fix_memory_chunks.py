import pathlib as _pl

p = _pl.Path("agent/pe5_agent.py")
src = p.read_text(encoding="utf-8")

# ── FIX: limitar filas por categoría antes del .copy() ──────────────────────
# Buscar el slice que causa el OOM
OLD = '''    ].copy()'''

# El patrón real está en _analyze_category — buscar contexto
import re

# Buscar la línea del filtro de categoría + copy
pattern = r'(cat_df\s*=\s*df\[.*?\]\.copy\(\))'
matches = list(re.finditer(pattern, src, re.DOTALL))
print(f"  INFO  matches encontrados: {len(matches)}")
for m in matches:
    print(f"    → pos {m.start()}: {repr(m.group()[:80])}")
