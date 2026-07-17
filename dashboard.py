#!/usr/bin/env python3
"""
dashboard.py — HDS-ROI Dashboard v1.0
Sistema de Inteligencia de Precios — Hardware Peru
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

# ── Config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="HDS-ROI | Hardware Peru",
    page_icon="🖥️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, #1e3a5f 0%, #2d6a9f 100%);
        border-radius: 12px; padding: 20px; color: white;
        text-align: center; margin: 5px;
    }
    .metric-value { font-size: 2.2rem; font-weight: 700; }
    .metric-label { font-size: 0.85rem; opacity: 0.85; margin-top: 4px; }
    .section-title {
        font-size: 1.1rem; font-weight: 600; color: #2d6a9f;
        border-left: 4px solid #2d6a9f; padding-left: 10px;
        margin: 20px 0 10px 0;
    }
    .stAlert { border-radius: 8px; }
    div[data-testid="metric-container"] {
        background: #f0f4f8; border-radius: 10px; padding: 15px;
        border: 1px solid #d0dce8;
    }
</style>
""", unsafe_allow_html=True)

# ── Carga de datos ─────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_data():
    paths = [
        Path("data/processed/MASTER_hardware_peru_clean.csv"),
        Path("../data/processed/MASTER_hardware_peru_clean.csv"),
    ]
    for p in paths:
        if p.exists():
            df = pd.read_csv(p, low_memory=False)
            # Limpiar precio
            df["price_pen"] = pd.to_numeric(df["price_pen"], errors="coerce")
            df["price_usd"] = pd.to_numeric(df.get("price_usd", pd.Series(dtype=float)), errors="coerce")
            df["discount_pct"] = pd.to_numeric(df.get("discount_pct", pd.Series(dtype=float)), errors="coerce")
            df["rating"] = pd.to_numeric(df.get("rating", pd.Series(dtype=float)), errors="coerce")
            # Filtrar precios anómalos
            df = df[(df["price_pen"] >= 10) & (df["price_pen"] <= 50000)]
            # Timestamp
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
            df["fecha"] = df["timestamp"].dt.date
            return df
    return pd.DataFrame()

df_raw = load_data()

# ── Sidebar ────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/computer.png", width=60)
    st.title("HDS-ROI Dashboard")
    st.caption("Sistema de Inteligencia de Precios — Hardware Peru")
    st.divider()

    if df_raw.empty:
        st.error("No se encontró el MASTER CSV")
        st.stop()

    # Filtros
    st.markdown("### 🔽 Filtros")

    fuentes_disponibles = sorted(df_raw["source"].dropna().unique().tolist())
    fuentes_sel = st.multiselect(
        "Fuente", fuentes_disponibles, default=fuentes_disponibles,
        help="Selecciona las tiendas a analizar"
    )

    cats_disponibles = sorted(df_raw["category"].dropna().unique().tolist())
    cats_sel = st.multiselect(
        "Categoría", cats_disponibles, default=cats_disponibles[:8]
    )

    precio_min, precio_max = st.slider(
        "Rango de precio (S/)",
        min_value=10, max_value=50000,
        value=(10, 15000), step=100
    )

    st.divider()
    st.caption(f"📅 Última actualización: {df_raw['timestamp'].max().strftime('%d/%m/%Y %H:%M') if not df_raw.empty else 'N/A'}")

# ── Filtrar datos ──────────────────────────────────────────────────────
df = df_raw[
    (df_raw["source"].isin(fuentes_sel)) &
    (df_raw["category"].isin(cats_sel)) &
    (df_raw["price_pen"] >= precio_min) &
    (df_raw["price_pen"] <= precio_max)
].copy()

# ── Header ─────────────────────────────────────────────────────────────
st.title("🖥️ HDS-ROI — Sistema de Inteligencia de Precios")
st.caption("Pipeline automatizado de scraping, predicción de demanda y optimización de rentabilidad — Hardware Perú")
st.divider()

# ── KPIs ───────────────────────────────────────────────────────────────
col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric("📦 Total Registros", f"{len(df):,}", delta=f"{len(df_raw):,} en MASTER")
with col2:
    st.metric("🏪 Fuentes Activas", f"{df['source'].nunique()}", delta="tiendas")
with col3:
    st.metric("🗂️ Categorías", f"{df['category'].nunique()}")
with col4:
    precio_med = df["price_pen"].median()
    st.metric("💰 Precio Mediano", f"S/ {precio_med:,.0f}")
with col5:
    desc_med = df["discount_pct"].dropna()
    st.metric("🏷️ Descuento Promedio", f"{desc_med.mean():.1f}%" if len(desc_med) > 0 else "N/A")

st.divider()

# ── Fila 1: Distribución por fuente y categoría ────────────────────────
st.markdown('<div class="section-title">📊 Distribución del Dataset</div>', unsafe_allow_html=True)
col_a, col_b = st.columns(2)

with col_a:
    source_counts = df["source"].value_counts().reset_index()
    source_counts.columns = ["Fuente", "Registros"]
    fig_src = px.bar(
        source_counts, x="Registros", y="Fuente", orientation="h",
        title="Registros por Fuente",
        color="Registros", color_continuous_scale="Blues",
        text="Registros"
    )
    fig_src.update_traces(texttemplate="%{text:,}", textposition="outside")
    fig_src.update_layout(height=350, showlegend=False, coloraxis_showscale=False,
                          yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig_src, use_container_width=True)

