"""
fix_montecarlo_real.py
Elimina TODOS los datos sintéticos de _cargar_montecarlo()
Usa SOLO los estadísticos reales del JSON (p5_pct, media_pct, p95_pct)
"""
import shutil, ast, sys
from datetime import datetime

TARGET  = "dashboard_data.py"
BACKUP  = f"dashboard_data.py.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

shutil.copy2(TARGET, BACKUP)
print(f"[OK] Backup: {BACKUP}")

with open(TARGET, encoding="utf-8", errors="replace") as f:
    code = f.read()

# ══════════════════════════════════════════════════════════════════════════════
# REEMPLAZAR _cargar_montecarlo() COMPLETA
# ══════════════════════════════════════════════════════════════════════════════
OLD_FUNC = '''def _cargar_montecarlo():
    print("\\n  [MonteCarlo] Cargando análisis de sensibilidad...")

    # Intentar cargar desde OE4c (sensibilidad real)
    rutas = [
        RESULTS_DIR / "oe4c_sensibilidad_moderado.json",
        RESULTS_DIR / "oe4c_sensibilidad_agresivo.json",
        RESULTS_DIR / "oe4c_resumen_sensibilidad.csv",
    ]
    for ruta in rutas:
        if ruta.exists() and str(ruta).endswith(".json"):
            data = _read_json(ruta)
            if data:
                # Construir DataFrame desde los datos reales de sensibilidad
                escenarios = data.get("escenarios", data.get("simulaciones", []))
                if escenarios:
                    df = pd.DataFrame(escenarios)
                    if "roi_simulado" not in df.columns:
                        # Buscar columna de ROI con otro nombre
                        roi_cols = [c for c in df.columns if "roi" in c.lower()]
                        if roi_cols:
                            df["roi_simulado"] = pd.to_numeric(
                                df[roi_cols[0]], errors="coerce")
                    if "roi_simulado" in df.columns:
                        df["roi_simulado"] = pd.to_numeric(
                            df["roi_simulado"], errors="coerce").fillna(0)
                        if "factor_venta" not in df.columns:
                            df["factor_venta"] = np.random.uniform(0.5, 1.0, len(df))
                        if "margen" not in df.columns:
                            df["margen"] = df["roi_simulado"] / 100
                        print(f"      📊 {len(df)} escenarios de sensibilidad")
                        return df

        elif ruta.exists() and str(ruta).endswith(".csv"):
            df = _read_csv(ruta)
            if not df.empty:
                roi_cols = [c for c in df.columns if "roi" in c.lower()]
                if roi_cols:
                    df["roi_simulado"] = pd.to_numeric(
                        df[roi_cols[0]], errors="coerce").fillna(0)
                    df["factor_venta"] = np.random.uniform(0.5, 1.0, len(df))
                    df["margen"]       = df["roi_simulado"] / 100
                    return df

    # Construir desde los portafolios reales de OE9 (variación de ROI)
    df_oe9 = _read_csv(RESULTS_DIR / "oe9_pareto_front.csv")
    if not df_oe9.empty and "roi_pct" in df_oe9.columns:
        rois = df_oe9["roi_pct"].values / 100.0
        roi_mean = rois.mean()
        roi_std  = rois.std() if len(rois) > 1 else 0.1
        # Expandir con variación realista basada en datos reales
        np.random.seed(42)
        n = 500
        factor_venta = np.random.beta(2, 1.5, n)
        roi_sim = np.random.normal(roi_mean, roi_std, n) * factor_venta
        df = pd.DataFrame({
            "roi_simulado": roi_sim,
            "factor_venta": factor_venta,
            "margen":       roi_sim,
        })
        print(f"      📊 {n} escenarios construidos desde frente Pareto real")
        return df

    print("      ❌ Sin datos de sensibilidad")
    return pd.DataFrame({"roi_simulado": [0], "factor_venta": [0], "margen": [0]})'''

