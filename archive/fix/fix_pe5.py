import pathlib

p = pathlib.Path("agent/pe5_agent.py")
txt = p.read_text(encoding="utf-8")
original = txt

# ── FIX 1 — bloque else obsolescencia (1.0 - score → lógica correcta) ──
old1 = """            else:
                sig.score  = 1.0 - score
                sig.signal = "LIQUIDATE" if sig.score >= OBS_THRESHOLD else "KEEP\""""
new1 = """            elif "TRANSIC" in label or label == "LABEL_1":
                # Transición → score reducido
                sig.score  = score * 0.5
                sig.signal = "LIQUIDATE" if sig.score >= OBS_THRESHOLD else "KEEP"

            else:
                # Vigente (LABEL_0) → no obsoleto
                sig.score  = 0.0
                sig.signal = "KEEP\""""

# ── FIX 2 — trend_score 80.0 fijo → eliminarlo (el else lo maneja) ──
old2 = """        trend_score = 80.0
        if trend.at_minimum:
            trend_score = 100.0
            reasons.append("precio en mínimo histórico")"""
new2 = """        if trend.at_minimum:
            trend_score = 100.0
            reasons.append("precio en mínimo histórico")
        else:
            trend_score = 70.0"""

# ── FIX 3 — UNKNOWN 50.0 → 40.0 ──
old3 = "        trend_score = 50.0"
new3 = "        trend_score = 40.0"

fixes = [
    ("FIX1 — obs else block",   old1, new1),
    ("FIX2 — trend_score 80→70", old2, new2),
    ("FIX3 — unknown 50→40",    old3, new3),
]

for nombre, old, new in fixes:
    if old in txt:
        txt = txt.replace(old, new, 1)
        print(f"  ✅ {nombre}")
    else:
        print(f"  ❌ {nombre} — NO ENCONTRADO (revisar manualmente)")

if txt != original:
    p.write_text(txt, encoding="utf-8")
    print("\n  ✅ pe5_agent.py guardado con fixes aplicados")
else:
    print("\n  ⚠️  Sin cambios — verifica el archivo manualmente")
