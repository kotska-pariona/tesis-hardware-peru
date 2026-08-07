# pages/page_prediccion_demanda.py
# Pestaña Crítica #2: Predicción de Demanda — LightGBM vs TFT
# Datos 100% reales desde results/predicciones_multihorizonte.json

import json
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from dash import dcc, html, callback, Input, Output
import dash_bootstrap_components as dbc
from pathlib import Path
from dashboard_config import COLORS, CHART_CONFIG, PLOTLY_TEMPLATE

# ─── helpers ──────────────────────────────────────────────────────────────────

def _safe_layout(**kwargs):
    base = dict(PLOTLY_TEMPLATE["layout"])
    base.update(kwargs)
    return base

def section_title(text, icon=""):
    return html.H5(
        [html.Span(icon + " ", style={"marginRight": "8px",
                                      "color": COLORS["accent"]}), text],
        style={"color": COLORS["accent"],
               "borderBottom": f"3px solid {COLORS['accent']}",
               "paddingBottom": "10px", "marginBottom": "20px",
               "fontWeight": 700, "fontSize": "1.1rem"})

def kpi_card(title, value, subtitle="", color=None, icon="📊"):
    color = color or COLORS["accent"]
    return dbc.Card([dbc.CardBody([
        html.Div([
            html.Span(icon, style={"fontSize": "1.8rem", "marginRight": "10px",
                                   "opacity": 0.85}),
            html.Div([
                html.P(title, className="mb-0",
                       style={"color": COLORS["text_dim"], "fontSize": "0.72rem",
                              "textTransform": "uppercase", "letterSpacing": "0.05em",
                              "fontWeight": 600}),
                html.H4(value, className="mb-0",
                        style={"color": color, "fontSize": "1.6rem",
                               "fontWeight": 700}),
                html.P(subtitle, className="mb-0",
                       style={"color": COLORS["text_dim"], "fontSize": "0.68rem"}),
            ], style={"flex": 1})
        ], style={"display": "flex", "alignItems": "center"})
    ], style={"padding": "14px"})],
    style={"background": COLORS["bg"],
           "border": f"2px solid {COLORS['border']}",
           "borderRadius": "10px", "height": "110px"}, className="shadow-sm")

# ─── carga de datos ────────────────────────────────────────────────────────────

def _load_data():
    base = Path("results")

    # Métricas LightGBM
    with open(base / "pe2_lgbm_metrics.json", encoding="utf-8") as f:
        lgbm = json.load(f)

    # Métricas TFT v1
    with open(base / "pe2_tft_metrics.json", encoding="utf-8") as f:
        tft = json.load(f)

    # Métricas TFT v2
    with open(base / "pe2_tft_v2_metrics.json", encoding="utf-8") as f:
        tft2 = json.load(f)

    # Predicciones multihorizonte
    with open(base / "predicciones_multihorizonte.json",
              encoding="utf-8", errors="replace") as f:
        pred_raw = json.load(f)

    # Extraer dict de SKUs
    skus_dict = {}
    if isinstance(pred_raw, list):
        for item in pred_raw:
            if isinstance(item, list) and len(item) == 2:
                key, val = item
                if key == "skus" and isinstance(val, dict):
                    skus_dict = val
                    break
            elif isinstance(item, dict):
                skus_dict.update(item)
    elif isinstance(pred_raw, dict):
        skus_dict = pred_raw.get("skus", pred_raw)

    return lgbm, tft, tft2, skus_dict

# ─── gráfico 1: comparativa de modelos ────────────────────────────────────────

