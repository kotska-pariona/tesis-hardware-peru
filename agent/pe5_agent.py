#!/usr/bin/env python3
"""
pe5_agent.py  v1.0
══════════════════════════════════════════════════════════════
Motor de decisión de precios BUY-WAIT-LIQUIDATE (PE5)

Integra tres señales:
  [S1] ROI Signal     → roi_calculator.py (PE3 base)
       BUY si ROI ≥ MARGEN_GANANCIA_MIN (15%)
       NO_BUY si importar cuesta más que comprar local

  [S2] Trend Signal   → regresión lineal sobre histórico local
       WAIT  si precio bajando (slope < -TREND_THRESHOLD)
       NOW   si precio subiendo o estable
       UNKNOWN si < MIN_POINTS_TREND puntos históricos

  [S3] Obsolescence   → score PE4 (multilingual-E5-large)
       LIQUIDATE si score_obsolescencia ≥ OBS_THRESHOLD
       (usa heurística por keywords si modelo no disponible)

Decisión final (prioridad):
  LIQUIDATE > WAIT > BUY > HOLD

Score final (0-100):
  score = roi_pct * w_roi
          + trend_score * w_trend
          - obs_penalty * w_obs

Output:
  data/processed/pe5_decisions.csv
  data/processed/pe5_report.json
══════════════════════════════════════════════════════════════
"""

import sys
import json
import logging
import time
import warnings
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ── Path fix ────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "configuracion"))
sys.path.insert(0, str(_ROOT / "agent"))
sys.path.insert(0, str(_ROOT / "analisis"))
# ────────────────────────────────────────────────────────────────────

from config import (
    MASTER_CSV, DATA_PROCESSED_DIR,
    MARGEN_GANANCIA_MIN,
    IGV, IPM, FLETE_BASE_USD,
)
from roi_calculator import (
    calculate_roi, analyze_dataframe,
    LOCAL_SOURCES, IMPORT_SOURCES, _normalize_category,
    _RATE_CACHE, CATEGORY_WEIGHTS,
)

log = logging.getLogger(__name__)

# ── Constantes PE5 ──────────────────────────────────────────────────
VERSION              = "1.0"
MIN_POINTS_TREND     = 4       # mínimo de snapshots para calcular tendencia
TREND_THRESHOLD      = 0.005   # 0.5% caída diaria → WAIT
OBS_THRESHOLD        = 0.60    # score obsolescencia ≥ 60% → LIQUIDATE
W_ROI                = 0.50    # peso ROI en score final
W_TREND              = 0.30    # peso tendencia
W_OBS                = 0.20    # penalización obsolescencia

# Keywords heurísticos para obsolescencia (fallback sin modelo PE4)
OBS_KEYWORDS = [
    "ddr3", "ddr2", "lga1151", "lga1150", "lga1155",
    "gtx 9", "gtx 10", "rx 470", "rx 480", "rx 570", "rx 580",
    "i3-8", "i5-8", "i7-8", "i3-9", "i5-9", "i7-9",
    "ryzen 1", "ryzen 2",
    "sata2", "sata ii",
    "windows 7", "windows 8",
    "2tb hdd", "1tb hdd",
]

DECISIONS_CSV = DATA_PROCESSED_DIR / "pe5_decisions.csv"
REPORT_JSON   = DATA_PROCESSED_DIR / "pe5_report.json"


# ════════════════════════════════════════════════════════════════════
# DATACLASSES
# ════════════════════════════════════════════════════════════════════

@dataclass
class TrendSignal:
    signal:       str   = "UNKNOWN"   # WAIT | NOW | UNKNOWN
    slope_pct:    float = 0.0         # % cambio diario
    n_points:     int   = 0
    price_min:    float = 0.0
    price_max:    float = 0.0
    price_last:   float = 0.0
    price_mean:   float = 0.0
    at_minimum:   bool  = False       # precio actual ≈ mínimo histórico


@dataclass
class ObsSignal:
    signal:       str   = "UNKNOWN"   # LIQUIDATE | KEEP | UNKNOWN
    score:        float = 0.0         # 0.0 - 1.0
    method:       str   = ""          # "model_pe4" | "heuristic" | "none"
    keywords_hit: list  = field(default_factory=list)


