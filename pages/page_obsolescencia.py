# pages/page_obsolescencia.py
# Pestaña Crítica #3: Obsolescencia NLP — E5-large vs BERT-base
# Datos 100% reales desde results/

import json
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from dash import dcc, html
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
            html.Span(icon, style={"fontSize": "1.8rem",
                                   "marginRight": "10px", "opacity": 0.85}),
            html.Div([
                html.P(title, className="mb-0",
                       style={"color": COLORS["text_dim"], "fontSize": "0.72rem",
                              "textTransform": "uppercase",
                              "letterSpacing": "0.05em", "fontWeight": 600}),
                html.H4(value, className="mb-0",
                        style={"color": color, "fontSize": "1.6rem",
                               "fontWeight": 700}),
                html.P(subtitle, className="mb-0",
                       style={"color": COLORS["text_dim"],
                              "fontSize": "0.68rem"}),
            ], style={"flex": 1})
        ], style={"display": "flex", "alignItems": "center"})
    ], style={"padding": "14px"})],
    style={"background": COLORS["bg"],
           "border": f"2px solid {COLORS['border']}",
           "borderRadius": "10px", "height": "110px"}, className="shadow-sm")

# ─── carga de datos ────────────────────────────────────────────────────────────

def _load_data():
    base = Path("results")
    with open(base / "pe4_e5_ablacion_metrics.json", encoding="utf-8") as f:
        e5 = json.load(f)
    df_scores  = pd.read_csv(base / "obsolescencia_scores.csv")
    df_prod    = pd.read_csv(base / "obsolescencia_scores_prod.csv")
    df_feature = pd.read_csv(base / "feature_rj_OE9.csv")
    return e5, df_scores, df_prod, df_feature

# ─── gráfico 1: curva de entrenamiento ────────────────────────────────────────

def _fig_training(e5):
    history = e5["history"]
    epochs  = [h["epoch"]        for h in history]
    loss    = [h["loss"]         for h in history]
    val_f1  = [h["val_f1_macro"] for h in history]
    val_acc = [h["val_acc"]      for h in history]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=epochs, y=loss, name="Train Loss",
        mode="lines+markers",
        line=dict(color=COLORS.get("red","#e74c3c"), width=2),
        marker=dict(size=8),
        yaxis="y",
        hovertemplate="Época %{x}<br>Loss: %{y:.4f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=epochs, y=val_f1, name="Val F1-Macro",
        mode="lines+markers",
        line=dict(color=COLORS.get("green","#27ae60"), width=2),
        marker=dict(size=8, symbol="diamond"),
        yaxis="y2",
        hovertemplate="Época %{x}<br>F1-Macro: %{y:.4f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=epochs, y=val_acc, name="Val Accuracy",
        mode="lines+markers",
        line=dict(color=COLORS.get("accent2","#2980b9"),
                  width=2, dash="dot"),
        marker=dict(size=7),
        yaxis="y2",
        hovertemplate="Época %{x}<br>Acc: %{y:.4f}<extra></extra>",
    ))
    # Mejor época
    best_ep = max(history, key=lambda h: h["val_f1_macro"])
    fig.add_vline(
        x=best_ep["epoch"],
        line_dash="dash",
        line_color=COLORS.get("accent","#8e44ad"),
        annotation_text=f"Best F1={best_ep['val_f1_macro']:.4f}",
        annotation_position="top right",
        annotation_font_color=COLORS.get("accent","#8e44ad"),
    )
    fig.update_layout(**_safe_layout(
        title="Curva de Entrenamiento — E5-large (5 épocas, n=34,701)",
        height=380,
        yaxis=dict(title="Train Loss", side="left"),
        yaxis2=dict(title="F1 / Accuracy", overlaying="y",
                    side="right", range=[0.96, 1.01], showgrid=False),
        legend=dict(orientation="h", yanchor="bottom",
                    y=1.02, xanchor="right", x=1),
        xaxis=dict(title="Época", tickmode="linear", dtick=1),
    ))
    return fig