with col_b:
    cat_counts = df["category"].value_counts().reset_index()
    cat_counts.columns = ["Categoría", "Registros"]
    fig_cat = px.pie(
        cat_counts.head(10), values="Registros", names="Categoría",
        title="Top 10 Categorías",
        hole=0.4, color_discrete_sequence=px.colors.sequential.Blues_r
    )
    fig_cat.update_layout(height=350)
    st.plotly_chart(fig_cat, use_container_width=True)

# ── Fila 2: Precios por categoría ─────────────────────────────────────
st.markdown('<div class="section-title">💰 Análisis de Precios por Categoría</div>', unsafe_allow_html=True)

precio_cat = df.groupby("category")["price_pen"].agg(["median","mean","min","max","count"]).reset_index()
precio_cat.columns = ["Categoría","Mediana","Promedio","Mínimo","Máximo","N"]
precio_cat = precio_cat.sort_values("Mediana", ascending=False).head(15)

fig_box = px.box(
    df[df["category"].isin(precio_cat["Categoría"].tolist())],
    x="category", y="price_pen",
    title="Distribución de Precios por Categoría (S/)",
    color="category",
    color_discrete_sequence=px.colors.qualitative.Set3,
    labels={"category": "Categoría", "price_pen": "Precio (S/)"}
)
fig_box.update_layout(height=420, showlegend=False, xaxis_tickangle=-30)
fig_box.update_yaxis(type="log", title="Precio S/ (escala log)")
st.plotly_chart(fig_box, use_container_width=True)

# ── Fila 3: Comparativa de precios entre fuentes ───────────────────────
st.markdown('<div class="section-title">🏪 Comparativa de Precios entre Tiendas</div>', unsafe_allow_html=True)

cats_comp = ["CPU","GPU","RAM","SSD","MOTHERBOARD","PSU","COOLER","CASE"]
cats_comp_disponibles = [c for c in cats_comp if c in df["category"].unique()]

if cats_comp_disponibles:
    df_comp = df[df["category"].isin(cats_comp_disponibles)]
    precio_fuente_cat = df_comp.groupby(["source","category"])["price_pen"].median().reset_index()
    precio_fuente_cat.columns = ["Fuente","Categoría","Precio Mediano (S/)"]

    fig_comp = px.bar(
        precio_fuente_cat, x="Categoría", y="Precio Mediano (S/)",
        color="Fuente", barmode="group",
        title="Precio Mediano por Categoría y Fuente (S/)",
        color_discrete_sequence=px.colors.qualitative.Plotly,
    )
    fig_comp.update_layout(height=400, xaxis_tickangle=-20)
    st.plotly_chart(fig_comp, use_container_width=True)

# ── Fila 4: Evolución temporal ─────────────────────────────────────────
st.markdown('<div class="section-title">📈 Evolución Temporal de Registros</div>', unsafe_allow_html=True)

df_time = df.dropna(subset=["fecha"])
if len(df_time) > 0:
    time_counts = df_time.groupby(["fecha","source"]).size().reset_index(name="Registros")
    fig_time = px.area(
        time_counts, x="fecha", y="Registros", color="source",
        title="Registros Scrapeados por Día y Fuente",
        labels={"fecha": "Fecha", "source": "Fuente"},
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig_time.update_layout(height=350)
    st.plotly_chart(fig_time, use_container_width=True)

# ── Fila 5: Top productos con mayor descuento ──────────────────────────
st.markdown('<div class="section-title">🏷️ Top Productos con Mayor Descuento</div>', unsafe_allow_html=True)

df_desc = df[df["discount_pct"] > 5].dropna(subset=["discount_pct","title"])
if len(df_desc) > 0:
    top_desc = df_desc.nlargest(10, "discount_pct")[
        ["title","source","category","price_pen","discount_pct"]
    ].copy()
    top_desc.columns = ["Producto","Fuente","Categoría","Precio S/","Descuento %"]
    top_desc["Precio S/"] = top_desc["Precio S/"].apply(lambda x: f"S/ {x:,.2f}")
    top_desc["Descuento %"] = top_desc["Descuento %"].apply(lambda x: f"{x:.1f}%")
    top_desc["Producto"] = top_desc["Producto"].str[:60]
    st.dataframe(top_desc, use_container_width=True, hide_index=True)

# ── Fila 6: Tabla resumen por categoría ───────────────────────────────
st.markdown('<div class="section-title">📋 Resumen Estadístico por Categoría</div>', unsafe_allow_html=True)

resumen = df.groupby("category").agg(
    Registros=("price_pen","count"),
    Precio_Min=("price_pen","min"),
    Precio_Mediano=("price_pen","median"),
    Precio_Max=("price_pen","max"),
    Descuento_Prom=("discount_pct","mean"),
    Rating_Prom=("rating","mean"),
).reset_index()
resumen.columns = ["Categoría","Registros","Precio Mín (S/)","Precio Mediano (S/)","Precio Máx (S/)","Descuento Prom %","Rating Prom"]
resumen = resumen.sort_values("Registros", ascending=False)
for col in ["Precio Mín (S/)","Precio Mediano (S/)","Precio Máx (S/)"]:
    resumen[col] = resumen[col].apply(lambda x: f"S/ {x:,.2f}")
resumen["Descuento Prom %"] = resumen["Descuento Prom %"].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
resumen["Rating Prom"] = resumen["Rating Prom"].apply(lambda x: f"{x:.2f} ⭐" if pd.notna(x) else "—")
st.dataframe(resumen, use_container_width=True, hide_index=True)

# ── Footer ─────────────────────────────────────────────────────────────
st.divider()
st.caption("🖥️ HDS-ROI Pipeline v5.10 | Tesis: Optimización de Dropshipping con IA | Hardware Perú 2026")