@dataclass
class Decision:
    # Identificación
    title:            str   = ""
    category:         str   = ""
    source_import:    str   = ""

    # Precios
    price_import_usd: float = 0.0
    price_local_pen:  float = 0.0
    costo_total_pen:  float = 0.0
    usd_pen:          float = 0.0

    # Señales
    roi_pct:          float = 0.0
    roi_signal:       str   = ""      # BUY | NO_BUY
    trend_signal:     str   = ""      # WAIT | NOW | UNKNOWN
    trend_slope_pct:  float = 0.0
    obs_signal:       str   = ""      # LIQUIDATE | KEEP | UNKNOWN
    obs_score:        float = 0.0
    obs_method:       str   = ""
    at_minimum:       bool  = False

    # Decisión final
    decision:         str   = ""      # BUY | WAIT | LIQUIDATE | HOLD
    score_final:      float = 0.0
    razon:            str   = ""

    # Metadata
    url_import:       str   = ""
    regimen:          str   = ""
    ahorro_pen:       float = 0.0
    timestamp:        str   = ""


# ════════════════════════════════════════════════════════════════════
# SEÑAL DE TENDENCIA [S2]
# ════════════════════════════════════════════════════════════════════

def compute_trend(
    df_local: pd.DataFrame,
    category: str,
) -> TrendSignal:
    """
    Calcula la tendencia de precios locales para una categoría.
    Usa regresión lineal sobre precio_mediano por día.
    """
    sig = TrendSignal()

    if df_local.empty:
        return sig

    df = df_local.copy()

    # Intentar parsear timestamp
    for col in ["timestamp", "scraped_at", "date", "fecha"]:
        if col in df.columns:
            try:
                df["_date"] = pd.to_datetime(df[col], errors="coerce").dt.date
                break
            except Exception:
                continue
    else:
        return sig  # sin columna de fecha

    df = df.dropna(subset=["_date", "price_pen"])
    df["price_pen"] = pd.to_numeric(df["price_pen"], errors="coerce")
    df = df[df["price_pen"] > 0]

    if df.empty:
        return sig

    # Precio mediano por día
    daily = (
        df.groupby("_date")["price_pen"]
        .median()
        .reset_index()
        .sort_values("_date")
    )

    sig.n_points  = len(daily)
    sig.price_min  = float(daily["price_pen"].min())
    sig.price_max  = float(daily["price_pen"].max())
    sig.price_last = float(daily["price_pen"].iloc[-1])
    sig.price_mean = float(daily["price_pen"].mean())

    # Precio actual cerca del mínimo histórico (±5%)
    sig.at_minimum = sig.price_last <= sig.price_min * 1.05

    if sig.n_points < MIN_POINTS_TREND:
        sig.signal = "UNKNOWN"
        return sig

    # Regresión lineal: días como x, precio como y
    x = np.arange(len(daily))
    y = daily["price_pen"].values

    try:
        slope, _ = np.polyfit(x, y, 1)
        # Normalizar: slope diario como % del precio medio
        slope_pct = slope / sig.price_mean if sig.price_mean > 0 else 0.0
        sig.slope_pct = round(float(slope_pct), 6)

        if slope_pct < -TREND_THRESHOLD:
            sig.signal = "WAIT"   # precio bajando → esperar
        else:
            sig.signal = "NOW"    # precio estable o subiendo
    except Exception as e:
        log.debug(f"  Trend error {category}: {e}")
        sig.signal = "UNKNOWN"

    return sig


# ════════════════════════════════════════════════════════════════════
# SEÑAL DE OBSOLESCENCIA [S3]
# ════════════════════════════════════════════════════════════════════

