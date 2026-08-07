# pages/arbitraje_roi.py
# HDS-ROI v6.1 — Página de Oportunidades de Arbitraje
# Integrada al sistema multi-página del dashboard

import json
import dash
from dash import html, dcc, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from pathlib import Path
from config_v6 import COLORS, CARD_STYLE, CONTENT_STYLE
from components_v6 import crear_header, crear_seccion, crear_alerta, crear_kpi_card

dash.register_page(__name__, path="/arbitraje", name="Arbitraje ROI", order=10)

TC = 3.75

# ── Cargar datos ────────────────────────────────────────────────────────────
def _cargar_modelos():
    path = Path("data/raw/precios_por_modelo.json")
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _cargar_simulacion():
    path = Path("data/raw/simulacion_capital.json")
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# ── Helpers visuales ────────────────────────────────────────────────────────
def _badge_senal(roi):
    if roi > 40:
        return dbc.Badge("🟢 COMPRAR", color="success", pill=True, className="ms-1")
    elif roi > 10:
        return dbc.Badge("🟡 EVALUAR", color="warning", pill=True, className="ms-1")
    elif roi > 0:
        return dbc.Badge("⚪ MARGINAL", color="secondary", pill=True, className="ms-1")
    return dbc.Badge("🔴 EVITAR", color="danger", pill=True, className="ms-1")

def _badge_conf(conf):
    color = "success" if conf == "alta" else "warning"
    return dbc.Badge(conf.upper(), color=color, pill=True, className="ms-1")

def _color_roi(roi):
    if roi > 40:  return "#27ae60"
    if roi > 10:  return "#f39c12"
    if roi > 0:   return "#7f8c8d"
    return "#e74c3c"

# ── Construir tabla de ranking ───────────────────────────────────────────────
def _tabla_ranking(data):
    if not data:
        return html.P("No hay datos disponibles.", className="text-muted")

    filas = []
    for i, (modelo, d) in enumerate(data.items(), 1):
        compra   = d.get("precio_compra_fusionado", d["precio_compra_china_usd"])
        costo    = d["costo_importado_usd"]
        venta    = d["precio_venta_pe_usd"]
        ganancia = round(venta * 0.95 - costo, 2)
        roi      = d["roi_pct"]
        fuente   = d.get("fuente_precio", "aliexpress")

        filas.append(html.Tr([
            html.Td(f"#{i}", style={"color": "#888", "fontSize": "0.8rem"}),
            html.Td(html.Strong(modelo.upper()), style={"fontSize": "0.85rem"}),
            html.Td(f"${compra:,.2f}"),
            html.Td(f"${costo:,.2f}"),
            html.Td(f"${venta:,.2f}"),
            html.Td([
                html.Strong(f"${ganancia:,.2f}", style={"color": "#27ae60"}),
                html.Br(),
                html.Small(f"S/{ganancia*TC:,.0f}", style={"color": "#888"}),
            ]),
            html.Td(
                html.Strong(f"{roi:.1f}%", style={"color": _color_roi(roi), "fontSize": "1rem"}),
            ),
            html.Td(_badge_senal(roi)),
            html.Td(_badge_conf(d["confianza"])),
            html.Td(html.Small(fuente, style={"color": "#aaa"})),
        ], style={"borderLeft": f"3px solid {_color_roi(roi)}"}))

    return dbc.Table(
        [
            html.Thead(html.Tr([
                html.Th("#"), html.Th("Modelo"), html.Th("Compra $"),
                html.Th("Costo Imp."), html.Th("Venta PE $"), html.Th("Ganancia"),
                html.Th("ROI"), html.Th("Señal"), html.Th("Confianza"), html.Th("Fuente"),
            ], style={"backgroundColor": "#f8f9fa", "fontSize": "0.82rem"})),
            html.Tbody(filas),
        ],
        bordered=True, hover=True, responsive=True, size="sm",
        style={"fontSize": "0.85rem"},
    )

# ── Gráfico de barras ROI ────────────────────────────────────────────────────
def _grafico_roi(data):
    if not data:
        return go.Figure()
    modelos  = [m.upper() for m in data.keys()]
    rois     = [d["roi_pct"] for d in data.values()]
    colores  = [_color_roi(r) for r in rois]

    fig = go.Figure(go.Bar(
        x=rois, y=modelos, orientation="h",
        marker_color=colores,
        text=[f"{r:.1f}%" for r in rois],
        textposition="outside",
    ))
    fig.update_layout(
        title="ROI por Modelo (%)",
        xaxis_title="ROI (%)",
        height=max(300, len(modelos) * 38),
        margin=dict(l=10, r=60, t=40, b=10),
        plot_bgcolor="white",
        paper_bgcolor="white",
        xaxis=dict(gridcolor="#eee"),
        yaxis=dict(autorange="reversed"),
        font=dict(size=11),
    )
    fig.add_vline(x=10, line_dash="dash", line_color="#f39c12",
                  annotation_text="Umbral 10%", annotation_position="top right")
    fig.add_vline(x=40, line_dash="dash", line_color="#27ae60",
                  annotation_text="Zona COMPRAR", annotation_position="top right")
    return fig