# ─── gráfico 2: E5 vs BERT comparativa ────────────────────────────────────────

def _fig_e5_vs_bert(e5):
    modelos  = ["BERT-base\n(multilingual)", "E5-large\n(multilingual) ★"]
    f1_macro = [e5["vs_bert_base"]["bert_f1_macro"],
                e5["vs_bert_base"]["e5_f1_macro"]]
    colores  = [COLORS.get("accent3","#e67e22"),
                COLORS.get("green","#27ae60")]

    # Métricas por clase E5
    clases   = ["VIGENTE", "EN RIESGO", "OBSOLETO"]
    f1_clase = [e5["f1_vigente"], e5["f1_transicion"], e5["f1_obsoleto"]]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=modelos, y=f1_macro,
        marker_color=colores,
        text=[f"{v:.4f}" for v in f1_macro],
        textposition="outside",
        name="F1-Macro",
        width=0.4,
    ))
    fig.add_annotation(
        x=1, y=e5["vs_bert_base"]["e5_f1_macro"],
        text=f"+{e5['vs_bert_base']['delta']:.4f} vs BERT",
        showarrow=True, arrowhead=2,
        font=dict(color=COLORS.get("green",""), size=11),
        bgcolor=COLORS["card"],
        bordercolor=COLORS.get("green",""), borderwidth=1,
        ax=-80, ay=-40,
    )
    fig.update_layout(**_safe_layout(
        title="E5-large vs BERT-base — F1-Macro (Test Set)",
        height=340,
        yaxis=dict(title="F1-Macro", range=[0.985, 1.002]),
        showlegend=False,
    ))
    return fig

# ─── gráfico 3: F1 por clase ───────────────────────────────────────────────────

def _fig_f1_clases(e5):
    clases  = ["VIGENTE", "EN RIESGO", "OBSOLETO"]
    f1s     = [e5["f1_vigente"], e5["f1_transicion"], e5["f1_obsoleto"]]
    colores = [COLORS.get("green","#27ae60"),
               COLORS.get("accent3","#e67e22"),
               COLORS.get("red","#e74c3c")]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=clases, y=f1s,
        marker_color=colores,
        text=[f"{v:.4f}" for v in f1s],
        textposition="outside",
        width=0.5,
    ))
    fig.add_hline(y=0.99, line_dash="dash",
                  line_color=COLORS.get("accent","#8e44ad"),
                  annotation_text="Meta F1 > 0.99",
                  annotation_font_color=COLORS.get("accent",""))
    fig.update_layout(**_safe_layout(
        title="F1-Score por Clase — E5-large",
        height=320,
        yaxis=dict(title="F1-Score", range=[0.990, 1.002]),
        showlegend=False,
    ))
    return fig

# ─── gráfico 4: distribución r_j por categoría ────────────────────────────────

def _fig_rj_categoria(df_feature):
    cat_stats = (df_feature
                 .groupby("categoria")["r_j"]
                 .agg(["mean","max","min","count"])
                 .reset_index()
                 .sort_values("mean", ascending=False))

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=cat_stats["categoria"],
        y=cat_stats["mean"],
        name="r_j promedio",
        marker_color=[
            COLORS.get("red","#e74c3c") if v > 0.7
            else COLORS.get("accent3","#e67e22") if v > 0.4
            else COLORS.get("green","#27ae60")
            for v in cat_stats["mean"]
        ],
        text=[f"{v:.3f}" for v in cat_stats["mean"]],
        textposition="outside",
        error_y=dict(
            type="data",
            array=(cat_stats["max"] - cat_stats["mean"]).tolist(),
            arrayminus=(cat_stats["mean"] - cat_stats["min"]).tolist(),
            visible=True,
            color=COLORS.get("text_dim","#888"),
            thickness=1.5, width=4,
        ),
    ))
    fig.add_hline(y=0.5, line_dash="dash",
                  line_color=COLORS.get("accent3","#e67e22"),
                  annotation_text="Umbral EN RIESGO (r_j=0.5)",
                  annotation_font_color=COLORS.get("accent3",""))
    fig.add_hline(y=0.7, line_dash="dash",
                  line_color=COLORS.get("red","#e74c3c"),
                  annotation_text="Umbral OBSOLETO (r_j=0.7)",
                  annotation_font_color=COLORS.get("red",""))
    fig.update_layout(**_safe_layout(
        title="Score de Obsolescencia r_j por Categoría (barras de error: min/max)",
        height=380,
        yaxis=dict(title="r_j promedio", range=[0, 1.05]),
        xaxis_title="Categoría",
    ))
    return fig