def compute_obsolescence(
    title: str,
    category: str,
    model_dir: Optional[Path] = None,
) -> ObsSignal:
    """
    Calcula score de obsolescencia.
    Intenta usar el modelo PE4 (multilingual-E5-large).
    Fallback: heurística por keywords.
    """
    sig = ObsSignal()
    title_lower = str(title).lower()

    # ── Intentar modelo PE4 ──────────────────────────────────────
    if model_dir is None:
        model_dir = _ROOT / "models" / "pe4_bert_obsolescence"

    if model_dir.exists():
        try:
            # Importación lazy — evita error si transformers no instalado
            from transformers import pipeline as hf_pipeline
            import torch

            # Cargar modelo (cacheado en memoria si ya fue cargado)
            if not hasattr(compute_obsolescence, "_pipe"):
                log.info("  [PE4] Cargando modelo de obsolescencia...")
                compute_obsolescence._pipe = hf_pipeline(
                    "text-classification",
                    model=str(model_dir),
                    device=0 if torch.cuda.is_available() else -1,
                )
                log.info("  [PE4] Modelo cargado ✅")

            result = compute_obsolescence._pipe(
                title[:512],
                truncation=True,
            )[0]

            label = result.get("label", "").upper()
            score = float(result.get("score", 0.0))

            if "OBSOLET" in label or label == "LABEL_1":
                sig.score  = score
                sig.signal = "LIQUIDATE" if score >= OBS_THRESHOLD else "KEEP"
            else:
                sig.score  = 1.0 - score
                sig.signal = "LIQUIDATE" if sig.score >= OBS_THRESHOLD else "KEEP"

            sig.method = "model_pe4"
            return sig

        except ImportError:
            log.debug("  [PE4] transformers no disponible — usando heurística")
        except Exception as e:
            log.debug(f"  [PE4] Error modelo: {e} — usando heurística")

    # ── Fallback: heurística por keywords ───────────────────────
    hits = [kw for kw in OBS_KEYWORDS if kw in title_lower]
    sig.keywords_hit = hits
    sig.method = "heuristic"

    if hits:
        # Score proporcional al número de keywords encontradas
        sig.score  = min(1.0, len(hits) * 0.35)
        sig.signal = "LIQUIDATE" if sig.score >= OBS_THRESHOLD else "KEEP"
    else:
        sig.score  = 0.0
        sig.signal = "KEEP"

    return sig


# ════════════════════════════════════════════════════════════════════
# SCORE FINAL Y DECISIÓN
# ════════════════════════════════════════════════════════════════════

def compute_decision(
    roi_pct:      float,
    roi_signal:   str,
    trend:        TrendSignal,
    obs:          ObsSignal,
) -> tuple[str, float, str]:
    """
    Combina las 3 señales en una decisión final + score.

    Prioridad: LIQUIDATE > WAIT > BUY > HOLD

    Returns: (decision, score_final, razon)
    """
    reasons = []

    # ── Señal ROI ────────────────────────────────────────────────
    roi_norm = min(100.0, max(0.0, roi_pct))   # 0-100

    # ── Señal Tendencia ──────────────────────────────────────────
    if trend.signal == "NOW":
        trend_score = 80.0
        if trend.at_minimum:
            trend_score = 100.0
            reasons.append("precio en mínimo histórico")
    elif trend.signal == "WAIT":
        trend_score = 20.0
        reasons.append(f"precio bajando {trend.slope_pct*100:.2f}%/día")
    else:
        trend_score = 50.0   # UNKNOWN → neutral

    # ── Penalización obsolescencia ───────────────────────────────
    obs_penalty = obs.score * 100   # 0-100

    # ── Score final ponderado ────────────────────────────────────
    score = (
        roi_norm    * W_ROI
        + trend_score * W_TREND
        - obs_penalty * W_OBS
    )
    score = round(max(0.0, min(100.0, score)), 2)

    # ── Decisión por prioridad ───────────────────────────────────
    if obs.signal == "LIQUIDATE":
        decision = "LIQUIDATE"
        reasons.append(
            f"obsolescencia {obs.score*100:.0f}% "
            f"[{obs.method}]"
        )

    elif trend.signal == "WAIT" and roi_signal != "BUY":
        decision = "WAIT"
        reasons.append("precio en tendencia bajista")

    elif roi_signal == "BUY":
        if trend.signal == "WAIT":
            # BUY con advertencia de tendencia bajista
            decision = "BUY"
            reasons.append(
                f"ROI {roi_pct:.1f}% atractivo "
                f"(⚠️ precio bajando — considerar esperar)"
            )
        else:
            decision = "BUY"
            reasons.append(f"ROI {roi_pct:.1f}% ≥ {MARGEN_GANANCIA_MIN*100:.0f}% mínimo")

    else:
        decision = "HOLD"
        reasons.append(
            f"ROI {roi_pct:.1f}% insuficiente "
            f"(< {MARGEN_GANANCIA_MIN*100:.0f}%)"
        )

    razon = " | ".join(reasons) if reasons else "Sin señal clara"
    return decision, score, razon


