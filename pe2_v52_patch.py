# =============================================================================
# HDS-ROI v6.2 — PATCH PE2 v5.2
# Archivo: pe2_v52_patch.py
# Instrucciones: ver sección 'COMO APLICAR' al final
# =============================================================================

# ── 1. BLOQUE PE2_V52 — pegar despues de 'from dashboard_data import DATA'

PE2_V52 = {
    "wmape_global":  0.97,    # WMAPE test global
    "wmape_seen":    0.78,    # WMAPE SKUs conocidos (seen)
    "wmape_unseen":  2.14,    # WMAPE SKUs nuevos (unseen)
    "mae_global":    4.87,    # MAE test global (USD)
    "mae_seen":      4.00,    # MAE SKUs conocidos
    "mae_unseen":    9.25,    # MAE SKUs nuevos
    "wmape_val":     0.62,    # WMAPE validacion
    "mae_val":       3.12,    # MAE validacion
    "r2":            0.9967,  # R2 (mantenido)
    "n_iter":        997,     # iteraciones LightGBM
    "n_features":    32,      # features
    "n_train":       640762,  # registros train
    "n_val":         107056,  # registros val
    "n_test":        129626,  # registros test
    "n_total":       877958,  # registros totales processed_v2
    "n_fechas":      35,      # fechas unicas
    "pct_unseen":    22,      # % SKUs nuevos en test
    "ratio_deg":     2.7,     # ratio degradacion seen->unseen
    "dataset":       "processed_v2",
    "modelo":        "pe2_v52",
    "fecha":         "2026-10-03",
}


# ── 2. REEMPLAZAR bloque try/except de metricas LGBM en page_home_ejecutivo()
# BUSCAR:
#   try:
#       with open("results/pe2_lgbm_metrics.json", encoding="utf-8") as f:
#           lgbm = json.load(f)
#       mape_lgbm = lgbm["metrics_test"]["mape"]
#       r2_lgbm   = lgbm["metrics_test"]["r2"]
#   except Exception:
#       mape_lgbm, r2_lgbm = 0.64, 0.9967

# REEMPLAZAR POR:
    # FIX-H: Cargar metricas PE2 v5.2
    try:
        _paths = [
            "models/pe2_v52_metrics_20261003_142754.json",
            "results/pe2_v52_metrics.json",
            "results/pe2_lgbm_metrics.json",
        ]
        lgbm = None
        for _p in _paths:
            if Path(_p).exists():
                with open(_p, encoding="utf-8") as f:
                    lgbm = json.load(f)
                break
        if lgbm:
            _test = lgbm.get("metrics_test", lgbm.get("test", {}))
            wmape_lgbm   = _test.get("wmape", _test.get("mape", PE2_V52["wmape_global"]))
            r2_lgbm      = _test.get("r2", PE2_V52["r2"])
            wmape_seen   = _test.get("wmape_seen",   PE2_V52["wmape_seen"])
            wmape_unseen = _test.get("wmape_unseen", PE2_V52["wmape_unseen"])
        else:
            raise FileNotFoundError
    except Exception:
        wmape_lgbm   = PE2_V52["wmape_global"]
        r2_lgbm      = PE2_V52["r2"]
        wmape_seen   = PE2_V52["wmape_seen"]
        wmape_unseen = PE2_V52["wmape_unseen"]


# ── 3. BANNER PE2 v5.2 — agregar en page_home_ejecutivo() return
# Pegar ANTES de 'section_title("🗺️ Flujo de Sustentacion...'

    banner_pe2 = dbc.Card([dbc.CardBody([
        html.Div([
            html.Span("🤖 ", style={"fontSize": "1.4rem"}),
            html.Span("PE2 v5.2 — LightGBM · Dataset processed_v2",
                      style={"fontWeight": 700, "color": COLORS["accent"], "fontSize": "0.95rem"}),
            dbc.Badge("ACTUALIZADO", color="success", pill=True, className="ms-2",
                      style={"fontSize": "0.65rem"}),
        ], style={"marginBottom": "12px"}),
        dbc.Row([
            dbc.Col([
                html.Div([html.B("WMAPE Global: "),
                          html.Span(f"{PE2_V52['wmape_global']:.2f}%",
                          style={"color": COLORS["green"], "fontWeight": 700})]),
                html.Div([html.B("WMAPE Seen: "),
                          html.Span(f"{PE2_V52['wmape_seen']:.2f}%",
                          style={"color": COLORS["green"]})]),
                html.Div([html.B("WMAPE Unseen: "),
                          html.Span(f"{PE2_V52['wmape_unseen']:.2f}%",
                          style={"color": COLORS["accent4"]})]),
            ], md=3, style={"fontSize": "0.82rem"}),
            dbc.Col([
                html.Div([html.B("MAE Global: "),
                          html.Span(f"${PE2_V52['mae_global']:.2f}",
                          style={"color": COLORS["accent2"]})]),
                html.Div([html.B("MAE Seen: "),
                          html.Span(f"${PE2_V52['mae_seen']:.2f}",
                          style={"color": COLORS["accent2"]})]),
                html.Div([html.B("MAE Unseen: "),
                          html.Span(f"${PE2_V52['mae_unseen']:.2f}",
                          style={"color": COLORS["accent4"]})]),
            ], md=3, style={"fontSize": "0.82rem"}),
            dbc.Col([
                html.Div([html.B("Iteraciones: "),
                          html.Span(f"{PE2_V52['n_iter']:,}",
                          style={"color": COLORS["accent"]})]),
                html.Div([html.B("Features: "),
                          html.Span(str(PE2_V52["n_features"]),
                          style={"color": COLORS["accent"]})]),
                html.Div([html.B("Ratio degradacion: "),
                          html.Span(f"{PE2_V52['ratio_deg']}x",
                          style={"color": COLORS["accent4"]})]),
            ], md=3, style={"fontSize": "0.82rem"}),
            dbc.Col([
                html.Div([html.B("Dataset: "),
                          html.Span(PE2_V52["dataset"],
                          style={"color": COLORS["accent2"]})]),
                html.Div([html.B("Registros: "),
                          html.Span(f"{PE2_V52['n_total']:,}",
                          style={"color": COLORS["accent"]})]),
                html.Div([html.B("Fechas: "),
                          html.Span(f"{PE2_V52['n_fechas']} unicas",
                          style={"color": COLORS["accent"]})]),
            ], md=3, style={"fontSize": "0.82rem"}),
        ]),
    ])], style={
        "background": COLORS["bg"],
        "border": f"2px solid {COLORS['green']}44",
        "borderLeft": f"5px solid {COLORS['green']}",
        "borderRadius": "10px",
        "marginBottom": "20px",
    })

    # En el return, agregar 'banner_pe2,' despues de 'banner,'