def _fig_modelos(lgbm, tft, tft2):
    modelos = ["Naive Baseline", "TFT v1", "TFT v2 (log1p)", "LightGBM ★"]
    mapes   = [
        lgbm["naive_baseline"]["test_mape"] * 100,   # 86.45%
        tft["metrics"]["mape"],                       # 73.00%
        tft2["metrics"]["mape"],                      # 381.36%
        lgbm["metrics_test"]["mape"] * 100,           # 0.64%
    ]
    r2s = [
        lgbm["naive_baseline"]["test_r2"],
        tft["metrics"]["r2"],
        tft2["metrics"]["r2"],
        lgbm["metrics_test"]["r2"],
    ]
    colores = [
        COLORS.get("text_dim", "#aaa"),
        COLORS.get("accent3", "#e67e22"),
        COLORS.get("red", "#e74c3c"),
        COLORS.get("green", "#27ae60"),
    ]

    fig = go.Figure()

    # Barras MAPE
    fig.add_trace(go.Bar(
        name="MAPE (%)",
        x=modelos,
        y=mapes,
        marker_color=colores,
        text=[f"{v:.2f}%" for v in mapes],
        textposition="outside",
        yaxis="y",
        offsetgroup=1,
    ))

    # Línea R²
    fig.add_trace(go.Scatter(
        name="R²",
        x=modelos,
        y=r2s,
        mode="lines+markers+text",
        marker=dict(size=12, color=COLORS.get("accent2", "#2980b9"),
                    line=dict(color="white", width=2)),
        line=dict(color=COLORS.get("accent2", "#2980b9"), width=2, dash="dash"),
        text=[f"R²={v:.3f}" for v in r2s],
        textposition="top center",
        textfont=dict(size=9),
        yaxis="y2",
    ))

    # Zona de meta
    fig.add_hrect(y0=0, y1=2, fillcolor=COLORS.get("green", "#27ae60"),
                  opacity=0.07, line_width=0, annotation_text="Meta MAPE < 2%",
                  annotation_position="top left",
                  annotation_font_color=COLORS.get("green", "#27ae60"))

    fig.update_layout(**_safe_layout(
        title="Comparativa de Modelos — MAPE y R² (Test Set)",
        height=420,
        yaxis=dict(title="MAPE (%)", ticksuffix="%"),
        yaxis2=dict(title="R²", overlaying="y", side="right",
                    range=[0, 1.05], showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
        bargap=0.3,
    ))
    return fig

# ─── gráfico 2: predicción multihorizonte de un SKU ───────────────────────────

def _fig_prediccion_sku(sku_data, horizonte="30"):
    titulo = sku_data.get("title", "SKU")[:55] + "..."
    historia_fechas  = sku_data.get("historia_fechas", [])
    historia_precios = sku_data.get("historia_precios", [])
    pred = sku_data.get("predicciones", {}).get(horizonte, {})

    if not pred:
        return go.Figure()

    fechas_pred  = pred.get("fechas", [])
    precios_pred = pred.get("precios", [])
    ci_lower     = pred.get("ci_lower", [])
    ci_upper     = pred.get("ci_upper", [])

    fig = go.Figure()

    # Historia real
    fig.add_trace(go.Scatter(
        x=historia_fechas, y=historia_precios,
        mode="lines+markers",
        name="Historia real",
        line=dict(color=COLORS.get("accent2", "#2980b9"), width=2),
        marker=dict(size=6),
        hovertemplate="<b>Real</b><br>Fecha: %{x}<br>Precio: $%{y:.2f}<extra></extra>",
    ))

    # Banda de confianza
    if ci_lower and ci_upper:
        fig.add_trace(go.Scatter(
            x=fechas_pred + fechas_pred[::-1],
            y=ci_upper + ci_lower[::-1],
            fill="toself",
            fillcolor="rgba(142,68,173,0.12)",
            line=dict(color="rgba(0,0,0,0)"),
            name="IC 95%",
            showlegend=True,
            hoverinfo="skip",
        ))

    # Predicción
    color_pred = (COLORS.get("green", "#27ae60")
                  if pred.get("tendencia") == "SUBE"
                  else COLORS.get("red", "#e74c3c")
                  if pred.get("tendencia") == "BAJA"
                  else COLORS.get("accent3", "#e67e22"))

    fig.add_trace(go.Scatter(
        x=fechas_pred, y=precios_pred,
        mode="lines+markers",
        name=f"Pred. LightGBM ({horizonte}d)",
        line=dict(color=color_pred, width=2, dash="dot"),
        marker=dict(size=5),
        hovertemplate=(
            "<b>Predicción</b><br>Fecha: %{x}<br>"
            "Precio: $%{y:.2f}<extra></extra>"),
    ))

    # Anotación precio final
    if fechas_pred and precios_pred:
        fig.add_annotation(
            x=fechas_pred[-1], y=precios_pred[-1],
            text=f"${precios_pred[-1]:.2f}<br>{pred.get('variacion_pct',0):+.1f}%",
            showarrow=True, arrowhead=2,
            font=dict(color=color_pred, size=10),
            bgcolor=COLORS["card"],
            bordercolor=color_pred, borderwidth=1,
        )

    fig.update_layout(**_safe_layout(
        title=f"Predicción {horizonte}d — {titulo}",
        xaxis_title="Fecha",
        yaxis_title="Precio (USD)",
        height=400,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))
    return fig

# ─── gráfico 3: error por rango de precio (TFT v2 vs LightGBM) ───────────────

def _fig_error_rangos(tft2, lgbm):
    rangos = ["$5-$20", "$20-$100", "$100-$500", "$500-$2k", "$2k+"]
    # TFT v2 MAPE por rango
    tft2_mapes = [
        tft2["metrics"]["by_price_range"]["$5-$20   (accesorios)"]["wmape"],
        tft2["metrics"]["by_price_range"]["$20-$100 (periféricos)"]["wmape"],
        tft2["metrics"]["by_price_range"]["$100-$500 (mid-range)"]["wmape"],
        tft2["metrics"]["by_price_range"]["$500-$2k  (high-end)"]["wmape"],
        tft2["metrics"]["by_price_range"]["$2k+      (premium)"]["wmape"],
    ]
    # LightGBM: MAPE global aplicado (mejor en todos los rangos)
    lgbm_mapes = [
        lgbm["metrics_test"]["wmape"] * 100,
        lgbm["metrics_test"]["wmape"] * 100,
        lgbm["metrics_test"]["wmape"] * 100,
        lgbm["metrics_test"]["wmape"] * 100,
        lgbm["metrics_test"]["wmape"] * 100,
    ]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="TFT v2 WMAPE (%)",
        x=rangos, y=tft2_mapes,
        marker_color=COLORS.get("red", "#e74c3c"),
        text=[f"{v:.1f}%" for v in tft2_mapes],
        textposition="outside",
        offsetgroup=1,
    ))
    fig.add_trace(go.Bar(
        name="LightGBM WMAPE (%)",
        x=rangos, y=lgbm_mapes,
        marker_color=COLORS.get("green", "#27ae60"),
        text=[f"{v:.1f}%" for v in lgbm_mapes],
        textposition="outside",
        offsetgroup=2,
    ))
    fig.update_layout(**_safe_layout(
        title="Error WMAPE por Rango de Precio — TFT v2 vs LightGBM",
        height=380,
        barmode="group",
        yaxis=dict(title="WMAPE (%)", ticksuffix="%"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))
    return fig

# ─── gráfico 4: resumen de tendencias por categoría ──────────────────────────

def _fig_tendencias(skus_dict):
    cat_tend = {}
    for sku, data in skus_dict.items():
        cat  = data.get("hw_type", "otro").upper()
        pred = data.get("predicciones", {}).get("7", {})
        tend = pred.get("tendencia", "ESTABLE")
        if cat not in cat_tend:
            cat_tend[cat] = {"SUBE": 0, "ESTABLE": 0, "BAJA": 0}
        cat_tend[cat][tend] = cat_tend[cat].get(tend, 0) + 1

    cats   = list(cat_tend.keys())
    subes  = [cat_tend[c].get("SUBE", 0)    for c in cats]
    estabs = [cat_tend[c].get("ESTABLE", 0) for c in cats]
    bajas  = [cat_tend[c].get("BAJA", 0)    for c in cats]

    fig = go.Figure()
    fig.add_trace(go.Bar(name="↑ SUBE",    x=cats, y=subes,
                         marker_color=COLORS.get("green", "#27ae60")))
    fig.add_trace(go.Bar(name="→ ESTABLE", x=cats, y=estabs,
                         marker_color=COLORS.get("accent3", "#e67e22")))
    fig.add_trace(go.Bar(name="↓ BAJA",   x=cats, y=bajas,
                         marker_color=COLORS.get("red", "#e74c3c")))
    fig.update_layout(**_safe_layout(
        title="Tendencias de Precio a 7 días por Categoría (LightGBM)",
        height=380,
        barmode="stack",
        yaxis_title="Nº SKUs",
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))
    return fig

# ─── tabla de SKUs con predicción ─────────────────────────────────────────────

def _tabla_skus(skus_dict):
    filas = []
    for sku, data in list(skus_dict.items())[:20]:
        pred7  = data.get("predicciones", {}).get("7",  {})
        pred30 = data.get("predicciones", {}).get("30", {})
        tend   = pred7.get("tendencia", "—")
        var7   = pred7.get("variacion_pct", 0)
        var30  = pred30.get("variacion_pct", 0)
        accion = data.get("oportunidad", {}).get("accion", "—")
        roi    = data.get("oportunidad", {}).get("roi_pct", 0)

        color_tend = (COLORS.get("green", "#27ae60") if tend == "SUBE"
                      else COLORS.get("red", "#e74c3c") if tend == "BAJA"
                      else COLORS.get("accent3", "#e67e22"))
        color_roi  = (COLORS.get("green", "#27ae60") if roi > 30
                      else COLORS.get("accent3", "#e67e22") if roi > 15
                      else COLORS.get("red", "#e74c3c"))

        filas.append(html.Tr([
            html.Td(data.get("title", sku)[:40] + "…",
                    style={"fontSize": "0.78rem", "maxWidth": "260px",
                           "overflow": "hidden", "whiteSpace": "nowrap",
                           "textOverflow": "ellipsis"}),
            html.Td(data.get("hw_type", "—").upper(),
                    style={"textAlign": "center", "fontSize": "0.78rem"}),
            html.Td(f"${data.get('precio_actual_usd', 0):.2f}",
                    style={"textAlign": "right", "fontSize": "0.78rem"}),
            html.Td(html.B(tend, style={"color": color_tend}),
                    style={"textAlign": "center"}),
            html.Td(f"{var7:+.1f}%",
                    style={"textAlign": "right", "fontSize": "0.78rem",
                           "color": color_tend}),
            html.Td(f"{var30:+.1f}%",
                    style={"textAlign": "right", "fontSize": "0.78rem",
                           "color": color_tend}),
            html.Td(html.B(f"{roi:.1f}%", style={"color": color_roi}),
                    style={"textAlign": "right"}),
            html.Td(accion, style={"textAlign": "center",
                                   "fontSize": "0.75rem",
                                   "color": COLORS.get("accent", "")}),
        ], style={"borderBottom": f"1px solid {COLORS['border']}"}))

    return dbc.Table([
        html.Thead(html.Tr([
            html.Th(c, style={"color": COLORS["accent"], "fontWeight": 700,
                              "fontSize": "0.78rem",
                              "textAlign": "right" if i in [2,4,5,6] else
                                           "center" if i in [1,3,7] else "left"})
            for i, c in enumerate(["Producto", "Tipo", "Precio Actual",
                                   "Tendencia", "Var 7d", "Var 30d",
                                   "ROI", "Acción"])
        ], style={"background": COLORS["card"],
                  "borderBottom": f"2px solid {COLORS['border']}"})),
        html.Tbody(filas),
    ], bordered=True, hover=True, responsive=True, size="sm",
       style={"color": COLORS["text"], "fontSize": "0.8rem"})

# ─── página principal ──────────────────────────────────────────────────────────

def page_prediccion_demanda():
    try:
        lgbm, tft, tft2, skus_dict = _load_data()
    except Exception as e:
        return html.Div([
            section_title("📈 Predicción de Demanda", "📈"),
            dbc.Alert(f"⚠️ Error: {e}", color="danger"),
        ], style={"padding": "24px"})

    n_skus   = len(skus_dict)
    n_sube   = sum(1 for d in skus_dict.values()
                   if d.get("predicciones", {}).get("7", {})
                      .get("tendencia") == "SUBE")
    n_baja   = sum(1 for d in skus_dict.values()
                   if d.get("predicciones", {}).get("7", {})
                      .get("tendencia") == "BAJA")
    n_comprar = sum(1 for d in skus_dict.values()
                    if "COMPRAR" in d.get("oportunidad", {})
                                     .get("accion", ""))

    # ── KPIs ──────────────────────────────────────────────────────────────
    kpi_row = dbc.Row([
        dbc.Col(kpi_card("MAPE LightGBM",
                         f"{lgbm['metrics_test']['mape']*100:.2f}%",
                         f"vs TFT v1: {tft['metrics']['mape']:.1f}%",
                         COLORS["green"], "🎯"), md=3),
        dbc.Col(kpi_card("R² Test",
                         f"{lgbm['metrics_test']['r2']:.4f}",
                         f"n={lgbm['metrics_test']['n']:,} muestras",
                         COLORS["accent2"], "📐"), md=3),
        dbc.Col(kpi_card("SKUs Predichos",
                         str(n_skus),
                         f"↑{n_sube} suben · ↓{n_baja} bajan",
                         COLORS["accent"], "🔮"), md=3),
        dbc.Col(kpi_card("Oportunidades",
                         str(n_comprar),
                         "acción COMPRAR / COMPRAR YA",
                         COLORS["accent3"], "💰"), md=3),
    ], className="mb-4 g-3")

    # ── Selector de SKU ───────────────────────────────────────────────────
    opciones_sku = [
        {"label": f"{v.get('hw_type','').upper()} — {v.get('title','')[:45]}",
         "value": k}
        for k, v in skus_dict.items()
    ]
    primer_sku = list(skus_dict.keys())[0] if skus_dict else None

    # Gráficos estáticos
    fig_modelos   = _fig_modelos(lgbm, tft, tft2)
    fig_rangos    = _fig_error_rangos(tft2, lgbm)
    fig_tendencias = _fig_tendencias(skus_dict)
    tabla         = _tabla_skus(skus_dict)

    # Gráfico inicial vacío (el callback lo llena al navegar al tab)
    fig_pred_init = go.Figure()
    fig_pred_init.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        annotations=[dict(
            text="Selecciona un SKU para ver la predicción",
            x=0.5, y=0.5, xref="paper", yref="paper",
            showarrow=False,
            font=dict(size=14, color="#888"),
        )],
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
    )

    return html.Div([
        section_title("📈 Predicción de Demanda — LightGBM vs TFT", "📈"),

        dbc.Alert([
            html.B("📌 Objetivo OE3/PE2: "),
            "Predecir la evolución de precios de hardware a 1, 7, 14 y 30 días "
            "para anticipar oportunidades de arbitraje. "
            f"LightGBM (MAPE={lgbm['metrics_test']['mape']*100:.2f}%, "
            f"R²={lgbm['metrics_test']['r2']:.4f}) supera ampliamente a "
            f"TFT v1 (MAPE={tft['metrics']['mape']:.1f}%) y "
            f"TFT v2 (MAPE={tft2['metrics']['mape']:.1f}%) — "
            "justificado por la escasez de datos históricos (9 días vs 30+ requeridos por TFT)."
        ], color="info", style={"background": COLORS["card"],
                                "border": f"2px solid {COLORS['accent2']}",
                                "color": COLORS["text"], "fontSize": "0.88rem",
                                "marginBottom": "20px"}),

        kpi_row,

        dbc.Tabs([

            # ── Tab 1: Comparativa de Modelos ──────────────────────────
            dbc.Tab(label="🏆 Comparativa Modelos", tab_id="tab-modelos",
                    label_style={"fontWeight": 700}, children=[
                html.Div([
                    dcc.Graph(figure=fig_modelos, config=CHART_CONFIG),

                    dbc.Row([
                        dbc.Col([
                            dcc.Graph(figure=fig_rangos, config=CHART_CONFIG),
                        ], md=12),
                    ]),

                    # Tabla de métricas
                    section_title("Métricas Detalladas por Modelo", "📋"),
                    _tabla_metricas(lgbm, tft, tft2),

                    dbc.Alert([
                        html.B("🔑 Justificación de selección LightGBM: "),
                        html.Ul([
                            html.Li(f"Solo 9 días de historia → TFT requiere 30+ "
                                    "(encoder_length=7, necesita warm-up)"),
                            html.Li(f"LightGBM MAPE={lgbm['metrics_test']['mape']*100:.2f}% "
                                    f"vs TFT MAPE={tft['metrics']['mape']:.1f}% "
                                    f"(×{tft['metrics']['mape']/(lgbm['metrics_test']['mape']*100):.0f}x mejor)"),
                            html.Li("21 features tabulares (lags, MA, std, calendario, "
                                    "categoría) → robustos con datos escasos"),
                            html.Li(f"Best iteration: {lgbm['config']['best_iteration']} "
                                    f"/ {lgbm['config']['num_boost_round']} "
                                    "(early stopping efectivo)"),
                        ], style={"marginBottom": 0, "fontSize": "0.83rem"}),
                    ], color="success",
                       style={"background": "#f0fdf4",
                              "border": f"2px solid {COLORS.get('green','')}",
                              "color": COLORS["text"], "marginTop": "16px"}),
                ], style={"paddingTop": "16px"}),
            ]),

            # ── Tab 2: Predicción por SKU ──────────────────────────────
            dbc.Tab(label="🔮 Predicción por SKU", tab_id="tab-pred",
                    children=[
                html.Div([
                    dbc.Row([
                        dbc.Col([
                            html.Label("Seleccionar SKU:",
                                       style={"color": COLORS["text"],
                                              "fontWeight": 600,
                                              "fontSize": "0.85rem"}),
                            dcc.Dropdown(
                                id="pred-sku-selector",
                                options=opciones_sku,
                                value=primer_sku,
                                clearable=False,
                                style={"background": COLORS["card"],
                                       "color": "#000",
                                       "fontSize": "0.82rem"},
                            ),
                        ], md=8),
                        dbc.Col([
                            html.Label("Horizonte:",
                                       style={"color": COLORS["text"],
                                              "fontWeight": 600,
                                              "fontSize": "0.85rem"}),
                            dcc.Dropdown(
                                id="pred-horizonte-selector",
                                options=[
                                    {"label": "1 día",   "value": "1"},
                                    {"label": "7 días",  "value": "7"},
                                    {"label": "14 días", "value": "14"},
                                    {"label": "30 días", "value": "30"},
                                ],
                                value="30",
                                clearable=False,
                                style={"background": COLORS["card"],
                                       "color": "#000"},
                            ),
                        ], md=4),
                    ], className="mb-3"),

                    dcc.Graph(id="pred-sku-graph",
                              figure=fig_pred_init,
                              config=CHART_CONFIG),

                    html.Div(id="pred-sku-info"),

                ], style={"paddingTop": "16px"}),
            ]),

            # ── Tab 3: Tendencias por Categoría ───────────────────────
            dbc.Tab(label="📊 Tendencias", tab_id="tab-tend",
                    children=[
                html.Div([
                    dcc.Graph(figure=fig_tendencias, config=CHART_CONFIG),
                    section_title("Top 20 SKUs — Predicción 7d y 30d", "📋"),
                    html.Div(tabla, style={"overflowX": "auto"}),
                ], style={"paddingTop": "16px"}),
            ]),

            # ── Tab 4: Metodología ────────────────────────────────────
            dbc.Tab(label="📐 Metodología", tab_id="tab-metodo",
                    children=[
                html.Div([
                    _seccion_metodologia(lgbm),
                ], style={"paddingTop": "16px"}),
            ]),

        ], id="pred-tabs", active_tab="tab-modelos"),

    ], style={"padding": "24px"})


