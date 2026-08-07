# =============================================================================
# HDS-ROI v6.0 — Predicción Multihorizonte (OE2) — v12
#
# FIX-I  (v11): price_pen solo de fuentes locales (Falabella/Hiraoka/Ripley)
# FIX-H  (v11): MARKUP_HW por tier como fallback
# FIX-P10 (v12): Lee markup_real.json generado por normalizar_master.py v2.0
#                → MARKUP_HW se actualiza con datos reales del mercado peruano
#                → si el JSON no existe, usa MARKUP_HW hardcodeado como fallback
# =============================================================================

import json
import warnings
import numpy as np
import pandas as pd
import joblib
from datetime import datetime, timedelta
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════
# HDS-ROI v6.1 — Señal por Modelo Específico (precios_por_modelo.json)
# Generado por: paso5_integracion_pe2.py
# ══════════════════════════════════════════════════════════════════════════
import json as _json, re as _re, os as _os

_MODELO_JSON = _os.path.join(_os.path.dirname(__file__),
                              'data', 'raw', 'precios_por_modelo.json')

_PATRON_MOBILE = _re.compile(
    r'(i[3579][\s\-]\d{4,5}[hHuUgGpPeE]\w*'
    r'|core\s*ultra\s*[579]\s*\d{3}[hHuUgGpP]\w*'
    r'|ryzen\s*[3579]\s*\d{4}[uUhHeE]\w*)',
    _re.IGNORECASE
)

def _normalizar_modelo(titulo):
    t = str(titulo).lower()
    if _PATRON_MOBILE.search(t): return None
    patrones = [
        r'(rtx\s*\d{4}\s*(?:ti|super|xt)?)',
        r'(rx\s*\d{4}\s*(?:xt|gre|xtx)?)',
        r'(gtx?\s*\d{4}\s*(?:ti|super)?)',
        r'(i[3579][\s\-]\d{4,5}[a-z]{0,3})',
        r'(ryzen\s*[3579]\s*\d{4}[a-z0-9]*)',
        r'(core\s*ultra\s*[579]\s*\d{3}[a-z]*)',
    ]
    for pat in patrones:
        m = _re.search(pat, t)
        if m:
            mod = m.group(1).strip()
            mod = _re.sub(r'\s*-\s*', '-', mod)
            mod = _re.sub(r'\s+', ' ', mod)
            mod = _re.sub(r'(i[3579])\s+(\d)', r'\1-\2', mod)
            return mod.strip()
    return None

def get_roi_por_modelo(titulo):
    """
    Dado el título de un producto, retorna dict con ROI y datos de precio
    si el modelo está en el índice. Retorna None si no se encuentra.
    """
    if not _os.path.exists(_MODELO_JSON):
        return None
    with open(_MODELO_JSON, 'r', encoding='utf-8') as _f:
        _idx = _json.load(_f)
    modelo = _normalizar_modelo(titulo)
    if modelo and modelo in _idx:
        d = _idx[modelo]
        return {
            'modelo':     modelo,
            'roi_pct':    d['roi_pct'],
            'markup':     d['markup_neto'],
            'confianza':  d['confianza'],
            'venta_usd':  d['precio_venta_pe_usd'],
            'costo_usd':  d['costo_importado_usd'],
            'ganancia_usd': round(d['precio_venta_pe_usd']*0.95 - d['costo_importado_usd'], 2),
        }
    return None

# Pre-cargar índice al iniciar (evitar I/O repetido)
_IDX_MODELOS = {}
if _os.path.exists(_MODELO_JSON):
    with open(_MODELO_JSON, 'r', encoding='utf-8') as _f:
        _IDX_MODELOS = _json.load(_f)
    print(f'[HDS-ROI v6.1] Indice de modelos cargado: {len(_IDX_MODELOS)} modelos')
else:
    print('[HDS-ROI v6.1] ADVERTENCIA: precios_por_modelo.json no encontrado')
# ══════════════════════════════════════════════════════════════════════════


warnings.filterwarnings("ignore")

BASE_DIR    = Path(__file__).resolve().parent.parent
MASTER_PATH = BASE_DIR / "data" / "raw" / "MASTER_normalizado.csv"
MODEL_PATH  = BASE_DIR / "models" / "lgbm_e1b_tuned.pkl"
OUTPUT_PATH = BASE_DIR / "results" / "predicciones_multihorizonte.json"
MARKUP_JSON = BASE_DIR / "data" / "raw" / "markup_real.json"

HORIZONTES = [1, 7, 14, 30]
TOP_N_SKUS = 30
FECHA_BASE = datetime(2026, 8, 5)

FEATURE_COLS = [
    "lag_1","lag_2","lag_3",
    "ma_2","ma_3","ma_5","ma_7","ma_14",
    "std_3","std_7",
    "pct_change_1","pct_change_2",
    "sku_mean","sku_std","sku_min","sku_max",
    "sku_range","sku_cv","sku_trend","sku_n_obs",
    "precio_actual",
]

