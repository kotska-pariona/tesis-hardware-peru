# =============================================================================
# feature_integrator.py  v2.2 — Fuzzy Join por Título Normalizado
# Corrección: preparar matriz OE9 para que NSGA-III use TODO en USD
#   - Conserva precio_import_usd (USD) y NO depende de PEN para el ROI
#   - (opcional) crea alias para consistencia si más adelante se usa precio_venta_est / ganancia_esperada
# =============================================================================

import argparse
import json
import re
import unicodedata
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pathlib import Path
from datetime import datetime
from sklearn.preprocessing import MinMaxScaler

try:
    from rapidfuzz import fuzz, process as rfprocess
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False
    print("⚠️  rapidfuzz no instalado → pip install rapidfuzz")
    from difflib import SequenceMatcher

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# 0. CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────

RESULTS_DIR  = Path("results")
DATA_DIR     = Path("data")
FEATURES_DIR = DATA_DIR / "features"

F_RJ      = RESULTS_DIR / "feature_rj_OE9.csv"
F_ROI_MOD = RESULTS_DIR / "oe4a_productos_roi_moderado.csv"
F_ROI_CON = RESULTS_DIR / "oe4a_productos_roi_conservador.csv"
F_ROI_AGR = RESULTS_DIR / "oe4a_productos_roi_agresivo.csv"
F_PE3C    = RESULTS_DIR / "pe3c_matches_costo_real.csv"
F_PARETO  = RESULTS_DIR / "oe5_pareto_front.csv"

OUT_MATRIX  = FEATURES_DIR / "oe9_feature_matrix.csv"
OUT_REPORT  = RESULTS_DIR  / "oe9_integration_report.json"
OUT_HEATMAP = RESULTS_DIR  / "oe9_feature_heatmap.png"
LOG_FILE    = DATA_DIR     / "feature_integrator_log.txt"

FUZZY_THRESHOLD = 80

W_ROI    = 0.40
W_GAP    = 0.25
W_PARETO = 0.20
W_RJ     = 0.15

# ─────────────────────────────────────────────────────────────────────────────
# 1. UTILIDADES
# ─────────────────────────────────────────────────────────────────────────────

def log(msg: str, verbose: bool = True):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    if verbose:
        print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def ensure_dirs():
    for d in [FEATURES_DIR, RESULTS_DIR]:
        d.mkdir(parents=True, exist_ok=True)

def safe_load(path: Path, label: str) -> pd.DataFrame | None:
    if not path.exists():
        log(f"⚠️  No encontrado: {path}  [{label}]")
        return None
    df = pd.read_csv(path, encoding="utf-8", low_memory=False)
    log(f"✅ Cargado: {path.name:<45} {len(df):>6,} filas × {df.shape[1]} cols")
    return df