# ── 4. TABLA METAS — reemplazar en page_home_ejecutivo()
# BUSCAR la lista de metas y REEMPLAZAR por:

                for meta, obj, res, estado in [
                    ("WMAPE",       "< 2%",   f"{wmape_lgbm:.2f}%",     "✅"),
                    ("WMAPE Seen",  "< 1%",   f"{wmape_seen:.2f}%",     "✅"),
                    ("WMAPE Unseen","< 3%",   f"{wmape_unseen:.2f}%",   "✅"),
                    ("R2",          "> 0.85", f"{r2_lgbm:.4f}",         "✅"),
                    ("F1-NLP",      "> 0.95", f"{f1_e5:.4f}",           "✅"),
                    ("Pareto",      "> 10",   f"{n_pareto} sols.",       "✅"),
                    ("ROI max",     "> 20%",  f"+{roi_max:.1f}%",       "✅"),
                ],


# ── 5. ABLACION — actualizar LightGBM en dashboard_data.py
# BUSCAR la fila de LightGBM en el DataFrame de ablacion y cambiar:
#   mape_pct: 0.64  ->  0.97
#   smape_pct: 0.71 ->  0.89
#   params_k: 451   ->  997


# ── 6. STRINGS SIMPLES — buscar y reemplazar en dashboard_v5_main.py

REPLACEMENTS = [
    # Sidebar version
    ("v6.0 · Dropshipping Hardware",
     "v6.2 · PE2 v5.2 · Dropshipping Hardware"),

    # Motor de decision alert
    ("LightGBM predice precios con MAPE 0.64%.",
     f"LightGBM PE2 v5.2 predice con WMAPE {PE2_V52['wmape_global']:.2f}%."),

    # Panel porque
    ("MAPE 0.64% · R2=0.9967 · Horizonte 1/7/14/30d",
     f"WMAPE {PE2_V52['wmape_global']:.2f}% · R2={PE2_V52['r2']} · {PE2_V52['n_iter']} iter"),

    # Prediccion alert
    ("LightGBM (MAPE 0.64%)",
     f"LightGBM PE2 v5.2 (WMAPE {PE2_V52['wmape_global']:.2f}%)"),

    # Ablacion alert final
    ("MAPE 0.64% · R2=0.9967 · Convergencia en iteracion 451",
     f"WMAPE {PE2_V52['wmape_global']:.2f}% · R2={PE2_V52['r2']} · Convergencia en iteracion {PE2_V52['n_iter']}"),

    # Print startup
    ("HDS-ROI v6.0 — Motor de Decision Inteligente",
     "HDS-ROI v6.2 — Motor de Decision Inteligente (PE2 v5.2)"),
]


# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =
# COMO APLICAR ESTE PATCH
# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =# =
# 1. Abre dashboard_v5_main.py en tu editor
# 2. Agrega el bloque PE2_V52 despues de 'from dashboard_data import DATA'
# 3. Reemplaza el bloque try/except de metricas LGBM (seccion 2)
# 4. Agrega el banner_pe2 en page_home_ejecutivo() (seccion 3)
# 5. Actualiza la tabla de metas (seccion 4)
# 6. Actualiza LightGBM en dashboard_data.py (seccion 5)
# 7. Aplica los reemplazos de strings (seccion 6)
# 8. Reinicia el dashboard: python dashboard_v5_main.py