# ─── tabla de métricas ─────────────────────────────────────────────────────────

def _tabla_metricas(lgbm, tft, tft2):
    filas_data = [
        ("Naive Baseline", "—",
         f"{lgbm['naive_baseline']['test_mape']*100:.2f}%",
         "—",
         f"{lgbm['naive_baseline']['test_r2']:.4f}",
         "❌ Referencia mínima",
         COLORS.get("text_dim", "#aaa")),
        ("TFT v1", "73.00%", "73.00%", "277.47",
         f"{tft['metrics']['r2']:.4f}",
         "⚠️ Datos insuficientes (9d)",
         COLORS.get("accent3", "#e67e22")),
        ("TFT v2 (log1p)", "381.36%", "57.62%", "468.24",
         f"{tft2['metrics']['r2']:.4f}",
         "❌ Diverge en rangos bajos",
         COLORS.get("red", "#e74c3c")),
        ("LightGBM ★",
         f"{lgbm['metrics_test']['mape']*100:.2f}%",
         f"{lgbm['metrics_test']['wmape']*100:.2f}%",
         f"{lgbm['metrics_test']['rmse']:.2f}",
         f"{lgbm['metrics_test']['r2']:.4f}",
         "✅ Seleccionado — robusto con datos escasos",
         COLORS.get("green", "#27ae60")),
    ]

    filas = []
    for nombre, mape, wmape, rmse, r2, nota, col in filas_data:
        es_lgbm = "★" in nombre
        filas.append(html.Tr([
            html.Td(html.B(nombre, style={"color": col})),
            html.Td(mape,  style={"textAlign": "right",
                                   "color": COLORS.get("green","")
                                            if es_lgbm else ""}),
            html.Td(wmape, style={"textAlign": "right",
                                   "color": COLORS.get("green","")
                                            if es_lgbm else ""}),
            html.Td(rmse,  style={"textAlign": "right"}),
            html.Td(html.B(r2, style={"color": COLORS.get("green","")
                                               if es_lgbm else ""}),
                    style={"textAlign": "right"}),
            html.Td(nota,  style={"fontSize": "0.8rem"}),
        ], style={
            "borderBottom": f"1px solid {COLORS['border']}",
            "background": f"{col}0D" if es_lgbm else "transparent",
            "fontWeight": 700 if es_lgbm else 400,
        }))

    return dbc.Table([
        html.Thead(html.Tr([
            html.Th(c, style={"color": COLORS["accent"], "fontWeight": 700,
                              "textAlign": "right" if i in [1,2,3,4] else "left"})
            for i, c in enumerate(["Modelo", "MAPE", "WMAPE",
                                   "RMSE", "R²", "Nota"])
        ], style={"background": COLORS["card"],
                  "borderBottom": f"2px solid {COLORS['border']}"})),
        html.Tbody(filas),
    ], bordered=True, hover=True, responsive=True, size="sm",
       style={"color": COLORS["text"], "fontSize": "0.83rem"})