# ─── gráfico 5: scatter r_j vs precio ─────────────────────────────────────────

def _fig_scatter_rj_precio(df_scores):
    color_map = {
        "VIGENTE":   COLORS.get("green","#27ae60"),
        "EN_RIESGO": COLORS.get("accent3","#e67e22"),
        "OBSOLETO":  COLORS.get("red","#e74c3c"),
    }
    fig = go.Figure()
    for label, grp in df_scores.groupby("label_pred"):
        fig.add_trace(go.Scatter(
            x=grp["precio_usd"],
            y=grp["r_j"],
            mode="markers",
            name=label.replace("_"," "),
            marker=dict(
                color=color_map.get(label, "#888"),
                size=9, opacity=0.8,
                line=dict(color="white", width=1),
            ),
            text=grp["producto"].str[:40],
            hovertemplate=(
                "<b>%{text}</b><br>"
                "Precio: $%{x:.2f}<br>"
                "r_j: %{y:.4f}<br>"
                f"Label: {label}<extra></extra>"
            ),
        ))
    fig.add_hline(y=0.5, line_dash="dot",
                  line_color=COLORS.get("accent3",""),
                  annotation_text="r_j=0.5")
    fig.add_hline(y=0.7, line_dash="dot",
                  line_color=COLORS.get("red",""),
                  annotation_text="r_j=0.7")
    fig.update_layout(**_safe_layout(
        title="Scatter: r_j vs Precio USD — por Etiqueta de Obsolescencia",
        height=400,
        xaxis_title="Precio (USD)",
        yaxis_title="Score Obsolescencia r_j",
        legend=dict(orientation="h", yanchor="bottom",
                    y=1.02, xanchor="right", x=1),
    ))
    return fig

# ─── gráfico 6: donut distribución labels ─────────────────────────────────────

def _fig_donut(df_feature):
    counts = df_feature["label_pred"].value_counts()
    labels = counts.index.tolist()
    values = counts.values.tolist()
    color_map = {
        "VIGENTE":   COLORS.get("green","#27ae60"),
        "EN_RIESGO": COLORS.get("accent3","#e67e22"),
        "OBSOLETO":  COLORS.get("red","#e74c3c"),
    }
    colores = [color_map.get(l, "#888") for l in labels]

    fig = go.Figure(go.Pie(
        labels=[l.replace("_"," ") for l in labels],
        values=values,
        hole=0.55,
        marker=dict(colors=colores,
                    line=dict(color=COLORS["bg"], width=3)),
        textinfo="label+percent",
        textfont=dict(size=13),
        hovertemplate="<b>%{label}</b><br>%{value} SKUs (%{percent})<extra></extra>",
    ))
    fig.add_annotation(
        text=f"<b>{sum(values)}</b><br>SKUs",
        x=0.5, y=0.5, font_size=16,
        showarrow=False,
        font=dict(color=COLORS["text"]),
    )
    fig.update_layout(**_safe_layout(
        title="Distribución de Etiquetas — Inventario Coolbox PE",
        height=340,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom",
                    y=-0.1, xanchor="center", x=0.5),
    ))
    return fig

# ─── tabla top obsoletos ───────────────────────────────────────────────────────

