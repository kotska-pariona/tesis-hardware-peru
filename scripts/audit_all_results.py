import os, re, json
import pandas as pd

ROOT = "results"  # asume que ejecutas desde ~/tesis-hardware-peru
TARGET_FILES = [
    "oe9_resumen_nsga3.json",
    "oe9_integration_report.json",
    "evaluation_report.json",
    "oe9_pareto_front.csv",
    "oe4a_resumen_roi_moderado.json",   # por si también quieres ver otros escenarios
    "oe4b_resumen_roi_conservador.json",
    "oe5_resumen_nsga3.json",
]

# Archivos grandes/varios: recorrer todo y sniffear
ALL_EXTS = (".json",".csv",".txt",".png",".jpeg",".jpg",".parquet")

def safe_read_json(path):
    try:
        with open(path,"r",encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def safe_read_csv(path):
    try:
        return pd.read_csv(path)
    except Exception:
        return None

def find_rj_fields(obj):
    hits = []
    def walk(x, keypath=""):
        if isinstance(x, dict):
            for k,v in x.items():
                walk(v, f"{keypath}.{k}" if keypath else k)
        elif isinstance(x, list):
            for i,v in enumerate(x[:200]):  # limita
                walk(v, f"{keypath}[{i}]")
        else:
            pass
    # solo recorremos claves con regex para evitar sobrecarga
    keys = []
    def walk_keys(x):
        if isinstance(x, dict):
            for k,v in x.items():
                if re.search(r"(r_j_port|r_j\b|RJ_MAX|g3|factib|constraint|viol|obsole|riesg|pareto)", str(k), re.I):
                    keys.append(k)
                walk_keys(v)
        elif isinstance(x, list):
            for v in x[:200]:
                walk_keys(v)
    walk_keys(obj)
    return list(set(keys))

def summarize_solution_table(df):
    out = {"rows": None, "cols": None, "rj_port_min": None, "rj_port_max": None, "g3_min": None, "g3_max": None}
    out["rows"] = len(df)
    out["cols"] = df.shape[1]
    # columnas candidatas
    col_rj = None
    col_g3 = None
    for c in df.columns:
        if re.fullmatch(r".*r_j_port.*", str(c), flags=re.I):
            col_rj = c
        if re.fullmatch(r".*g3.*", str(c), flags=re.I):
            col_g3 = c
        if col_rj is None and re.search(r"r_j_port", str(c), re.I):
            col_rj = c
        if col_g3 is None and re.search(r"g3", str(c), re.I):
            col_g3 = c

    if col_rj is not None:
        s = pd.to_numeric(df[col_rj], errors="coerce")
        out["rj_port_min"] = float(s.min(skipna=True)) if s.notna().any() else None
        out["rj_port_max"] = float(s.max(skipna=True)) if s.notna().any() else None

    if col_g3 is not None:
        s = pd.to_numeric(df[col_g3], errors="coerce")
        out["g3_min"] = float(s.min(skipna=True)) if s.notna().any() else None
        out["g3_max"] = float(s.max(skipna=True)) if s.notna().any() else None

    return out

# --------- main ----------
if not os.path.isdir(ROOT):
    raise SystemExit(f"❌ No existe la carpeta '{ROOT}'. Ejecuta desde ~/tesis-hardware-peru o ajusta ROOT.")

rows = []
detail_lines = []

# 1) Analizar JSON clave
for fn in os.listdir(ROOT):
    if not fn.lower().endswith(".json"):
        continue
    path = os.path.join(ROOT, fn)
    j = safe_read_json(path)
    if j is None:
        continue
    keys = find_rj_fields(j)
    # métricas superficiales
    row = {"file": fn, "type": "json", "num_keys_hit": len(keys)}
    row["key_hits"] = ";".join(keys[:20])
    rows.append(row)

# 2) Analizar CSV
for fn in os.listdir(ROOT):
    if not fn.lower().endswith(".csv"):
        continue
    path = os.path.join(ROOT, fn)
    df = safe_read_csv(path)
    if df is None:
        continue
    summ = summarize_solution_table(df)
    row = {"file": fn, "type": "csv"}
    row.update(summ)
    rows.append(row)

report_df = pd.DataFrame(rows)

# Heurística: filtrar filas que probablemente tengan columnas de rj_port/g3
print("========== AUDIT ALL RESULTS ==========")
print("Total items analizados (json+csv):", len(report_df))
if not report_df.empty:
    # Ordenar para ver lo útil primero
    # (si hay columnas de tipo csv con stats)
    print("\nTop entradas por presencia de 'rj_port'/'g3' (heurística):")
    # Reagrupar: solo muestra csv
    csv_df = report_df[report_df["type"]=="csv"].copy() if "type" in report_df.columns else report_df
    if len(csv_df):
        cols = ["file","rows","cols","rj_port_min","rj_port_max","g3_min","g3_max"]
        cols = [c for c in cols if c in csv_df.columns]
        print(csv_df[cols].head(30).to_string(index=False))

# Guardar CSV de resumen
out_csv = os.path.join(ROOT, "audit_all_results_summary.csv")
report_df.to_csv(out_csv, index=False)
print(f"\n✅ Guardado: {out_csv}")

# 3) Mensajes útiles: buscar patrones en nombres de archivo
patterns = ["oe9", "oe4", "nsga", "pareto", "portafolio", "rj", "g3", "constraint", "sensibilidad", "resumen"]
hits = []
for fn in os.listdir(ROOT):
    low = fn.lower()
    if any(p in low for p in patterns) and fn.lower().endswith((".json",".csv",".txt")):
        hits.append(fn)
print("\nArchivos relevantes detectados (nombres):")
for h in sorted(hits):
    print(" -", h)

print("\n========== FIN ==========")