COMPRA_KEYWORDS = [
    "ebay_usa","amazon_usa","aliexpress_usa","newegg_usa",
    "aliexpress","newegg","pcpartpicker","camel",
    "amazon.com","ebay.com","ebay","amazon",
]
VENTA_KEYWORDS = [
    "falabella_pe","hiraoka_pe","ripley_pe","coolbox_pe","mercadolibre_pe",
    "falabella","hiraoka","ripley","coolbox","mercadolibre","linio",
]

def clasificar_fuente(source: str) -> str:
    s = source.lower().strip()
    if s in {"exchangerate_api","unknown",""}:
        return "desconocida"
    for kw in COMPRA_KEYWORDS:
        if kw in s: return "compra"
    for kw in VENTA_KEYWORDS:
        if kw in s: return "venta"
    return "desconocida"

# ─────────────────────────────────────────────────────────────────────
# CUOTAS, BONUS, MARKUP
# ─────────────────────────────────────────────────────────────────────

CUOTA_HW = {
    "psu":5,"motherboard":5,"cooler":4,"case":4,
    "ram":3,"monitor":2,"laptop":2,"cpu":2,
    "ssd":2,"hdd":1,"gpu":1,"otro":1,
}
MINIMO_HW = {
    "psu":1,"motherboard":1,"cooler":1,"case":1,
    "ram":1,"cpu":1,"ssd":1,"laptop":1,"monitor":1,
}
BONUS_HW = {
    "psu":1.00,"motherboard":0.95,"cooler":0.90,"case":0.60,
    "ram":0.40,"laptop":0.35,"monitor":0.30,"hdd":0.20,
    "cpu":0.10,"ssd":0.05,"gpu":0.00,"otro":0.00,
}
UNIDADES_MAX_HW = {
    "gpu":3,"cpu":5,"ram":8,"ssd":6,"hdd":4,
    "motherboard":3,"psu":4,"case":3,"cooler":4,
    "monitor":2,"laptop":2,"otro":3,
}

# FIX-H: markup fallback hardcodeado — se sobreescribe con markup_real.json
# si normalizar_master.py v2.0 ya fue ejecutado (FIX-P10)
MARKUP_HW = {
    "psu":         1.85,
    "motherboard": 1.75,
    "cooler":      2.00,
    "case":        1.80,
    "ram":         1.60,
    "cpu":         1.55,
    "ssd":         1.45,
    "gpu":         1.20,
    "monitor":     1.55,
    "laptop":      1.40,
    "hdd":         1.60,
    "otro":        1.50,
}

SHIPPING_POR_FUENTE = {
    "amazon":12.0,"ebay":20.0,"aliexpress":12.0,"newegg":15.0,
}

# ─────────────────────────────────────────────────────────────────────
# CATEGORY MAP
# ─────────────────────────────────────────────────────────────────────

CATEGORY_MAP = {
    "RAM":"ram","GPU":"gpu","CPU":"cpu","SSD":"ssd","HDD":"hdd",
    "Motherboard":"motherboard","MOTHERBOARD":"motherboard",
    "PSU":"psu","Case":"case","CASE":"case",
    "Cooler":"cooler","COOLER":"cooler",
    "Monitor":"monitor","Laptop":"laptop","PERIPHERAL":"otro",
    "ram":"ram","gpu":"gpu","cpu":"cpu","ssd":"ssd","hdd":"hdd",
    "motherboard":"motherboard","mainboard":"motherboard","placa madre":"motherboard",
    "psu":"psu","power supply":"psu","fuente de poder":"psu","power supplies":"psu",
    "case":"case","pc case":"case","computer case":"case",
    "tower":"case","chassis":"case","cases & towers":"case",
    "cooler":"cooler","cpu cooler":"cooler","cooling":"cooler",
    "cpu cooling":"cooler","liquid cooler":"cooler",
    "fans & cooling":"cooler","computer cooling":"cooler",
    "monitor":"monitor","display":"monitor","pantalla":"monitor",
    "monitors":"monitor","computer monitors":"monitor",
    "laptop":"laptop","notebook":"laptop",
    "laptops & netbooks":"laptop","gaming laptop":"laptop",
    "graphics card":"gpu","video card":"gpu",
    "graphics cards & video adapters":"gpu",
    "processor":"cpu","procesador":"cpu","cpus/processors":"cpu",
    "memory":"ram","memoria ram":"ram","computer memory":"ram","memory modules":"ram",
    "solid state drive":"ssd","solid state drives":"ssd","nvme":"ssd",
    "hard drive":"hdd","hard disk":"hdd","hard drives":"hdd",
    "internal hard drives":"hdd",
}

def _hw_desde_category(category_raw: str) -> str:
    if not isinstance(category_raw, str) or not category_raw.strip():
        return ""
    c_orig = category_raw.strip()
    if c_orig in CATEGORY_MAP:
        return CATEGORY_MAP[c_orig]
    c = c_orig.lower()
    if c in CATEGORY_MAP:
        return CATEGORY_MAP[c]
    for key, hw in CATEGORY_MAP.items():
        if key.lower() in c:
            return hw
    return ""