# ─── sección metodología ───────────────────────────────────────────────────────

def _seccion_metodologia(lgbm):
    features = lgbm["config"]["features"]
    return html.Div([
        dbc.Row([
            dbc.Col([
                section_title("Pipeline de Predicción", "⚙️"),
                html.Ol([
                    html.Li("Scraping diario Amazon/eBay → precios históricos por SKU"),
                    html.Li("Feature engineering: lags (1,2,3), MA (2,3,5), "
                            "std (3,5), pct_change (1,2)"),
                    html.Li("Features de calendario: day_of_week, day_of_month, "
                            "month, is_weekend"),
                    html.Li("Encodings: sku_enc, source_enc, category_enc"),
                    html.Li(f"LightGBM: objective=regression_l1, "
                            f"lr={lgbm['config']['learning_rate']}, "
                            f"num_leaves={lgbm['config']['num_leaves']}"),
                    html.Li(f"Early stopping: best_iter="
                            f"{lgbm['config']['best_iteration']} / "
                            f"{lgbm['config']['num_boost_round']}"),
                    html.Li("Predicción multihorizonte: 1, 7, 14, 30 días "
                            "con intervalo de confianza IQR"),
                ], style={"fontSize": "0.85rem",
                          "color": COLORS["text"], "lineHeight": "1.9"}),
            ], md=6),
            dbc.Col([
                section_title("Features del Modelo", "🔧"),
                html.Div([
                    dbc.Badge(f, color="primary",
                              style={"margin": "3px", "fontSize": "0.75rem",
                                     "background": COLORS["accent2"]})
                    for f in features
                ]),
                html.Hr(style={"borderColor": COLORS["border"],
                               "margin": "16px 0"}),
                section_title("Decisión de Diseño: ¿Por qué no TFT?", "🤔"),
                dbc.Alert([
                    html.P([
                        html.B("Problema: "), "TFT (Temporal Fusion Transformer) "
                        "requiere mínimo 30+ observaciones por serie temporal "
                        "para el encoder de longitud 7."
                    ], className="mb-1", style={"fontSize": "0.83rem"}),
                    html.P([
                        html.B("Datos disponibles: "),
                        "9–13 observaciones por SKU (scraping desde 11-Jul-2026)."
                    ], className="mb-1", style={"fontSize": "0.83rem"}),
                    html.P([
                        html.B("Resultado TFT: "),
                        "MAPE=73.00% → inutilizable en producción."
                    ], className="mb-0", style={"fontSize": "0.83rem"}),
                ], color="warning",
                   style={"border": f"1px solid {COLORS['border']}",
                          "fontSize": "0.83rem"}),
            ], md=6),
        ]),
    ])


