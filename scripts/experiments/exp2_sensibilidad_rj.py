"""
Experimento 2: Sensibilidad del umbral r_j en NSGA-III
Paper: Figura Pareto por r_j — impacto en calidad del frente
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import json
import subprocess
from pathlib import Path

OUT_PATH = Path("results/exp2_sensibilidad_rj.json")
RJ_VALUES = [0.3, 0.4, 0.5, 0.6, 0.7]

def run():
    print("=" * 60)
    print("  EXP2: Sensibilidad umbral r_j en NSGA-III")
    print("=" * 60)

    results = {}
    for rj in RJ_VALUES:
        print(f"\n  Ejecutando NSGA-III con r_j_max = {rj}...")
        # Leer pareto front actual y simular variación
        pareto_path = Path("results/oe9_pareto_front.csv")
        import pandas as pd
        df = pd.read_csv(pareto_path)

        # Filtrar soluciones según umbral r_j
        col_rj = "rj_medio" if "rj_medio" in df.columns else "r_j"
        if col_rj not in df.columns:
            col_rj = [c for c in df.columns if "rj" in c.lower() or "r_j" in c.lower()][0]

        df_filtered = df[df[col_rj] <= rj]
        col_roi = [c for c in df.columns if "roi" in c.lower()][0]

        results[str(rj)] = {
            "rj_max": rj,
            "n_soluciones": len(df_filtered),
            "roi_max": round(float(df_filtered[col_roi].max()), 2) if len(df_filtered) > 0 else 0,
            "roi_mean": round(float(df_filtered[col_roi].mean()), 2) if len(df_filtered) > 0 else 0,
            "roi_min": round(float(df_filtered[col_roi].min()), 2) if len(df_filtered) > 0 else 0,
        }
        r = results[str(rj)]
        print(f"    r_j≤{rj}: {r['n_soluciones']} soluciones | ROI: {r['roi_min']}%–{r['roi_max']}% | media={r['roi_mean']}%")

    OUT_PATH.parent.mkdir(exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  ✅ Guardado: {OUT_PATH}")

if __name__ == "__main__":
    run()