KEYWORDS_HW = [
    ("gpu",  ["rtx 3","rtx 4","rtx 5","gtx 16","gtx 10","rx 6","rx 7","rx 9",
              "radeon rx","geforce rtx","geforce gtx","graphics card","video card",
              "dual-rtx","tuf-rtx","rog-rtx","gpu"," vga "]),
    ("cpu",  ["ryzen 3","ryzen 5","ryzen 7","ryzen 9","core i3","core i5",
              "core i7","core i9","intel core","amd ryzen","threadripper",
              "xeon","athlon","lga1700","lga1200","lga1151"]),
    ("ram",  ["ddr4-","ddr5-","ddr4 ","ddr5 ","32gb ddr","16gb ddr","64gb ddr",
              "vengeance ddr","trident z","ripjaws","fury beast",
              "sodimm","udimm","dimm","pc4-","pc5-","lpddr4","lpddr5",
              "cl14","cl16","cl18","cl30","cl32",
              "4800mhz","5200mhz","5600mhz","6000mhz","3200mhz","3600mhz"]),
    ("ssd",  ["nvme ssd","m.2 ssd","pcie ssd","sata ssd","970 evo","980 pro",
              "sn850","sn770","p5 plus","solid state drive","wds100t","wds200t"]),
    ("hdd",  ["hard drive","hard disk","hdd","seagate barracuda",
              "wd blue","wd red","wd black hdd","ironwolf","exos",
              "st1000","st2000","st4000"]),
    ("motherboard", ["motherboard","mainboard","placa madre",
                     "b650","x670","z790","b760","x570","b550","z690",
                     "rog strix b","tuf gaming b","pro b","aorus b","msi b"]),
    ("psu",  ["power supply","fuente de poder","fuente atx",
              "650w power","750w power","850w power","1000w power",
              "650w psu","750w psu","850w psu","1000w psu",
              "650w modular","750w modular","850w modular",
              "fully modular psu","semi modular psu","sfx power",
              "corsair rm","seasonic focus","evga supernova","rmx","hx1000"]),
    ("case", ["lian li lancool","lian li o11","lian li vector",
              "nzxt h510","nzxt h710","nzxt h9","fractal design",
              "phanteks eclipse","corsair 4000","corsair 5000",
              "meshify","define r","mid-tower case","full tower case",
              "mini-itx case","pc case","pc chassis","tower case","computer case"]),
    ("cooler", ["thermalright","aqua elite","peerless assassin",
                "deepcool ls","deepcool ag","deepcool ak",
                "arctic liquid freezer","arctic freezer",
                "noctua nh","noctua nf","be quiet dark rock",
                "cooler master hyper","cooler master masterliquid",
                "corsair h100","corsair h115","corsair h150","corsair icue h",
                "kraken x","kraken z","kraken elite","rog ryujin",
                "liquid freezer","liquid cooler","aio cooler",
                "water cooler","watercooler","cpu cooler","cpu fan",
                "240mm aio","280mm aio","360mm aio","h100i","h150i","nh-d15"]),
    ("monitor", ["lg 27","samsung 27","asus rog monitor","benq monitor",
                 "aoc monitor","viewsonic","dell ultrasharp",
                 "4k monitor","1440p monitor","1080p monitor",
                 "144hz monitor","165hz monitor","240hz monitor",
                 "ips panel","oled monitor","gaming monitor","monitor","pantalla"]),
    ("laptop", ["gaming laptop","ultrabook","gaming notebook",
                "asus rog laptop","msi laptop","lenovo legion",
                "razer blade","alienware","omen laptop","laptop","notebook"]),
]

def detectar_tipo_hw(title: str, category_raw: str) -> str:
    hw_cat = _hw_desde_category(category_raw)
    if hw_cat:
        return hw_cat
    t = str(title).lower().strip()
    for hw_type, keywords in KEYWORDS_HW:
        if any(kw in t for kw in keywords):
            return hw_type
    return "otro"

# ─────────────────────────────────────────────────────────────────────
# 1. CARGA
# ─────────────────────────────────────────────────────────────────────

def _titulo_valido(title: str) -> bool:
    if not isinstance(title, str): return False
    t = title.strip()
    return len(t) >= 20 and len(t.split()) >= 3

def cargar_master():
    print(f"[1/5] Cargando MASTER ({MASTER_PATH.name}) ...")
    df = pd.read_csv(MASTER_PATH, low_memory=False)
    print(f"      Shape original: {df.shape}")

    if "sku" in df.columns:
        n = df["sku"].isna().sum()
        if n > 0:
            print(f"      SKUs nulos eliminados: {n:,}")
            df = df.dropna(subset=["sku"]).copy()

    df["_fecha"]      = pd.to_datetime(df["timestamp"], errors="coerce")
    df["_precio"]     = pd.to_numeric(df["price_usd"],  errors="coerce")
    df["_precio_pen"] = (pd.to_numeric(df["price_pen"], errors="coerce")
                         if "price_pen" in df.columns
                         else pd.Series(np.nan, index=df.index))

    df = df.dropna(subset=["_fecha","_precio"])
    df = df[df["_precio"] > 0].copy()

    df["_title"]  = df["title"].fillna("Sin nombre").astype(str)
    df["_source"] = df["source"].fillna("unknown").astype(str)
    df["_brand"]  = df["brand"].fillna("").astype(str) if "brand" in df.columns \
                    else pd.Series("", index=df.index)

    if "category_label" in df.columns:
        df["_category"] = df["category_label"].fillna(
            df["category"].fillna("hardware")).astype(str)
        print("      Usando 'category_label' como fuente primaria ✅")
    else:
        df["_category"] = df["category"].fillna("hardware").astype(str)

    n_antes = len(df)
    df = df[df["_title"].apply(_titulo_valido)].copy()
    print(f"      Títulos sucios eliminados: {n_antes - len(df):,}")

    df["_rating"]   = pd.to_numeric(df.get("rating",       0), errors="coerce").fillna(0)
    df["_reviews"]  = pd.to_numeric(df.get("reviews",      0), errors="coerce").fillna(0)
    df["_shipping"] = pd.to_numeric(df.get("shipping_usd", 0), errors="coerce").fillna(0)

    df["_rol_fuente"] = df["_source"].apply(clasificar_fuente)
    df["_hw_type"]    = df.apply(
        lambda r: detectar_tipo_hw(r["_title"], r["_category"]), axis=1)

    print(f"      Shape limpio: {df.shape}")
    print(f"      Distribución HW    : {df['_hw_type'].value_counts().to_dict()}")
    print(f"      Distribución fuente: {df['_rol_fuente'].value_counts().to_dict()}")
    return df