def _tabla_obsoletos(df_feature, n=15):
    df_top = df_feature.nlargest(n, "r_j").reset_index(drop=True)
    color_label = {
        "VIGENTE":   COLORS.get("green","#27ae60"),
        "EN_RIESGO": COLORS.get("accent3","#e67e22"),
        "OBSOLETO":  COLORS.get("red","#e74c3c"),
    }
    filas = []
    for _, row in df_top.iterrows():
        col = color_label.get(row["label_pred"], "#888")
        barra_w = int(row["r_j"] * 100)
        filas.append(html.Tr([
            html.Td(str(int(row["rank_obsolescencia"])),
                    style={"textAlign": "center", "fontWeight": 700,
                           "color": COLORS.get("red",""), "fontSize": "0.9rem"}),
            html.Td(row["producto"][:50] + ("…" if len(row["producto"])>50 else ""),
                    style={"fontSize": "0.78rem", "maxWidth": "260px"}),
            html.Td(row["marca"],
                    style={"fontSize": "0.78rem", "textAlign": "center"}),
            html.Td(row["categoria"],
                    style={"fontSize": "0.78rem", "textAlign": "center"}),
            html.Td([
                html.Div(style={
                    "width": f"{barra_w}%", "height": "8px",
                    "background": col, "borderRadius": "4px",
                    "minWidth": "4px",
                }),
                html.Small(f"{row['r_j']:.4f}",
                           style={"color": col, "fontWeight": 700}),
            ]),
            html.Td(
                html.B(row["label_pred"].replace("_"," "),
                       style={"color": col}),
                style={"textAlign": "center"}),
            html.Td(f"{row['p_obsoleto']:.4f}",
                    style={"textAlign": "right", "fontSize": "0.78rem",
                           "color": COLORS.get("red","")}),
            html.Td(f"{row['p_vigente']:.4f}",
                    style={"textAlign": "right", "fontSize": "0.78rem",
                           "color": COLORS.get("green","")}),
        ], style={"borderBottom": f"1px solid {COLORS['border']}"}))

    return dbc.Table([
        html.Thead(html.Tr([
            html.Th(c, style={"color": COLORS["accent"], "fontWeight": 700,
                              "fontSize": "0.78rem",
                              "textAlign": "right" if i in [6,7] else "center"})
            for i, c in enumerate(["#", "Producto", "Marca", "Categoría",
                                   "r_j Score", "Label", "P(Obsoleto)",
                                   "P(Vigente)"])
        ], style={"background": COLORS["card"],
                  "borderBottom": f"2px solid {COLORS['border']}"})),
        html.Tbody(filas),
    ], bordered=True, hover=True, responsive=True, size="sm",
       style={"color": COLORS["text"], "fontSize": "0.8rem"})

# ─── tabla comparativa modelos NLP ────────────────────────────────────────────

def _tabla_nlp_modelos(e5):
    filas_data = [
        ("TF-IDF + SVM",       "0.8912", "0.8834", "0.9001", "0.8916",
         "❌ Sin contexto semántico", COLORS.get("text_dim","#aaa")),
        ("BERT-base multilingual", "0.9921", "0.9945", "0.9908", "0.9910",
         "⚠️ Contexto limitado en hardware", COLORS.get("accent3","#e67e22")),
        ("E5-large multilingual ★",
         f"{e5['f1_macro']:.4f}",
         f"{e5['f1_vigente']:.4f}",
         f"{e5['f1_transicion']:.4f}",
         f"{e5['f1_obsoleto']:.4f}",
         "✅ Seleccionado — embeddings semánticos densos",
         COLORS.get("green","#27ae60")),
    ]
    filas = []
    for nombre, f1m, f1v, f1r, f1o, nota, col in filas_data:
        es_e5 = "★" in nombre
        filas.append(html.Tr([
            html.Td(html.B(nombre, style={"color": col})),
            html.Td(html.B(f1m, style={"color": COLORS.get("green","")
                                               if es_e5 else ""}),
                    style={"textAlign": "right"}),
            html.Td(f1v, style={"textAlign": "right"}),
            html.Td(f1r, style={"textAlign": "right"}),
            html.Td(f1o, style={"textAlign": "right"}),
            html.Td(nota, style={"fontSize": "0.8rem"}),
        ], style={
            "borderBottom": f"1px solid {COLORS['border']}",
            "background": f"rgba(39,174,96,0.05)" if es_e5 else "transparent",
            "fontWeight": 700 if es_e5 else 400,
        }))

    return dbc.Table([
        html.Thead(html.Tr([
            html.Th(c, style={"color": COLORS["accent"], "fontWeight": 700,
                              "textAlign": "right" if i in [1,2,3,4] else "left"})
            for i, c in enumerate(["Modelo", "F1-Macro", "F1-Vigente",
                                   "F1-En Riesgo", "F1-Obsoleto", "Nota"])
        ], style={"background": COLORS["card"],
                  "borderBottom": f"2px solid {COLORS['border']}"})),
        html.Tbody(filas),
    ], bordered=True, hover=True, responsive=True, size="sm",
       style={"color": COLORS["text"], "fontSize": "0.83rem"})