def normalize_title(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def fuzzy_score(a: str, b: str) -> float:
    if HAS_RAPIDFUZZ:
        return fuzz.token_sort_ratio(a, b)
    else:
        return SequenceMatcher(None, a, b).ratio() * 100

def best_fuzzy_match(query: str, candidates: list, threshold: float) -> tuple:
    q_norm = normalize_title(query)
    if not q_norm:
        return -1, 0.0
    if HAS_RAPIDFUZZ:
        result = rfprocess.extractOne(
            q_norm, candidates,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=threshold
        )
        if result is None:
            return -1, 0.0
        _, score, idx = result
        return idx, float(score)
    else:
        best_idx, best_score = -1, 0.0
        for i, cand in enumerate(candidates):
            s = fuzzy_score(q_norm, cand)
            if s > best_score:
                best_score, best_idx = s, i
        return (best_idx, best_score) if best_score >= threshold else (-1, 0.0)

# ─────────────────────────────────────────────────────────────────────────────
# 2. CARGA
# ─────────────────────────────────────────────────────────────────────────────

def load_sources(verbose: bool) -> dict:
    log("=" * 60, verbose)
    log("  CARGA DE FUENTES", verbose)
    log("=" * 60, verbose)
    return {
        "rj": safe_load(F_RJ, "feature_rj_OE9"),
        "roi_mod": safe_load(F_ROI_MOD, "roi_moderado"),
        "roi_con": safe_load(F_ROI_CON, "roi_conservador"),
        "roi_agr": safe_load(F_ROI_AGR, "roi_agresivo"),
        "pe3c": safe_load(F_PE3C, "pe3c_costo_real"),
        "pareto": safe_load(F_PARETO, "oe5_pareto_front"),
    }

# ─────────────────────────────────────────────────────────────────────────────
# 3. FUZZY JOIN GENÉRICO
# ─────────────────────────────────────────────────────────────────────────────

def fuzzy_join(base_df: pd.DataFrame,
               base_col: str,
               right_df: pd.DataFrame,
               right_col: str,
               right_cols_keep: list,
               label: str,
               threshold: float,
               verbose: bool = True) -> pd.DataFrame:

    log(f"\n🔗 Fuzzy join: rj.{base_col} ↔ {label}.{right_col} (umbral={threshold})", verbose)

    right_titles_norm = [normalize_title(t) for t in right_df[right_col].tolist()]

    matched_rows = []
    scores = []

    for prod in base_df[base_col]:
        idx, score = best_fuzzy_match(prod, right_titles_norm, threshold)
        if idx >= 0:
            row_data = right_df.iloc[idx][right_cols_keep].to_dict()
        else:
            row_data = {c: np.nan for c in right_cols_keep}
        matched_rows.append(row_data)
        scores.append(score if idx >= 0 else np.nan)

    match_df = pd.DataFrame(matched_rows, index=base_df.index)
    match_df[f"fuzzy_score_{label}"] = scores

    result = pd.concat(
        [base_df.reset_index(drop=True), match_df.reset_index(drop=True)],
        axis=1
    )

    n_matched = pd.Series(scores).notna().sum()
    log(f"   → {n_matched}/{len(base_df)} matches (score ≥ {threshold})", verbose)
    return result

# ─────────────────────────────────────────────────────────────────────────────
# 4. PROCESAMIENTO PARETO
# ─────────────────────────────────────────────────────────────────────────────

def process_pareto_fuzzy(base_df: pd.DataFrame,
                         pareto_df: pd.DataFrame,
                         threshold: float,
                         verbose: bool = True) -> pd.DataFrame:

    log(f"\n🔗 Fuzzy join Pareto: expandir skus_top3 → match vs producto (umbral={threshold})", verbose)

    pareto_lookup = {}
    for _, row in pareto_df.iterrows():
        titulos_raw = str(row.get("skus_top3", ""))
        titulos = [t.strip() for t in titulos_raw.split("|") if t.strip()]
        for titulo in titulos:
            t_norm = normalize_title(titulo)
            if t_norm not in pareto_lookup:
                pareto_lookup[t_norm] = {
                    "in_pareto_front": True,
                    "pareto_roi_pct": row.get("roi_pct", np.nan),
                    "pareto_riesgo": row.get("riesgo", np.nan),
                    "pareto_tipo": row.get("tipo", ""),
                }

    pareto_titles_norm = list(pareto_lookup.keys())
    pareto_infos = list(pareto_lookup.values())
    log(f"   Títulos únicos en Pareto: {len(pareto_titles_norm)}", verbose)

    results = []
    for prod in base_df["producto"]:
        idx, score = best_fuzzy_match(prod, pareto_titles_norm, threshold)
        if idx >= 0:
            info = pareto_infos[idx].copy()
            info["fuzzy_score_pareto"] = score
        else:
            info = {
                "in_pareto_front": False,
                "pareto_roi_pct": np.nan,
                "pareto_riesgo": np.nan,
                "pareto_tipo": "",
                "fuzzy_score_pareto": np.nan,
            }
        results.append(info)

    pareto_match_df = pd.DataFrame(results, index=base_df.index)
    result = pd.concat([base_df.reset_index(drop=True), pareto_match_df.reset_index(drop=True)], axis=1)

    n_matched = int(pareto_match_df["in_pareto_front"].sum())
    log(f"   → {n_matched}/{len(base_df)} productos en frente de Pareto", verbose)
    return result

# ─────────────────────────────────────────────────────────────────────────────
# 5. INTEGRACIÓN PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def integrate(sources: dict, verbose: bool) -> pd.DataFrame:
    log("\n" + "=" * 60, verbose)
    log("  INTEGRACIÓN DE FEATURES (v2.2 — fuzzy join)", verbose)
    log("=" * 60, verbose)

    # Base: r_j
    rj = sources["rj"]
    cols_rj = ["sku", "producto", "marca", "categoria",
               "r_j", "label_pred", "p_vigente", "p_en_riesgo",
               "p_obsoleto", "rank_obsolescencia"]
    cols_rj = [c for c in cols_rj if c in rj.columns]
    base = rj[cols_rj].copy().rename(columns={"label_pred": "label_obsolescencia"})
    log(f"\n📌 Base (r_j): {len(base)} SKUs", verbose)

    # JOIN 1: ROI (estos valores deben ser coherentes con USD/ROI; NSGA-III ya no usa PEN)
    roi_frames = []
    for df_roi, esc in [(sources["roi_mod"], "mod"),
                        (sources["roi_con"], "con"),
                        (sources["roi_agr"], "agr")]:
        if df_roi is None:
            continue
        cols_keep = ["title_local", "sku_local",
                     "roi_unitario_pct", "ganancia_unitaria_bruta",
                     "score_roi_ponderado", "rank",
                     "precio_venta_est", "demanda_cat",
                     "score_confianza", "score_demanda"]
        cols_keep = [c for c in cols_keep if c in df_roi.columns]
        sub = df_roi[cols_keep].copy().rename(columns={
            "roi_unitario_pct": f"roi_pct_{esc}",
            "ganancia_unitaria_bruta": f"ganancia_{esc}",
            "score_roi_ponderado": f"score_roi_{esc}",
            "rank": f"rank_roi_{esc}",
        })
        roi_frames.append((sub, esc))

    if roi_frames:
        df_roi_base, _ = roi_frames[0]
        rank_col = "rank_roi_mod"
        if rank_col in df_roi_base.columns:
            df_roi_base = (df_roi_base
                           .sort_values(rank_col)
                           .drop_duplicates("title_local"))

        cols_roi_keep = [c for c in df_roi_base.columns if c != "title_local"]
        base = fuzzy_join(
            base, "producto", df_roi_base, "title_local",
            cols_roi_keep, label="roi",
            threshold=FUZZY_THRESHOLD, verbose=verbose
        )

        for df_roi_extra, esc in roi_frames[1:]:
            df_roi_extra = df_roi_extra.drop_duplicates("title_local")
            extra_cols = [c for c in df_roi_extra.columns if c.endswith(f"_{esc}") or c == "title_local"]
            if len(extra_cols) > 1:
                base = fuzzy_join(
                    base, "producto",
                    df_roi_extra[extra_cols], "title_local",
                    [c for c in extra_cols if c != "title_local"],
                    label=f"roi_{esc}",
                    threshold=FUZZY_THRESHOLD, verbose=verbose
                )

        if "roi_pct_mod" in base.columns: base["roi_unitario_pct"] = base["roi_pct_mod"]
        if "ganancia_mod" in base.columns: base["ganancia_unitaria"] = base["ganancia_mod"]
        if "score_roi_mod" in base.columns: base["score_roi_ponderado"] = base["score_roi_mod"]
        if "rank_roi_mod" in base.columns: base["rank_roi"] = base["rank_roi_mod"]

    # JOIN 2: PE3c (aseguramos traer USD)
    if sources["pe3c"] is not None:
        pe3c = sources["pe3c"]
        cols_pe3c_keep = ["sku_local", "price_local", "price_import",
                           "gap_pct", "gap_usd", "match_score",
                           "gap_pct_real_base", "conviene_local_base"]
        cols_pe3c_keep = [c for c in cols_pe3c_keep if c in pe3c.columns]

        pe3c_dedup = pe3c.copy()
        if "match_score" in pe3c_dedup.columns:
            pe3c_dedup = (pe3c_dedup
                          .sort_values("match_score", ascending=False)
                          .drop_duplicates("title_local"))

        base = fuzzy_join(
            base, "producto", pe3c_dedup, "title_local",
            cols_pe3c_keep, label="pe3c",
            threshold=FUZZY_THRESHOLD, verbose=verbose
        )

        base = base.rename(columns={
            "price_local": "precio_local_pen",       # solo informativo
            "price_import": "precio_import_usd",    # USD (lo relevante)
            "gap_pct_real_base": "gap_pct_real",
            "conviene_local_base": "conviene_local",
        })

    # JOIN 3: Pareto
    if sources["pareto"] is not None:
        base = process_pareto_fuzzy(base, sources["pareto"], threshold=FUZZY_THRESHOLD, verbose=verbose)
    else:
        base["in_pareto_front"] = False
        base["pareto_roi_pct"] = np.nan
        base["pareto_riesgo"] = np.nan
        base["pareto_tipo"] = ""
        base["fuzzy_score_pareto"] = np.nan

    # ── Alias/consistencia (no cambia matemática)
    # Si existiera otra columna ganancia esperada en otro nombre, podrías mapearla aquí.
    # Pero NO hacemos conversión PEN<->USD.
    if "precio_import_real_base" in base.columns and "precio_import_usd" not in base.columns:
        base["precio_import_usd"] = base["precio_import_real_base"]

    return base

# ─────────────────────────────────────────────────────────────────────────────
# 6. SCORE COMPUESTO
# ─────────────────────────────────────────────────────────────────────────────

def compute_score_oe9(df: pd.DataFrame) -> pd.DataFrame:
    scaler = MinMaxScaler()
    df = df.copy()

    roi_col = "score_roi_ponderado" if "score_roi_ponderado" in df.columns else "roi_unitario_pct"
    if roi_col in df.columns:
        vals = df[roi_col].fillna(0).values.reshape(-1, 1)
        df["roi_norm"] = scaler.fit_transform(vals).flatten()
    else:
        df["roi_norm"] = 0.0

    if "gap_pct" in df.columns:
        vals = df["gap_pct"].abs().fillna(0).values.reshape(-1, 1)
        df["gap_norm"] = scaler.fit_transform(vals).flatten()
    else:
        df["gap_norm"] = 0.0

    df["pareto_norm"] = df["in_pareto_front"].astype(float)

    df["score_oe9"] = (
        W_ROI * df["roi_norm"]
        + W_GAP * df["gap_norm"]
        + W_PARETO * df["pareto_norm"]
        - W_RJ * df["r_j"].fillna(0)
    ).clip(0, 1).round(4)

    df["rank_oe9"] = df["score_oe9"].rank(ascending=False, method="min").astype(int)
    df = df.drop(columns=["roi_norm", "gap_norm", "pareto_norm"], errors="ignore")
    return df

# ─────────────────────────────────────────────────────────────────────────────
# 7. COLUMNAS FINALES
# ─────────────────────────────────────────────────────────────────────────────

COLS_FINALES = [
    "sku", "producto", "marca", "categoria",
    "precio_local_pen", "precio_import_usd",
    "r_j", "label_obsolescencia", "p_vigente", "p_en_riesgo", "p_obsoleto",
    "rank_obsolescencia",
    "roi_unitario_pct", "ganancia_unitaria", "score_roi_ponderado",
    "rank_roi", "roi_pct_con", "roi_pct_agr",
    "gap_pct", "gap_usd", "gap_pct_real", "conviene_local", "match_score",
    "in_pareto_front", "pareto_roi_pct", "pareto_riesgo", "pareto_tipo",
    "fuzzy_score_roi", "fuzzy_score_pe3c", "fuzzy_score_pareto",
    "score_oe9", "rank_oe9",
]

def select_final_cols(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in COLS_FINALES if c in df.columns]
    return df[cols].copy()

# ─────────────────────────────────────────────────────────────────────────────
# 8. REPORTE
# ─────────────────────────────────────────────────────────────────────────────

def build_report(df: pd.DataFrame) -> dict:
    n = len(df)
    report = {
        "version": "2.2-fuzzy",
        "timestamp": datetime.now().isoformat(),
        "total_skus": n,
        "fuzzy_threshold": FUZZY_THRESHOLD,
        "cobertura": {},
        "fuzzy_scores": {},
        "score_oe9_stats": {},
        "label_dist": {},
        "top15_oe9": [],
        "pesos_score_oe9": {"W_ROI": W_ROI, "W_GAP": W_GAP, "W_PARETO": W_PARETO, "W_RJ": W_RJ},
    }

    for col in ["r_j", "roi_unitario_pct", "gap_pct", "in_pareto_front", "score_oe9"]:
        if col in df.columns:
            n_ok = int(df[col].sum()) if col == "in_pareto_front" else int(df[col].notna().sum())
            report["cobertura"][col] = {"n": n_ok, "pct": round(n_ok / n * 100, 1)}

    for col in ["fuzzy_score_roi", "fuzzy_score_pe3c", "fuzzy_score_pareto"]:
        if col in df.columns:
            vals = df[col].dropna()
            if len(vals):
                report["fuzzy_scores"][col] = {
                    "n_matches": int(len(vals)),
                    "mean": round(float(vals.mean()), 1),
                    "min": round(float(vals.min()), 1),
                    "max": round(float(vals.max()), 1),
                }

    if "score_oe9" in df.columns:
        report["score_oe9_stats"] = {
            "min": round(float(df["score_oe9"].min()), 4),
            "max": round(float(df["score_oe9"].max()), 4),
            "mean": round(float(df["score_oe9"].mean()), 4),
            "std": round(float(df["score_oe9"].std()), 4),
            "median": round(float(df["score_oe9"].median()), 4),
        }

    if "label_obsolescencia" in df.columns:
        for label, cnt in df["label_obsolescencia"].value_counts().items():
            report["label_dist"][label] = {"n": int(cnt), "pct": round(cnt / n * 100, 1)}

    top_cols = ["sku", "producto", "score_oe9", "r_j", "roi_unitario_pct", "gap_pct",
                "in_pareto_front", "label_obsolescencia", "fuzzy_score_roi", "fuzzy_score_pe3c"]
    top_cols = [c for c in top_cols if c in df.columns]

    for _, row in df.nlargest(15, "score_oe9")[top_cols].iterrows():
        entry = {}
        for c in top_cols:
            v = row[c]
            if pd.isna(v) if not isinstance(v, bool) else False:
                entry[c] = None
            elif isinstance(v, np.bool_):
                entry[c] = bool(v)
            elif isinstance(v, np.integer):
                entry[c] = int(v)
            elif isinstance(v, np.floating):
                entry[c] = round(float(v), 4)
            else:
                entry[c] = str(v)[:60]
        report["top15_oe9"].append(entry)

    return report

# ─────────────────────────────────────────────────────────────────────────────
# 9. VISUALIZACIÓN
# ─────────────────────────────────────────────────────────────────────────────

def plot_results(df: pd.DataFrame):
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    fig.suptitle(
        "OE9 Feature Matrix v2 — Cobertura y Distribución\n"
        f"HDS-ROI v4.0 | {datetime.now().strftime('%Y-%m-%d')}",
        fontsize=13, fontweight="bold"
    )

    ax = axes[0]
    features = ["r_j", "roi_unitario_pct", "gap_pct", "in_pareto_front"]
    labels_ax = ["r_j\n(OE4)", "ROI\n(OE4a)", "Gap\n(PE3c)", "Pareto\n(OE5)"]
    n_total = len(df)
    counts = []
    for f in features:
        if f not in df.columns:
            counts.append(0)
        elif f == "in_pareto_front":
            counts.append(int(df[f].sum()))
        else:
            counts.append(int(df[f].notna().sum()))
    pcts = [c / n_total * 100 for c in counts]
    colors = ["#2ecc71" if p == 100 else "#f39c12" if p >= 50 else "#e74c3c" for p in pcts]
    bars = ax.bar(labels_ax, pcts, color=colors, edgecolor="white", linewidth=1.2)
    for bar, cnt in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5,
                f"{cnt}/{n_total}", ha="center", va="bottom", fontsize=9)
    ax.set_ylim(0, 115)
    ax.set_ylabel("Cobertura (%)")
    ax.set_title("Cobertura por Feature", fontsize=11)
    ax.axhline(100, color="gray", linestyle="--", linewidth=0.8)

    ax2 = axes[1]
    if "label_obsolescencia" in df.columns and "score_oe9" in df.columns:
        colors_label = {"VIGENTE": "#2ecc71", "EN_RIESGO": "#f39c12", "OBSOLETO": "#e74c3c"}
        for label in ["VIGENTE", "EN_RIESGO", "OBSOLETO"]:
            sub = df[df["label_obsolescencia"] == label]["score_oe9"].dropna()
            if len(sub):
                ax2.hist(sub, bins=10, alpha=0.65, label=f"{label} (n={len(sub)})",
                         color=colors_label.get(label, "gray"), edgecolor="white")
        ax2.set_xlabel("score_oe9")
        ax2.set_ylabel("Frecuencia")
        ax2.set_title("score_oe9 por Clase Obsolescencia", fontsize=11)
        ax2.legend(fontsize=9)

    ax3 = axes[2]
    fuzz_cols = [c for c in ["fuzzy_score_roi", "fuzzy_score_pe3c", "fuzzy_score_pareto"] if c in df.columns]
    if fuzz_cols:
        data_box = [df[c].dropna().values for c in fuzz_cols]
        labels_box = [c.replace("fuzzy_score_", "").upper() for c in fuzz_cols]
        bp = ax3.boxplot(data_box, labels=labels_box, patch_artist=True,
                         medianprops=dict(color="black", linewidth=2))
        for patch, color in zip(bp["boxes"], ["#3498db", "#9b59b6", "#e67e22"]):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
        ax3.axhline(FUZZY_THRESHOLD, color="red", linestyle="--", linewidth=1.2, label=f"Umbral={FUZZY_THRESHOLD}")
        ax3.set_ylabel("Fuzzy Score (0-100)")
        ax3.set_title("Calidad de Matches Fuzzy", fontsize=11)
        ax3.legend(fontsize=9)
        ax3.set_ylim(0, 105)

    plt.tight_layout()
    plt.savefig(OUT_HEATMAP, dpi=150, bbox_inches="tight")
    plt.close()