# ─────────────────────────────────────────────────────────────────────
# 2. FEATURES
# ─────────────────────────────────────────────────────────────────────

def build_features(vals_array: np.ndarray) -> dict:
    vals = vals_array.astype(float)
    n    = len(vals)
    lag1 = vals[-1]            if n >= 1  else np.nan
    lag2 = vals[-2]            if n >= 2  else lag1
    lag3 = vals[-3]            if n >= 3  else lag2
    ma2  = np.mean(vals[-2:])  if n >= 2  else lag1
    ma3  = np.mean(vals[-3:])  if n >= 3  else lag1
    ma5  = np.mean(vals[-5:])  if n >= 5  else lag1
    ma7  = np.mean(vals[-7:])  if n >= 7  else lag1
    ma14 = np.mean(vals[-14:]) if n >= 14 else lag1
    std3 = np.std(vals[-3:])   if n >= 3  else 0.0
    std7 = np.std(vals[-7:])   if n >= 7  else 0.0
    pct1 = np.clip((lag1/lag2-1) if lag2>0 else 0.0, -1, 1)
    pct2 = np.clip((lag2/lag3-1) if lag3>0 else 0.0, -1, 1)
    return {
        "lag_1":lag1,"lag_2":lag2,"lag_3":lag3,
        "ma_2":ma2,"ma_3":ma3,"ma_5":ma5,"ma_7":ma7,"ma_14":ma14,
        "std_3":std3,"std_7":std7,
        "pct_change_1":pct1,"pct_change_2":pct2,
        "sku_mean":  float(np.mean(vals)),
        "sku_std":   float(np.std(vals)),
        "sku_min":   float(np.min(vals)),
        "sku_max":   float(np.max(vals)),
        "sku_range": float(np.max(vals)-np.min(vals)),
        "sku_cv":    float(np.std(vals)/np.mean(vals)) if np.mean(vals)>0 else 0.0,
        "sku_trend": float((vals[-1]-vals[0])/vals[0]) if vals[0]>0 and n>1 else 0.0,
        "sku_n_obs": int(n),
        "precio_actual": float(lag1),
    }

# ─────────────────────────────────────────────────────────────────────
# 3. SELECCIÓN DIVERSIFICADA
# ─────────────────────────────────────────────────────────────────────

def _moda(s):
    m = s.mode()
    return m.iloc[0] if len(m) > 0 else "otro"

def _titulo_mas_largo(s):
    validos = s.dropna().astype(str)
    validos = validos[validos.apply(_titulo_valido)]
    if len(validos) == 0:
        return s.dropna().iloc[0] if len(s.dropna()) > 0 else "Sin nombre"
    return validos.loc[validos.str.len().idxmax()]

def _brand_ok(brand: str, conteo_brand: dict) -> bool:
    if not brand: return True
    return conteo_brand.get(brand, 0) < 3