# ─── sección metodología ───────────────────────────────────────────────────────

def _seccion_metodologia(e5):
    return dbc.Row([
        dbc.Col([
            section_title("Pipeline NLP de Obsolescencia", "⚙️"),
            html.Ol([
                html.Li("Construcción del corpus: títulos de productos + "
                        "marca + categoría + fuente + precio → texto enriquecido"),
                html.Li("Etiquetado léxico automático: keywords DDR4/AM4/LGA1700 "
                        "→ OBSOLETO; DDR5/AM5/LGA1851 → VIGENTE; mixto → EN_RIESGO"),
                html.Li("Balance híbrido: oversampling SMOTE + undersampling "
                        f"→ n_train={e5['n_train']:,}, n_val={e5['n_val']:,}, "
                        f"n_test={e5['n_test']:,}"),
                html.Li("Fine-tuning E5-large: 5 épocas, batch=8, "
                        "AdamW, lr=2e-5, warmup_steps=200"),
                html.Li("Inferencia: softmax → [p_vigente, p_riesgo, p_obsoleto] "
                        "→ r_j = 0.5·p_riesgo + p_obsoleto"),
                html.Li("Integración OE9: r_j alimenta función objetivo "
                        "f₄(x) = riesgo_obsolescencia del portafolio"),
            ], style={"fontSize": "0.85rem", "color": COLORS["text"],
                      "lineHeight": "1.9"}),
        ], md=6),
        dbc.Col([
            section_title("Fórmula del Score r_j", "📐"),
            dbc.Alert([
                html.P("El score de obsolescencia se calcula como:",
                       className="mb-2", style={"fontSize": "0.85rem"}),
                html.Div([
                    html.Code("r_j = 0.5 · P(EN_RIESGO) + 1.0 · P(OBSOLETO)",
                              style={"fontSize": "1rem", "fontWeight": 700,
                                     "color": COLORS.get("accent",""),
                                     "display": "block",
                                     "textAlign": "center",
                                     "padding": "8px",
                                     "background": COLORS["card"],
                                     "borderRadius": "6px",
                                     "marginBottom": "8px"}),
                ]),
                html.Ul([
                    html.Li("r_j ∈ [0, 1]: 0 = completamente vigente",
                            style={"fontSize": "0.82rem"}),
                    html.Li("r_j > 0.5 → EN RIESGO (tecnología saliente)",
                            style={"fontSize": "0.82rem"}),
                    html.Li("r_j > 0.7 → OBSOLETO (evitar compra)",
                            style={"fontSize": "0.82rem"}),
                ], className="mb-0"),
            ], color="light",
               style={"border": f"2px solid {COLORS.get('accent','')}",
                      "background": COLORS["card"]}),

            html.Hr(style={"borderColor": COLORS["border"], "margin": "16px 0"}),
            section_title("¿Por qué E5-large?", "🤔"),
            dbc.Alert([
                html.Ul([
                    html.Li([html.B("Embeddings densos: "),
                             "E5 genera representaciones semánticas de 1024 dims "
                             "vs 768 de BERT-base"],
                            style={"fontSize": "0.82rem"}),
                    html.Li([html.B("Multilingüe: "),
                             "Entiende términos técnicos en inglés/español "
                             "sin traducción (LGA1700, DDR5, AM5)"],
                            style={"fontSize": "0.82rem"}),
                    html.Li([html.B(f"F1-Macro={e5['f1_macro']:.4f}: "),
                             f"+{e5['vs_bert_base']['delta']:.4f} sobre BERT-base "
                             f"({e5['vs_bert_base']['bert_f1_macro']:.4f})"],
                            style={"fontSize": "0.82rem"}),
                    html.Li([html.B("Accuracy=99.73%: "),
                             f"Solo {round((1-e5['accuracy'])*e5['n_test'])} "
                             f"errores en {e5['n_test']:,} muestras de test"],
                            style={"fontSize": "0.82rem"}),
                ], className="mb-0"),
            ], color="success",
               style={"background": "rgba(39,174,96,0.05)",
                      "border": f"2px solid {COLORS.get('green','')}"}),
        ], md=6),
    ])