NEW_FUNC = '''def _cargar_montecarlo():
    """
    Carga estadísticos Monte Carlo REALES desde oe4c_sensibilidad_*.json
    NO genera datos sintéticos. Usa SOLO p5_pct, media_pct, p95_pct, std_pp
    del JSON producido por el pipeline OE4c.

    Estructura del DataFrame de salida:
      - perfil        : str  — "moderado" | "agresivo"
      - roi_pct       : float — ROI en porcentaje (escala 0-100)
      - estadistico   : str  — "p5" | "media" | "p95" | "std"
      - valor         : float — valor del estadístico
    """
    print("\\n  [MonteCarlo] Cargando estadísticos reales de sensibilidad...")

    perfiles = {
        "moderado": RESULTS_DIR / "oe4c_sensibilidad_moderado.json",
        "agresivo": RESULTS_DIR / "oe4c_sensibilidad_agresivo.json",
    }

    registros = []
    for perfil, ruta in perfiles.items():
        if not ruta.exists():
            print(f"      ⚠️  No encontrado: {ruta.name}")
            continue

        data = _read_json(ruta)
        if not data:
            continue

        mc = data.get("montecarlo", {})
        if not mc:
            print(f"      ⚠️  Sin clave 'montecarlo' en {ruta.name}")
            continue

        # Extraer estadísticos reales — todos en escala porcentual (0-100)
        n_sim    = int(mc.get("n_sim",          1000))
        media    = float(mc.get("media_pct",    0.0))
        std      = float(mc.get("std_pp",       0.0))
        p5       = float(mc.get("p5_pct",       0.0))
        p95      = float(mc.get("p95_pct",      0.0))
        prob_pos = float(mc.get("prob_roi_pos_pct", 100.0))
        prob_20  = float(mc.get("prob_roi_20_pct",  0.0))

        # Validar invariante estadístico P5 < media < P95
        if not (p5 <= media <= p95):
            print(f"      ⚠️  Invariante violada en {perfil}: P5={p5} media={media} P95={p95}")

        registros.append({
            "perfil":        perfil,
            "n_sim":         n_sim,
            "roi_simulado":  media,   # valor representativo para gráficos
            "media_pct":     media,
            "std_pp":        std,
            "p5_pct":        p5,
            "p95_pct":       p95,
            "prob_roi_pos":  prob_pos,
            "prob_roi_20":   prob_20,
            # factor_venta: ratio p5/p95 como proxy de dispersión (sin síntesis)
            "factor_venta":  round(p5 / p95, 4) if p95 > 0 else 0.0,
            "margen":        round(media / 100, 4),
        })
        print(f"      ✅ {perfil}: P5={p5:.1f}% | Media={media:.1f}% | P95={p95:.1f}% | n={n_sim}")

    if registros:
        df = pd.DataFrame(registros)
        print(f"      📊 {len(df)} perfiles reales cargados (sin síntesis)")
        return df

    print("      ❌ Sin datos de sensibilidad reales")
    return pd.DataFrame({
        "perfil": [], "roi_simulado": [], "media_pct": [],
        "std_pp": [], "p5_pct": [], "p95_pct": [],
        "prob_roi_pos": [], "prob_roi_20": [],
        "factor_venta": [], "margen": [],
    })'''

if OLD_FUNC in code:
    code = code.replace(OLD_FUNC, NEW_FUNC)
    print("[FIX] ✅ _cargar_montecarlo() reemplazada — cero datos sintéticos")
else:
    print("[FIX] ❌ Patrón no encontrado exacto")
    sys.exit(1)

# Validar sintaxis
try:
    ast.parse(code)
    print("[OK] Sintaxis válida ✅")
except SyntaxError as e:
    print(f"[ERROR] Línea {e.lineno}: {e.msg}")
    sys.exit(1)

with open(TARGET, "w", encoding="utf-8") as f:
    f.write(code)

print(f"[OK] {TARGET} guardado")
print(f"[OK] Backup: {BACKUP}")
