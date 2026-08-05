import os, re, json
import pandas as pd

ROOT="results"

PAT = re.compile(r"(rj|r_j|riesg|risk|obsole|obsol|RJ_MAX|g3|constraint|viol|factib)", re.I)

def sniff_json(path):
    with open(path,"r",encoding="utf-8") as f:
        obj=json.load(f)
    hits=set()
    def walk(x):
        if isinstance(x, dict):
            for k,v in x.items():
                if PAT.search(str(k)):
                    hits.add(k)
                walk(v)
        elif isinstance(x, list):
            for v in x[:200]:
                walk(v)
    walk(obj)
    return hits, obj

def sniff_csv(path):
    df=pd.read_csv(path)
    cols=[c for c in df.columns if PAT.search(str(c))]
    return cols, df.head(2)

print("=== AUDIT V2: campos parecidos a rj/g3/constraint ===")
rows=[]
for fn in os.listdir(ROOT):
    p=os.path.join(ROOT,fn)
    if fn.endswith(".json"):
        try:
            hits,_=sniff_json(p)
            if hits:
                rows.append((fn,"json",len(hits),";".join(list(hits)[:30])))
        except Exception as e:
            print("JSON error:", fn, e)
    elif fn.endswith(".csv"):
        try:
            cols,_=sniff_csv(p)
            if cols:
                rows.append((fn,"csv",len(cols),";".join(cols[:30])))
        except Exception as e:
            print("CSV error:", fn, e)

rows=sorted(rows, key=lambda x:(-x[2], x[0]))
print("\nResultados (primeros 50):")
for r in rows[:50]:
    print(r)

print("\nTotal coincidencias:", len(rows))