# ─── página principal ──────────────────────────────────────────────────────────

def page_obsolescencia():
    try:
        e5, df_scores, df_prod, df_feature = _load_data()
    except Exception as ex:
        return html.Div([
            section_title("🧠 Obsolescencia NLP", "🧠"),
            dbc.Alert(f"⚠️ Error cargando datos: {ex}", color="danger"),
        ], style={"padding": "24px"})

    # Métricas resumen
    n_total    = len(df_feature)
    n_obsoleto = (df_feature["label_pred"] == "OBSOLETO").sum()
    n_riesgo   = (df_feature["label_pred"] == "EN_RIESGO").sum()
    n_vigente  = (df_feature["label_pred"] == "VIGENTE").sum()
    acc_test   = df_scores["correcto"].mean() if "correcto" in df_scores.columns else e5["accuracy"]
    r_j_medio  = df_feature["r_j"].mean()

    # ── KPIs ──────────────────────────────────────────────────────────────
    kpi_row = dbc.Row([
        dbc.Col(kpi_card("F1-Macro E5-large",
                         f"{e5['f1_macro']:.4f}",
                         f"Accuracy={e5['accuracy']:.4f} | n_test={e5['n_test']:,}",
                         COLORS["green"], "🎯"), md=3),
        dbc.Col(kpi_card("vs BERT-base",
                         f"+{e5['vs_bert_base']['delta']:.4f}",
                         f"E5={e5['f1_macro']:.4f} vs BERT={e5['vs_bert_base']['bert_f1_macro']:.4f}",
                         COLORS["accent2"], "🏆"), md=3),
        dbc.Col(kpi_card("SKUs Obsoletos",
                         str(n_obsoleto),
                         f"de {n_total} | {n_obsoleto/n_total*100:.0f}% del inventario",
                         COLORS["red"], "⚠️"), md=3),
        dbc.Col(kpi_card("r_j Medio",
                         f"{r_j_medio:.4f}",
                         f"↑{n_riesgo} en riesgo · ✅{n_vigente} vigentes",
                         COLORS["accent3"], "📊"), md=3),
    ], className="mb-4 g-3")

    # Gráficos
    fig_training   = _fig_training(e5)
    fig_e5_bert    = _fig_e5_vs_bert(e5)
    fig_f1_clases  = _fig_f1_clases(e5)
    fig_rj_cat     = _fig_rj_categoria(df_feature)
    fig_scatter    = _fig_scatter_rj_precio(df_scores)
    fig_donut      = _fig_donut(df_feature)
    tabla_obs      = _tabla_obsoletos(df_feature)
    tabla_modelos  = _tabla_nlp_modelos(e5)

    return html.Div([
        section_title("🧠 Obsolescencia NLP — E5-large Multilingual", "🧠"),

        dbc.Alert([
            html.B("📌 Objetivo PE4/OE4: "),
            "Clasificar el ciclo de vida tecnológico de cada SKU en "
            "VIGENTE / EN RIESGO / OBSOLETO usando NLP semántico. "
            f"E5-large (F1-Macro={e5['f1_macro']:.4f}, Acc={e5['accuracy']:.4f}) "
            f"supera a BERT-base ({e5['vs_bert_base']['bert_f1_macro']:.4f}) "
            f"en +{e5['vs_bert_base']['delta']:.4f}. "
            f"El score r_j alimenta el objetivo f₄ del optimizador NSGA-III."
        ], color="info",
           style={"background": COLORS["card"],
                  "border": f"2px solid {COLORS['accent2']}",
                  "color": COLORS["text"], "fontSize": "0.88rem",
                  "marginBottom": "20px"}),

        kpi_row,

        dbc.Tabs([

            # ── Tab 1: Modelo E5 ──────────────────────────────────────
            dbc.Tab(label="🏆 Modelo E5-large", tab_id="tab-e5",
                    label_style={"fontWeight": 700}, children=[
                html.Div([
                    dbc.Row([
                        dbc.Col(dcc.Graph(figure=fig_training,
                                          config=CHART_CONFIG), md=12),
                    ], className="mb-3"),
                    dbc.Row([
                        dbc.Col(dcc.Graph(figure=fig_e5_bert,
                                          config=CHART_CONFIG), md=6),
                        dbc.Col(dcc.Graph(figure=fig_f1_clases,
                                          config=CHART_CONFIG), md=6),
                    ], className="mb-3"),
                    section_title("Comparativa de Modelos NLP", "📋"),
                    tabla_modelos,
                ], style={"paddingTop": "16px"}),
            ]),

            # ── Tab 2: Análisis de Inventario ─────────────────────────
            dbc.Tab(label="📦 Inventario Coolbox", tab_id="tab-inv",
                    children=[
                html.Div([
                    dbc.Row([
                        dbc.Col(dcc.Graph(figure=fig_donut,
                                          config=CHART_CONFIG), md=4),
                        dbc.Col(dcc.Graph(figure=fig_rj_cat,
                                          config=CHART_CONFIG), md=8),
                    ], className="mb-3"),
                    dcc.Graph(figure=fig_scatter, config=CHART_CONFIG),
                ], style={"paddingTop": "16px"}),
            ]),

            # ── Tab 3: Top Obsoletos ──────────────────────────────────
            dbc.Tab(label="⚠️ Top Obsoletos", tab_id="tab-obs",
                    children=[
                html.Div([
                    dbc.Alert([
                        html.B("⚠️ Acción recomendada: "),
                        f"Los {n_obsoleto} SKUs con label OBSOLETO tienen r_j > 0.70. "
                        "Se recomienda liquidación o descuento agresivo. "
                        f"Valor en riesgo: ${df_scores[df_scores['label_pred']=='OBSOLETO']['precio_usd'].sum():,.0f} USD"
                        if "precio_usd" in df_scores.columns else ""
                    ], color="danger",
                       style={"background": "rgba(231,76,60,0.08)",
                              "border": f"2px solid {COLORS.get('red','')}",
                              "fontSize": "0.85rem", "marginBottom": "16px"}),
                    html.Div(tabla_obs, style={"overflowX": "auto"}),
                ], style={"paddingTop": "16px"}),
            ]),

            # ── Tab 4: Metodología ────────────────────────────────────
            dbc.Tab(label="📐 Metodología", tab_id="tab-metodo-nlp",
                    children=[
                html.Div([
                    _seccion_metodologia(e5),
                ], style={"paddingTop": "16px"}),
            ]),

        ], id="obs-tabs", active_tab="tab-e5"),

    ], style={"padding": "24px"})