def seleccionar_skus_diversificados(df: pd.DataFrame) -> list:
    print(f"\n[3/5] Seleccionando Top {TOP_N_SKUS} SKUs con diversidad HW ...")

    df_compra = df[df["_rol_fuente"].isin(["compra","desconocida"])].copy()
    if len(df_compra) < 10:
        print("      ⚠️  Pocas fuentes internacionales, usando todas")
        df_compra = df.copy()

    stats = df_compra.groupby("sku").agg(
        n_obs        = ("_precio",     "count"),
        precio_medio = ("_precio",     "median"),
        precio_std   = ("_precio",     "std"),
        title        = ("_title",      _titulo_mas_largo),
        source       = ("_source",     "first"),
        category     = ("_category",   _moda),
        hw_type      = ("_hw_type",    _moda),
        brand        = ("_brand",      "first"),
        rating       = ("_rating",     "median"),
        reviews      = ("_reviews",    "median"),
        shipping     = ("_shipping",   "median"),
        rol_fuente   = ("_rol_fuente", "first"),
    ).reset_index()

    stats = stats[stats["n_obs"] >= 3].copy()
    stats = stats[stats["title"].apply(_titulo_valido)].copy()
    stats["precio_std"] = stats["precio_std"].fillna(0)
    stats["brand"] = stats["brand"].fillna("").astype(str).str.strip().str.lower().str[:20]

    def _norm(s):
        mn, mx = s.min(), s.max()
        return (s-mn)/(mx-mn+1e-9)

    stats["cv"]            = stats["precio_std"]/stats["precio_medio"].clip(lower=0.01)
    stats["score_obs"]     = _norm(stats["n_obs"])
    stats["score_cv"]      = _norm(stats["cv"])
    stats["score_rating"]  = _norm(stats["rating"].fillna(0))
    stats["score_reviews"] = _norm(stats["reviews"].fillna(0))
    stats["bonus_hw"]      = stats["hw_type"].map(BONUS_HW).fillna(0)
    stats["bonus_fuente"]  = (stats["rol_fuente"]=="compra").astype(float)
    stats["score_total"]   = (
        0.20*stats["score_obs"]     +
        0.15*stats["score_cv"]      +
        0.15*stats["score_reviews"] +
        0.10*stats["score_rating"]  +
        0.35*stats["bonus_hw"]      +
        0.05*stats["bonus_fuente"]
    )
    stats = stats.sort_values("score_total", ascending=False)

    print(f"      Distribución en stats: {stats['hw_type'].value_counts().to_dict()}")

    seleccionados = []
    conteo_hw     = {}
    conteo_brand  = {}

    print("      Fase 1: reserva mínima por categoría ...")
    for hw_obj, min_qty in MINIMO_HW.items():
        candidatos = stats[stats["hw_type"] == hw_obj]
        agregados  = 0
        for _, row in candidatos.iterrows():
            if agregados >= min_qty: break
            sku   = row["sku"]
            brand = str(row["brand"])
            if sku not in seleccionados and _brand_ok(brand, conteo_brand):
                seleccionados.append(sku)
                conteo_hw[hw_obj] = conteo_hw.get(hw_obj, 0) + 1
                if brand: conteo_brand[brand] = conteo_brand.get(brand, 0) + 1
                agregados += 1
        if agregados == 0:
            print(f"      ⚠️  '{hw_obj}': sin candidatos ({len(candidatos)} en stats)")
        else:
            print(f"      ✅  '{hw_obj}': {agregados} SKU(s) reservado(s)")

    ya_sel = set(seleccionados)
    for _, row in stats.iterrows():
        if len(seleccionados) >= TOP_N_SKUS: break
        sku   = row["sku"]
        hw    = str(row["hw_type"])
        brand = str(row["brand"])
        if sku in ya_sel: continue
        if conteo_hw.get(hw, 0) >= CUOTA_HW.get(hw, 3): continue
        if not _brand_ok(brand, conteo_brand): continue
        seleccionados.append(sku)
        ya_sel.add(sku)
        conteo_hw[hw] = conteo_hw.get(hw, 0) + 1
        if brand: conteo_brand[brand] = conteo_brand.get(brand, 0) + 1

    if len(seleccionados) < TOP_N_SKUS:
        ya_sel = set(seleccionados)
        for _, row in stats.iterrows():
            if len(seleccionados) >= TOP_N_SKUS: break
            if row["sku"] not in ya_sel:
                seleccionados.append(row["sku"])

    df_sel = df_compra[df_compra["sku"].isin(seleccionados)]
    print(f"      SKUs seleccionados: {len(seleccionados)}")
    print(f"      Distribución final: {df_sel['_hw_type'].value_counts().to_dict()}")
    return seleccionados

# ─────────────────────────────────────────────────────────────────────
# 4. PREDICCIÓN ROLLING
# ─────────────────────────────────────────────────────────────────────

def predecir_rolling(modelo, hist_vals: np.ndarray, horizonte: int) -> list:
    hist   = list(hist_vals.astype(float))
    cols_m = getattr(modelo, "feature_name_", FEATURE_COLS)
    preds  = []
    for _ in range(horizonte):
        feats = build_features(np.array(hist))
        X     = pd.DataFrame([feats])
        for c in cols_m:
            if c not in X.columns: X[c] = 0.0
        pred = float(modelo.predict(X[cols_m])[0])
        preds.append(max(pred, 0.01))
        hist.append(pred)
    return preds

# ─────────────────────────────────────────────────────────────────────
# 5. OPORTUNIDAD
# Jerarquía precio_venta:
#   1. precio_venta_local_usd  → SKU exacto en Falabella/Hiraoka
#   2. precio_pen_local / TC   → price_pen de fuente local (FIX-I)
#   3. precio_compra × MARKUP  → MARKUP_HW real (FIX-P10) o fallback (FIX-H)
# ─────────────────────────────────────────────────────────────────────

