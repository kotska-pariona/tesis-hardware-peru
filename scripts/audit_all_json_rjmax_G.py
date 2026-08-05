import os, json, re

ROOT="results"

def find_rjmax_in_json(path):
    try:
        with open(path,"r",encoding="utf-8") as f:
            j=json.load(f)
    except:
        return None
    vals={}
    def walk(x):
        if isinstance(x, dict):
            for k,v in x.items():
                lk=str(k).lower()
                if "rj_max" in lk or (lk=="rjmax") or ("rjmax" in lk):
                    vals[str(k)] = v
                if lk.endswith("rj_max") or "rj_max" in lk:
                    vals[str(k)] = v
                walk(v)
        elif isinstance(x, list):
            for v in x[:200]:
                walk(v)
    walk(j)
    return vals if vals else None

hits=[]
for fn in os.listdir(ROOT):
    if not fn.endswith(".json"):
        continue
    p=os.path.join(ROOT,fn)
    vals=find_rjmax_in_json(p)
    if vals:
        hits.append((fn, vals))

print("=== JSON que contienen rj_max/RJ_MAX (nombre exacto en el json) ===")
for fn, vals in sorted(hits, key=lambda x:x[0].lower()):
    print(fn, "->", vals)

print("\nTotal:", len(hits))