# ─────────────────────────────────────────────────────────────────────────────
# 10. MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    global FUZZY_THRESHOLD

    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true", default=True)
    parser.add_argument("--threshold", type=int, default=FUZZY_THRESHOLD,
                        help="Umbral fuzzy match (0-100, default=80)")
    args = parser.parse_args()

    FUZZY_THRESHOLD = args.threshold

    ensure_dirs()
    log("=" * 60)
    log("  feature_integrator.py v2.2 — Fuzzy Join por Título")
    log(f"  Inicio : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"  Umbral : {FUZZY_THRESHOLD}")
    log("=" * 60)

    sources = load_sources(True)
    if sources["rj"] is None:
        log("❌ CRÍTICO: feature_rj_OE9.csv no encontrado.")
        return

    df = integrate(sources, True)
    df = compute_score_oe9(df)
    df_final = select_final_cols(df)
    df_final = df_final.sort_values("score_oe9", ascending=False).reset_index(drop=True)

    df_final.to_csv(OUT_MATRIX, index=False, encoding="utf-8")
    log(f"\n💾 Matriz: {OUT_MATRIX}  [{df_final.shape[0]} × {df_final.shape[1]}]")

    report = build_report(df_final)
    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    log(f"📄 Reporte: {OUT_REPORT}")

    plot_results(df_final)
    log(f"📊 Gráfico: {OUT_HEATMAP}")

    log(f"\n{'='*65}")
    log("📋 TOP 15 SKUs por score_oe9:")
    log(f"   {'Producto':<38} {'Label':>10} {'score':>7} {'r_j':>6} {'ROI%':>7} {'Gap%':>6} {'Par':>4} {'fROI':>5}")
    log(f"   {'-'*85}")

    for _, row in df_final.head(15).iterrows():
        prod = str(row.get("producto", ""))[:37]
        label = str(row.get("label_obsolescencia", ""))
        sc = row.get("score_oe9", 0)
        rj = row.get("r_j", 0)
        roi = row.get("roi_unitario_pct", float("nan"))
        gap = row.get("gap_pct", float("nan"))
        par = "✅" if row.get("in_pareto_front", False) else "—"
        froi = row.get("fuzzy_score_roi", float("nan"))
        roi_s = f"{roi:>7.1f}" if pd.notna(roi) else "    N/A"
        gap_s = f"{gap:>6.1f}" if pd.notna(gap) else "   N/A"
        fr_s = f"{froi:>5.0f}" if pd.notna(froi) else "  N/A"
        log(f"   {prod:<38} {label:>10} {sc:>7.4f} {rj:>6.4f} {roi_s} {gap_s} {par:>4} {fr_s}")

    log(f"\n📊 Cobertura final:")
    for feat, info in report["cobertura"].items():
        bar = "█" * int(info["pct"] / 5)
        log(f"   {feat:<25} {info['n']:>3}/{report['total_skus']} ({info['pct']:>5.1f}%) {bar}")

    log(f"\n{'='*60}")
    log("✅ Completado.")
    log(f"🔜 Siguiente: python oe9_nsga3.py --input {OUT_MATRIX}")
    log("=" * 60)

if __name__ == "__main__":
    main()