def calcular_oportunidad(row_info: dict, precio_actual_usd: float,
                          precio_pred_7d: float) -> dict:
    TC      = 3.75
    hw_type = row_info.get("hw_type", "otro")
    source  = row_info.get("source",  "")
    rol     = clasificar_fuente(source)
    markup  = MARKUP_HW.get(hw_type, 1.50)

    if rol == "venta":
        precio_venta_usd  = precio_actual_usd
        precio_compra_usd = precio_actual_usd * 0.60
        shipping_usd      = 0.0
        fuente_compra_est = "estimado_60pct_local"
        metodo_venta      = "precio_local_directo"
    else:
        precio_compra_usd = precio_actual_usd

        shipping_usd = float(row_info.get("shipping_usd_median", 0) or 0)
        if shipping_usd == 0:
            for f, s in SHIPPING_POR_FUENTE.items():
                if f in source.lower():
                    shipping_usd = s
                    break
            else:
                shipping_usd = 15.0

        pv_local     = float(row_info.get("precio_venta_local_usd",  0) or 0)
        # FIX-I: precio_pen_local = solo de filas con _rol_fuente=="venta"
        pv_pen_local = float(row_info.get("precio_pen_local",        0) or 0)

        if pv_local > 0:
            precio_venta_usd = pv_local
            metodo_venta     = "sku_local_exacto"
        elif pv_pen_local > 0:
            precio_venta_usd = pv_pen_local / TC
            metodo_venta     = "precio_pen_local"
        else:
            # FIX-H + FIX-P10: markup desde datos reales si disponible
            precio_venta_usd = precio_compra_usd * markup
            metodo_venta     = f"markup_x{markup:.2f}"

        fuente_compra_est = source

    costo_total_usd  = precio_compra_usd + shipping_usd
    precio_venta_pen = precio_venta_usd * TC

    if precio_venta_usd > costo_total_usd:
        ganancia_usd = precio_venta_usd - costo_total_usd
        roi_pct      = (ganancia_usd / costo_total_usd) * 100
    else:
        ganancia_usd = 0.0
        roi_pct      = 0.0

    var_7d = ((precio_pred_7d - precio_compra_usd) / precio_compra_usd * 100
              if precio_compra_usd > 0 else 0.0)

    s_roi       = min(40, max(0, roi_pct * 0.4))
    s_obs       = min(15, row_info.get("n_obs",  0) * 0.1)
    s_rating    = min(15, row_info.get("rating", 0) * 3.0)
    s_tendencia = 10.0 if var_7d > 0 else 0.0
    s_shipping  = 10.0 if shipping_usd == 0 else 0.0
    s_margen    = min(10, (ganancia_usd / max(precio_venta_usd, 1)) * 20)
    score       = min(100, max(0,
                     s_roi + s_obs + s_rating + s_tendencia + s_shipping + s_margen))

    if   roi_pct > 30 and score >= 50: accion, icon = "COMPRAR YA", "🔥"
    elif roi_pct > 15 and score >= 30: accion, icon = "COMPRAR",    "✅"
    elif roi_pct > 0:                  accion, icon = "EVALUAR",    "⏳"
    else:                              accion, icon = "EVITAR",     "❌"

    unidades = max(1, min(UNIDADES_MAX_HW.get(hw_type, 3),
                          int(5000 / max(costo_total_usd, 1))))

    return {
        "hw_type":             hw_type,
        "source_rol":          rol,
        "fuente_compra":       fuente_compra_est,
        "metodo_precio_venta": metodo_venta,
        "precio_compra_usd":   round(precio_compra_usd,  2),
        "precio_venta_usd":    round(precio_venta_usd,   2),
        "precio_venta_pen":    round(precio_venta_pen,   2),
        "shipping_usd":        round(shipping_usd,       2),
        "costo_total_usd":     round(costo_total_usd,    2),
        "ganancia_usd":        round(ganancia_usd,       2),
        "roi_pct":             round(roi_pct,            2),
        "var_7d_pct":          round(var_7d,             2),
        "score_oportunidad":   round(score,              1),
        "accion":              accion,
        "accion_icon":         icon,
        "unidades_sugeridas":  unidades,
        "nota_roi": (
            f"ROI bruto ({metodo_venta}). "
            "Descontar: aranceles ~12%, IGV 18%, flete $15-25. "
            "ROI neto estimado: 25-45%."
        ),
    }