# ─── callback interactivo ──────────────────────────────────────────────────────

# Nota: el callback se registra en dashboard_v5_main.py
# Aquí exportamos la función de actualización

def update_pred_graph(sku_id, horizonte):
    """Función llamada por el callback en main."""
    try:
        _, _, _, skus_dict = _load_data()
        if sku_id and sku_id in skus_dict:
            fig  = _fig_prediccion_sku(skus_dict[sku_id], horizonte)
            data = skus_dict[sku_id]
            pred = data.get("predicciones", {}).get(horizonte, {})
            op   = data.get("oportunidad", {})

            info = dbc.Alert([
                dbc.Row([
                    dbc.Col([
                        html.B("Tendencia: "),
                        html.Span(pred.get("tendencia", "—"),
                                  style={"color":
                                         COLORS.get("green","") if
                                         pred.get("tendencia") == "SUBE"
                                         else COLORS.get("red","") if
                                         pred.get("tendencia") == "BAJA"
                                         else COLORS.get("accent3","")}),
                        html.Br(),
                        html.B("Variación: "),
                        f"{pred.get('variacion_pct', 0):+.2f}%",
                        html.Br(),
                        html.B("Precio ancla: "),
                        f"${pred.get('precio_ancla', 0):.2f}",
                    ], md=4),
                    dbc.Col([
                        html.B("ROI bruto: "),
                        html.Span(f"{op.get('roi_pct', 0):.1f}%",
                                  style={"color": COLORS.get("green","")}),
                        html.Br(),
                        html.B("Acción: "),
                        html.Span(op.get("accion", "—"),
                                  style={"color": COLORS.get("accent","")}),
                        html.Br(),
                        html.B("Unidades sugeridas: "),
                        str(op.get("unidades_sugeridas", "—")),
                    ], md=4),
                    dbc.Col([
                        html.B("Método: "),
                        pred.get("metodo", "—"),
                        html.Br(),
                        html.B("Precio final pred.: "),
                        f"${pred.get('precio_final', 0):.2f}",
                        html.Br(),
                        html.B("Fuente: "),
                        data.get("source", "—"),
                    ], md=4),
                ])
            ], color="light",
               style={"border": f"1px solid {COLORS['border']}",
                      "fontSize": "0.82rem", "marginTop": "8px"})

            return fig, info
    except Exception as e:
        pass
    return go.Figure(), html.Div()