# ── Gráfico simulación de capital ────────────────────────────────────────────
def _grafico_simulacion(data):
    ESCENARIOS = [1000, 3000, 5000, 10000]
    ganancias, rois_g = [], []

    for capital in ESCENARIOS:
        rentables = {m: d for m, d in data.items() if d["roi_pct"] > 10}
        cap_rest, ganancia_total, inversion_total = capital, 0.0, 0.0
        for modelo, d in rentables.items():
            costo = d["costo_importado_usd"]
            if cap_rest >= costo:
                ganancia_total += d["precio_venta_pe_usd"] * 0.95 - costo
                inversion_total += costo
                cap_rest -= costo
        roi_g = (ganancia_total / inversion_total * 100) if inversion_total > 0 else 0
        ganancias.append(round(ganancia_total, 2))
        rois_g.append(round(roi_g, 1))

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[f"${c:,}" for c in ESCENARIOS],
        y=ganancias,
        name="Ganancia USD",
        marker_color=["#7f8c8d", "#27ae60", "#2980b9", "#8e44ad"],
        text=[f"${g:,.0f}\nROI {r:.0f}%" for g, r in zip(ganancias, rois_g)],
        textposition="outside",
    ))
    fig.update_layout(
        title="Ganancia Proyectada por Capital Disponible",
        xaxis_title="Capital Inicial",
        yaxis_title="Ganancia Bruta (USD)",
        height=320,
        plot_bgcolor="white",
        paper_bgcolor="white",
        yaxis=dict(gridcolor="#eee"),
        margin=dict(l=10, r=10, t=40, b=10),
        showlegend=False,
    )
    # Marcar óptimo
    fig.add_annotation(
        x="$3,000", y=ganancias[1],
        text="⭐ ÓPTIMO",
        showarrow=True, arrowhead=2,
        font=dict(color="#27ae60", size=12),
        arrowcolor="#27ae60",
    )
    return fig

# ── KPI cards ────────────────────────────────────────────────────────────────
def _kpi_cards(data):
    if not data:
        return []
    top3     = list(data.items())[:3]
    rentables = sum(1 for d in data.values() if d["roi_pct"] > 10)
    mejor_roi = max(d["roi_pct"] for d in data.values())
    mejor_mod = max(data, key=lambda m: data[m]["roi_pct"]).upper()

    # Ganancia óptima con $3000
    cap_rest, ganancia_opt, inv_opt = 3000, 0.0, 0.0
    for m, d in data.items():
        if d["roi_pct"] > 10 and cap_rest >= d["costo_importado_usd"]:
            ganancia_opt += d["precio_venta_pe_usd"] * 0.95 - d["costo_importado_usd"]
            inv_opt += d["costo_importado_usd"]
            cap_rest -= d["costo_importado_usd"]
    roi_opt = (ganancia_opt / inv_opt * 100) if inv_opt > 0 else 0

    return dbc.Row([
        dbc.Col(crear_kpi_card("🏆 Mejor ROI",      f"+{mejor_roi:.1f}%",  mejor_mod,       "#27ae60"), md=3),
        dbc.Col(crear_kpi_card("✅ Modelos Rentables", f"{rentables}",      "ROI > 10%",     "#2980b9"), md=3),
        dbc.Col(crear_kpi_card("💰 Ganancia Óptima", f"${ganancia_opt:,.0f}", "Con $3,000 USD", "#8e44ad"), md=3),
        dbc.Col(crear_kpi_card("📈 ROI Global Óptimo", f"{roi_opt:.1f}%",  "Escenario $3k", "#e67e22"), md=3),
    ], className="mb-4")

# ── LAYOUT ───────────────────────────────────────────────────────────────────
def layout():
    data = _cargar_modelos()

    return html.Div([
        crear_header(
            "📊 Oportunidades de Arbitraje — HDS-ROI v6.1",
            "Análisis de rentabilidad de importación · eBay USA + AliExpress → Perú"
        ),

        crear_alerta(
            "success",
            "🚀 Sistema HDS-ROI v6.1 Activo",
            f"Índice cargado: {len(data)} modelos analizados. "
            f"Rentables (ROI > 10%): {sum(1 for d in data.values() if d['roi_pct']>10)}. "
            f"Tipo de cambio: S/{TC} por USD."
        ),

        # KPIs
        _kpi_cards(data),

        # Gráfico ROI
        crear_seccion("📈 Ranking de ROI por Modelo", dcc.Graph(
            figure=_grafico_roi(data),
            config={"displayModeBar": False},
        )),

        # Tabla ranking
        crear_seccion("📋 Ranking Completo", _tabla_ranking(data)),

        # Simulación capital
        crear_seccion("💰 Simulación por Capital Disponible", dcc.Graph(
            figure=_grafico_simulacion(data),
            config={"displayModeBar": False},
        )),

        # Supuestos
        dbc.Alert([
            html.Strong("⚙️ Supuestos del modelo: "),
            "Costo importación = precio compra × 1.30 · ",
            "Precio venta PE = 95% del precio mercado local · ",
            f"Tipo de cambio = S/{TC}/USD · ",
            "Fuente: eBay USA (70%) + AliExpress (30%) · ",
            "Filtro: CPUs Mobile excluidos",
        ], color="light", className="mt-3 text-muted", style={"fontSize": "0.82rem"}),

    ], style=CONTENT_STYLE)