# ════════════════════════════════════════════════════════════════════
# AGENTE PRINCIPAL
# ════════════════════════════════════════════════════════════════════

class PricingAgent:
    """
    Agente de decisión de precios PE5.
    Integra ROI (PE3-base) + Tendencia + Obsolescencia (PE4).
    """

    def __init__(self, master_csv: Path = MASTER_CSV):
        self.master_csv = master_csv
        self.df_master  = pd.DataFrame()
        self.df_local   = pd.DataFrame()
        self.df_import  = pd.DataFrame()
        self.results    = []
        self._load_data()

    def _load_data(self):
        if not self.master_csv.exists():
            raise FileNotFoundError(
                f"MASTER CSV no encontrado: {self.master_csv}"
            )

        log.info(f"  Cargando MASTER: {self.master_csv}")
        df = pd.read_csv(self.master_csv, low_memory=False)
        log.info(f"  Total registros: {len(df):,}")

        df["source_lower"] = df["source"].str.lower().str.strip()
        df["category_norm"] = df["category"].apply(_normalize_category)

        self.df_master = df
        self.df_local  = df[df["source_lower"].isin(LOCAL_SOURCES)].copy()
        self.df_import = df[df["source_lower"].isin(IMPORT_SOURCES)].copy()

        log.info(
            f"  Local PE: {len(self.df_local):,} | "
            f"Importación: {len(self.df_import):,}"
        )

    def run(self) -> pd.DataFrame:
        """Ejecuta el análisis completo y retorna DataFrame de decisiones."""
        t_start = time.time()
        log.info("\n" + "═"*55)
        log.info(f"  PricingAgent v{VERSION} — iniciando análisis")
        log.info("═"*55)

        # Poblar caché de tipo de cambio (una sola llamada HTTP)
        if not _RATE_CACHE:
            try:
                from scrapers import get_exchange_rate
                rate_data = get_exchange_rate()
                _RATE_CACHE["usd_pen_venta"] = rate_data.get(
                    "usd_pen_venta", 3.75
                )
            except Exception:
                _RATE_CACHE["usd_pen_venta"] = 3.75
        usd_pen = _RATE_CACHE["usd_pen_venta"]
        log.info(f"  TC: S/ {usd_pen:.4f} por USD")

        categories = [
            c for c in self.df_master["category_norm"].unique()
            if c != "OTHER"
        ]
        log.info(f"  Categorías a analizar: {len(categories)}")

        for category in sorted(categories):
            self._analyze_category(category, usd_pen)

        if not self.results:
            log.warning("  Sin resultados generados")
            return pd.DataFrame()

        df_out = pd.DataFrame([asdict(r) for r in self.results])
        df_out = df_out.sort_values("score_final", ascending=False)

        self._save(df_out)
        self._print_summary(df_out)

        elapsed = time.time() - t_start
        log.info(f"\n  ⏱ Tiempo total: {elapsed:.1f}s")
        return df_out

    def _analyze_category(self, category: str, usd_pen: float):
        """Analiza una categoría: calcula ROI + Trend + Obs para cada producto."""
        local_cat  = self.df_local[
            self.df_local["category_norm"] == category
        ].copy()
        import_cat = self.df_import[
            self.df_import["category_norm"] == category
        ].copy()

        if local_cat.empty or import_cat.empty:
            return

        # Precio local de referencia
        local_cat["price_pen"] = pd.to_numeric(
            local_cat["price_pen"], errors="coerce"
        )
        local_cat = local_cat[local_cat["price_pen"] > 0]
        if local_cat.empty:
            return

        precio_mediano = float(local_cat["price_pen"].median())
        peso_kg        = CATEGORY_WEIGHTS.get(category, 0.5)

        # [S2] Tendencia de precios locales
        trend = compute_trend(local_cat, category)

        import_cat["price_usd"] = pd.to_numeric(
            import_cat["price_usd"], errors="coerce"
        )
        import_cat = import_cat[import_cat["price_usd"] > 0]
        if import_cat.empty:
            return

        log.info(
            f"  {category:15s}: "
            f"{len(import_cat):4d} productos | "
            f"precio local S/ {precio_mediano:.0f} | "
            f"trend={trend.signal} (slope={trend.slope_pct*100:.3f}%/día)"
        )

        for _, row in import_cat.iterrows():
            try:
                price_usd = float(row.get("price_usd") or 0)
                ship_usd  = float(row.get("shipping_usd") or 0)
                title     = str(row.get("title", ""))

                if price_usd <= 0 or not title:
                    continue

                # [S1] ROI
                roi = calculate_roi(
                    price_import_usd=price_usd,
                    price_local_pen=precio_mediano,
                    shipping_origen_usd=ship_usd,
                    peso_kg=peso_kg,
                    title=title,
                    category=category,
                    source_import=str(row.get("source", "")),
                    url_import=str(row.get("url", "")),
                    usd_pen_rate=usd_pen,
                )

                roi_signal = "BUY" if roi.conviene_importar else "NO_BUY"

                # [S3] Obsolescencia
                obs = compute_obsolescence(title, category)

                # Decisión final
                decision, score_final, razon = compute_decision(
                    roi_pct=roi.roi_pct,
                    roi_signal=roi_signal,
                    trend=trend,
                    obs=obs,
                )

                self.results.append(Decision(
                    title=title,
                    category=category,
                    source_import=str(row.get("source", "")),
                    price_import_usd=price_usd,
                    price_local_pen=precio_mediano,
                    costo_total_pen=roi.costo_total_pen,
                    usd_pen=usd_pen,
                    roi_pct=roi.roi_pct,
                    roi_signal=roi_signal,
                    trend_signal=trend.signal,
                    trend_slope_pct=trend.slope_pct,
                    obs_signal=obs.signal,
                    obs_score=obs.score,
                    obs_method=obs.method,
                    at_minimum=trend.at_minimum,
                    decision=decision,
                    score_final=score_final,
                    razon=razon,
                    url_import=str(row.get("url", "")),
                    regimen=roi.regimen,
                    ahorro_pen=roi.ahorro_pen,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ))

            except Exception as e:
                log.debug(f"    Error fila: {e}")
                continue

    def _save(self, df: pd.DataFrame):
        DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

        # CSV
        df.to_csv(DECISIONS_CSV, index=False, encoding="utf-8")
        log.info(f"\n  💾 Decisiones: {DECISIONS_CSV}")

        # Reporte JSON
        now = datetime.now(timezone.utc).isoformat()
        counts = df["decision"].value_counts().to_dict()

        top_buy = df[df["decision"] == "BUY"].head(5)[
            ["title", "category", "roi_pct", "score_final", "ahorro_pen"]
        ].to_dict("records")

        top_liquidate = df[df["decision"] == "LIQUIDATE"].head(5)[
            ["title", "category", "obs_score", "score_final"]
        ].to_dict("records")

        report = {
            "version":        VERSION,
            "timestamp":      now,
            "total_analyzed": len(df),
            "decisions":      counts,
            "pct_buy":        round(counts.get("BUY", 0) / len(df) * 100, 1),
            "pct_wait":       round(counts.get("WAIT", 0) / len(df) * 100, 1),
            "pct_liquidate":  round(counts.get("LIQUIDATE", 0) / len(df) * 100, 1),
            "pct_hold":       round(counts.get("HOLD", 0) / len(df) * 100, 1),
            "best_roi_pct":   round(float(df[df["decision"]=="BUY"]["roi_pct"].max()), 2)
                              if counts.get("BUY", 0) > 0 else 0,
            "best_ahorro_pen":round(float(df[df["decision"]=="BUY"]["ahorro_pen"].max()), 2)
                              if counts.get("BUY", 0) > 0 else 0,
            "top_buy":        top_buy,
            "top_liquidate":  top_liquidate,
            "pe3_r2":         0.9549,
            "pe4_f1":         0.9966,
        }

        with open(REPORT_JSON, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        log.info(f"  📊 Reporte:    {REPORT_JSON}")

    def _print_summary(self, df: pd.DataFrame):
        counts = df["decision"].value_counts()
        log.info("\n" + "═"*55)
        log.info("  RESUMEN PE5 — BUY-WAIT-LIQUIDATE")
        log.info("═"*55)
        for dec in ["BUY", "WAIT", "LIQUIDATE", "HOLD"]:
            n   = counts.get(dec, 0)
            pct = n / len(df) * 100
            bar = "█" * int(pct / 5)
            log.info(f"  {dec:10s}: {n:5d} ({pct:5.1f}%)  {bar}")
        log.info("═"*55)

        buy_df = df[df["decision"] == "BUY"]
        if not buy_df.empty:
            top = buy_df.nlargest(5, "score_final")
            log.info("\n  🏆 TOP 5 BUY:")
            for _, r in top.iterrows():
                log.info(
                    f"    [{r['category']:10s}] "
                    f"ROI={r['roi_pct']:6.1f}% | "
                    f"Ahorro=S/{r['ahorro_pen']:7.0f} | "
                    f"{r['title'][:50]}"
                )

        liq_df = df[df["decision"] == "LIQUIDATE"]
        if not liq_df.empty:
            top_liq = liq_df.nlargest(3, "obs_score")
            log.info("\n  ⚠️  TOP 3 LIQUIDATE:")
            for _, r in top_liq.iterrows():
                log.info(
                    f"    [{r['category']:10s}] "
                    f"Obs={r['obs_score']*100:.0f}% | "
                    f"{r['title'][:50]}"
                )


# ════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ════════════════════════════════════════════════════════════════════

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                _ROOT / "data" / "logs" / "pe5_agent.log",
                encoding="utf-8",
            ),
        ],
    )

    import argparse
    parser = argparse.ArgumentParser(
        description="PE5 — Motor BUY-WAIT-LIQUIDATE v1.0"
    )
    parser.add_argument(
        "--master", type=Path, default=MASTER_CSV,
        help="Ruta al MASTER CSV"
    )
    parser.add_argument(
        "--top", type=int, default=20,
        help="Top N resultados a mostrar"
    )
    parser.add_argument(
        "--category", type=str, default=None,
        help="Filtrar por categoría (CPU, GPU, RAM, etc.)"
    )
    args = parser.parse_args()

    agent = PricingAgent(master_csv=args.master)
    df    = agent.run()

    if df.empty:
        print("❌ Sin resultados")
        return

    # Mostrar top N
    filter_df = df
    if args.category:
        filter_df = df[
            df["category"].str.upper() == args.category.upper()
        ]

    print(f"\n{'═'*70}")
    print(f"  TOP {args.top} DECISIONES PE5")
    print(f"{'═'*70}")
    top = filter_df.head(args.top)
    for _, r in top.iterrows():
        icon = {"BUY": "✅", "WAIT": "⏳", "LIQUIDATE": "🔴", "HOLD": "⬜"}.get(
            r["decision"], "?"
        )
        print(
            f"  {icon} [{r['decision']:9s}] "
            f"[{r['category']:10s}] "
            f"score={r['score_final']:5.1f} | "
            f"ROI={r['roi_pct']:6.1f}% | "
            f"{r['title'][:45]}"
        )

    print(f"\n  📁 CSV:    {DECISIONS_CSV}")
    print(f"  📊 Reporte: {REPORT_JSON}")


if __name__ == "__main__":
    main()