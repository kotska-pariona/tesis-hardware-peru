import json

with open("results/oe9_resumen_nsga3.json","r",encoding="utf-8") as f:
    j=json.load(f)

print("=== OE9 thresholds / config ===")
print("rj_max (resumen):", j.get("rj_max", None))
print("RJ_MAX (resumen, si existe):", j.get("RJ_MAX", None))

inp=j.get("input",{})
if isinstance(inp, dict):
    # imprime candidatos comunes
    for k in inp.keys():
        lk=str(k).lower()
        if "rj" in lk or "rj_max" in lk or "rjmax" in lk or "rj_" in lk or "risk" in lk or "riesg" in lk:
            print("input:", k, "=", inp[k])