# ─────────────────────────────────────────────────────────────────────
# 6. MAIN
# ─────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*65)
    print("  HDS-ROI v6.0 — Predicción Multihorizonte + Oportunidades")
    print("="*65)

    # ── FIX-P10: Cargar markup_real.json si existe ────────────────
    print(f"\n[0/5] FIX-P10: Cargando markup real desde {MARKUP_JSON.name} ...")
    if MARKUP_JSON.exists():
        try:
            with open(MARKUP_JSON, "r", encoding="utf-8") as f:
                markup_data = json.load(f)
            actualizados = []
            for cat, val in markup_data.items():
                if cat in MARKUP_HW and isinstance(val, (int, float)) \
                        and 1.1 <= val <= 4.0:
                    MARKUP_HW[cat] = round(float(val), 3)
                    actualizados.append(f"{cat}={val:.3f}x")
            if actualizados:
                print(f"      ✅ MARKUP_HW actualizado con datos reales:")
                for item in actualizados:
                    print(f"         {item}")
            else:
                print("      ⚠️  markup_real.json sin claves válidas → MARKUP_HW por defecto")
        except Exception as e:
            print(f"      ⚠️  Error leyendo markup_real.json: {e} → MARKUP_HW por defecto")
    else:
        print(f"      ℹ️  {MARKUP_JSON.name} no encontrado")
        print("      ℹ️  Ejecutar normalizar_master.py v2.0 para generarlo")
        print("      ℹ️  Usando MARKUP_HW hardcodeado como fallback")

    # ── [1/5] Cargar MASTER ───────────────────────────────────────
    df = cargar_master()

    # ── [2/5] Cargar modelo ───────────────────────────────────────
    print(f"\n[2/5] Cargando modelo {MODEL_PATH.name} ...")
    modelo = joblib.load(MODEL_PATH)
    if hasattr(modelo, "feature_name_"):
        print(f"      Features: {len(modelo.feature_name_)}")

    # ── [3/5] Selección diversificada ────────────────────────────
    top_skus = seleccionar_skus_diversificados(df)

    # Fuentes internacionales (compra)
    df_top = df[
        df["sku"].isin(top_skus) &
        df["_rol_fuente"].isin(["compra","desconocida"])
    ].copy()

    # Fuentes locales (venta) — precio_pen SOLO de aquí (FIX-I)
    df_local             = df[df["_rol_fuente"] == "venta"].copy()
    precio_venta_por_sku = {}
    precio_pen_por_sku   = {}

    if len(df_local) > 0:
        precio_venta_por_sku = df_local.groupby("sku")["_precio"].median().to_dict()
        df_local_pen = df_local[
            df_local["_precio_pen"].notna() & (df_local["_precio_pen"] > 0)
        ]
        if len(df_local_pen) > 0:
            precio_pen_por_sku = df_local_pen.groupby("sku")["_precio_pen"].median().to_dict()
        print(f"      Precios locales disponibles: {len(precio_venta_por_sku)} SKUs")
        print(f"      Precios PEN locales:          {len(precio_pen_por_sku)} SKUs")
    else:
        print("      ⚠️  Sin precios locales — usando MARKUP_HW")

    # ── [4/5] Predicciones rolling ────────────────────────────────
    print(f"\n[4/5] Generando predicciones rolling {HORIZONTES} días ...")
    resultados = {}
    errores    = 0

    for sku_id in top_skus:
        df_sku = df_top[df_top["sku"] == sku_id].copy()
        if len(df_sku) < 3:
            df_sku = df[df["sku"] == sku_id].copy()

        serie = (df_sku
                 .groupby(df_sku["_fecha"].dt.date)["_precio"]
                 .median().sort_index())
        if len(serie) < 3:
            errores += 1
            continue

        title    = df_sku["_title"].mode().iloc[0]
        source   = df_sku["_source"].mode().iloc[0]
        category = df_sku["_category"].mode().iloc[0]
        hw_type  = df_sku["_hw_type"].mode().iloc[0]
        brand    = df_sku["_brand"].mode().iloc[0]
        rating   = float(df_sku["_rating"].median())
        reviews  = int(df_sku["_reviews"].median())
        shipping = float(df_sku["_shipping"].median())

        # FIX-I: precio_pen SOLO de fuentes locales
        precio_pen_local       = float(precio_pen_por_sku.get(sku_id,  0.0))
        precio_venta_local_usd = float(precio_venta_por_sku.get(sku_id, 0.0))

        precio_actual = float(serie.iloc[-1])
        hist_fechas   = [str(d) for d in serie.index[-30:]]
        hist_precios  = [round(float(p), 2) for p in serie.values[-30:]]

        pred_por_horizonte = {}
        pred_7d_precio     = precio_actual

        for h in HORIZONTES:
            preds = predecir_rolling(modelo, serie.values, h)
            if h == 7:
                pred_7d_precio = preds[-1]

            fechas_fut = [(FECHA_BASE + timedelta(days=i+1)).strftime("%Y-%m-%d")
                          for i in range(h)]
            var_pct = ((preds[-1]-precio_actual)/precio_actual*100
                       if precio_actual > 0 else 0.0)
            margen  = precio_actual * 0.015 * np.sqrt(h)
            ci_lo   = [round(max(p-margen*(i+1)/h, 0.01), 2) for i, p in enumerate(preds)]
            ci_hi   = [round(p+margen*(i+1)/h, 2)            for i, p in enumerate(preds)]

            pred_por_horizonte[str(h)] = {
                "fechas":        fechas_fut,
                "precios":       [round(p, 2) for p in preds],
                "ci_lower":      ci_lo,
                "ci_upper":      ci_hi,
                "precio_final":  round(preds[-1], 2),
                "variacion_pct": round(var_pct, 2),
                "tendencia":     ("SUBE" if var_pct>1 else "BAJA" if var_pct<-1 else "ESTABLE"),
            }

        oportunidad = calcular_oportunidad(
            row_info={
                "hw_type":                hw_type,
                "source":                 source,
                "precio_pen_local":       precio_pen_local,
                "precio_venta_local_usd": precio_venta_local_usd,
                "shipping_usd_median":    shipping,
                "n_obs":                  len(serie),
                "rating":                 rating,
            },
            precio_actual_usd=precio_actual,
            precio_pred_7d=pred_7d_precio,
        )

        resultados[str(sku_id)] = {
            "sku":               str(sku_id),
            "title":             title[:80],
            "source":            source,
            "source_rol":        clasificar_fuente(source),
            "category":          category,
            "hw_type":           hw_type,
            "brand":             brand,
            "rating":            round(rating, 1),
            "reviews":           reviews,
            "n_observaciones":   int(len(serie)),
            "fecha_ultimo_dato": str(serie.index[-1]),
            "precio_actual_usd": round(precio_actual, 2),
            "historia_fechas":   hist_fechas,
            "historia_precios":  hist_precios,
            "predicciones":      pred_por_horizonte,
            "oportunidad":       oportunidad,
        }

    print(f"      Procesados: {len(resultados)} | Errores: {errores}")

    # ── [5/5] Guardar resultados ──────────────────────────────────
    print(f"\n[5/5] Guardando en {OUTPUT_PATH} ...")

    ranking = sorted(
        resultados.items(),
        key=lambda x: x[1]["oportunidad"]["score_oportunidad"],
        reverse=True,
    )

    def _make_top_item(v):
        return {
            "sku":           v["sku"],
            "title":         v["title"][:60],
            "hw_type":       v["hw_type"],
            "source_rol":    v["source_rol"],
            "brand":         v["brand"],
            "precio_compra": v["oportunidad"]["precio_compra_usd"],
            "precio_venta":  v["oportunidad"]["precio_venta_usd"],
            "metodo_venta":  v["oportunidad"]["metodo_precio_venta"],
            "ganancia":      v["oportunidad"]["ganancia_usd"],
            "roi_pct":       v["oportunidad"]["roi_pct"],
            "unidades":      v["oportunidad"]["unidades_sugeridas"],
            "accion":        v["oportunidad"]["accion"],
            "accion_icon":   v["oportunidad"]["accion_icon"],
            "score":         v["oportunidad"]["score_oportunidad"],
            "tendencia_7d":  v["predicciones"]["7"]["tendencia"],
            "var_7d":        v["predicciones"]["7"]["variacion_pct"],
        }

    top5 = [
        _make_top_item(v) for _, v in ranking[:10]
        if v["oportunidad"]["accion"] in ("COMPRAR YA", "COMPRAR")
    ]

    if not top5:
        print("  ⚠️  Sin COMPRAR/COMPRAR YA — incluyendo EVALUAR")
        top5 = [_make_top_item(v) for _, v in ranking[:5]]

    # Markup usado — auditable (FIX-P10)
    markup_usado = {k: round(v, 3) for k, v in MARKUP_HW.items()}

    resumen = {
        "fecha_generacion":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "fecha_corte":            FECHA_BASE.strftime("%Y-%m-%d"),
        "horizontes_dias":        HORIZONTES,
        "n_skus":                 len(resultados),
        "modelo_usado":           MODEL_PATH.name,
        "seleccion":              "diversificada_2fases_v12",
        "markup_usado":           markup_usado,
        "markup_fuente":          (
            "markup_real.json" if MARKUP_JSON.exists() else "hardcodeado_fallback"
        ),
        "top5_oportunidades":     top5[:5],
        "top_skus_por_horizonte": {},
    }

    for h in HORIZONTES:
        rh = sorted(
            resultados.items(),
            key=lambda x: x[1]["predicciones"][str(h)]["variacion_pct"],
            reverse=True,
        )[:5]
        resumen["top_skus_por_horizonte"][str(h)] = [
            {
                "sku":           v["sku"],
                "title":         v["title"][:50],
                "hw_type":       v["hw_type"],
                "source_rol":    v["source_rol"],
                "precio_actual": v["precio_actual_usd"],
                "precio_pred":   v["predicciones"][str(h)]["precio_final"],
                "variacion_pct": v["predicciones"][str(h)]["variacion_pct"],
                "tendencia":     v["predicciones"][str(h)]["tendencia"],
                "accion":        v["oportunidad"]["accion"],
                "roi_pct":       v["oportunidad"]["roi_pct"],
            }
            for _, v in rh
        ]

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {"resumen": resumen, "skus": resultados},
            f, ensure_ascii=False, indent=2,
        )
    print(f"      Tamaño: {OUTPUT_PATH.stat().st_size / 1024:.1f} KB")

    # ── Resumen final ─────────────────────────────────────────────
    print("\n" + "="*65)
    print("  ✅ TOP OPORTUNIDADES:")
    print("="*65)
    for i, item in enumerate(top5[:5], 1):
        print(f"  {i}. {item['accion_icon']} [{item['hw_type'].upper():<12}] "
              f"[{item['source_rol'].upper():<10}] {item['title'][:35]}")
        print(f"     Compra: ${item['precio_compra']:>8,.2f} → "
              f"Venta: ${item['precio_venta']:>8,.2f} ({item['metodo_venta']}) | "
              f"ROI: {item['roi_pct']:+6.1f}% | Ganancia: ${item['ganancia']:,.2f}")
        print()

    dist_final = {}
    for v in resultados.values():
        hw = v["hw_type"]
        dist_final[hw] = dist_final.get(hw, 0) + 1
    print(f"  📊 Distribución HW: {dist_final}")
    print(f"  📊 Markup fuente:   {resumen['markup_fuente']}")
    print("="*65 + "\n")


if __name__ == "__main__":
    main()