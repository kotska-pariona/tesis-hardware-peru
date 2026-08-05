# =============================================================================
# obsolescencia_scorer.py — OE4: Scorer de Obsolescencia en Producción
# Proyecto: HDS-ROI v4.0 | Universidad Nacional de Ingeniería
# Autor: Kotska Rony Pariona Martinez
# Fecha: 2026-07-30
#
# MODOS DE USO:
#   1. Pipeline completo (nuevo CSV de precios):
#      python obsolescencia_scorer.py --input data/precios_nuevos.csv
#
#   2. Score de un producto individual:
#      python obsolescencia_scorer.py --texto "Procesador Intel i7-14700K LGA1700 DDR4"
#
#   3. Exportar feature r_j para OE9 (NSGA-III):
#      python obsolescencia_scorer.py --input data/precios_20260717_0313.csv --export-oe9
#
# OUTPUT: results/obsolescencia_scores_prod.csv  → r_j por SKU
#         results/feature_rj_OE9.csv             → feature listo para NSGA-III
# =============================================================================

import argparse
import warnings
import numpy as np
import pandas as pd

from pathlib import Path
from datetime import datetime

import torch
import torch.nn as nn
from sentence_transformers import SentenceTransformer

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# 0. CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────

MODEL_DIR   = Path("models")
DATA_DIR    = Path("data")
RESULTS_DIR = Path("results")

CLASSIFIER_PATH = MODEL_DIR   / "obsolescence_classifier.pt"
SCORES_PROD     = RESULTS_DIR / "obsolescencia_scores_prod.csv"
FEATURE_OE9     = RESULTS_DIR / "feature_rj_OE9.csv"
LOG_FILE        = DATA_DIR    / "scorer_log.txt"

E5_MODEL_NAME = "intfloat/multilingual-e5-large"
E5_PREFIX     = "query: "
BATCH_SIZE    = 16

LABEL_NAMES   = ["VIGENTE", "EN_RIESGO", "OBSOLETO"]
N_CLASSES     = 3

# Columnas para normalizar texto (igual que corpus_builder.py)
COL_MAP = {
    "name"       : "producto",
    "title"      : "producto",
    "nombre"     : "producto",
    "brand"      : "marca",
    "marca"      : "marca",
    "category"   : "categoria",
    "categoria"  : "categoria",
    "price_pen"  : "precio_pen",
    "price"      : "precio_pen",
    "precio"     : "precio_pen",
    "discount"   : "descuento",
    "descuento"  : "descuento",
    "sku"        : "sku",
    "url"        : "url",
    "source_file": "source_file",
}

# ─────────────────────────────────────────────────────────────────────────────
# 1. UTILIDADES
# ─────────────────────────────────────────────────────────────────────────────

def log(msg: str):
    ts   = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def ensure_dirs():
    for d in [MODEL_DIR, RESULTS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# 2. ARQUITECTURA MLP (debe ser idéntica a classifier.py)
# ─────────────────────────────────────────────────────────────────────────────

class ObsolescenceMLP(nn.Module):
    def __init__(self, input_dim: int = 1024,
                 hidden_1: int = 256, hidden_2: int = 64,
                 n_classes: int = 3,
                 dropout_1: float = 0.3, dropout_2: float = 0.2):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_1),
            nn.LayerNorm(hidden_1),
            nn.ReLU(),
            nn.Dropout(dropout_1),
            nn.Linear(hidden_1, hidden_2),
            nn.LayerNorm(hidden_2),
            nn.ReLU(),
            nn.Dropout(dropout_2),
            nn.Linear(hidden_2, n_classes),
        )

    def forward(self, x):
        return self.net(x)

    def predict_proba(self, x):
        with torch.no_grad():
            return torch.softmax(self.forward(x), dim=-1)


# ─────────────────────────────────────────────────────────────────────────────
# 3. CARGA DE MODELOS
# ─────────────────────────────────────────────────────────────────────────────

class ObsolescenciaScorer:
    """
    Scorer de producción: E5-large + MLP → r_j ∈ [0, 1]

    Uso:
        scorer = ObsolescenciaScorer()
        result = scorer.score_texto("Procesador Intel i7-14700K LGA1700 DDR4")
        result = scorer.score_dataframe(df)
    """

    def __init__(self, device: str = None):
        ensure_dirs()
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        log(f"🎮 Device: {self.device.upper()}")
        self._load_classifier()
        self._load_embedder()

    def _load_classifier(self):
        if not CLASSIFIER_PATH.exists():
            raise FileNotFoundError(
                f"No se encontró {CLASSIFIER_PATH}\n"
                "Ejecuta primero: python classifier.py"
            )
        log(f"📦 Cargando clasificador: {CLASSIFIER_PATH}")
        checkpoint = torch.load(CLASSIFIER_PATH,
                                map_location=self.device,
                                weights_only=False)

        hp = checkpoint.get("hyperparams", {})
        self.mlp = ObsolescenceMLP(
            input_dim  = checkpoint.get("input_dim", 1024),
            hidden_1   = hp.get("hidden_1", 256),
            hidden_2   = hp.get("hidden_2", 64),
            n_classes  = checkpoint.get("n_classes", 3),
            dropout_1  = hp.get("dropout_1", 0.3),
            dropout_2  = hp.get("dropout_2", 0.2),
        ).to(self.device)

        self.mlp.load_state_dict(checkpoint["model_state_dict"])
        self.mlp.eval()

        cv_mean = checkpoint.get("cv_f1_mean", 0.0)
        cv_std  = checkpoint.get("cv_f1_std",  0.0)
        ts      = checkpoint.get("timestamp", "N/A")
        log(f"✅ Clasificador cargado | CV F1={cv_mean:.4f}±{cv_std:.4f} | {ts[:10]}")

    def _load_embedder(self):
        log(f"🤖 Cargando embedder: {E5_MODEL_NAME} (desde caché local)")
        t0 = datetime.now()
        self.embedder = SentenceTransformer(E5_MODEL_NAME, device=self.device)
        elapsed = (datetime.now() - t0).total_seconds()
        log(f"✅ Embedder cargado en {elapsed:.1f}s")

    # ── Texto → embedding
    def _embed(self, texts: list[str]) -> np.ndarray:
        prefixed = [f"{E5_PREFIX}{t}" for t in texts]
        return self.embedder.encode(
            prefixed,
            batch_size=BATCH_SIZE,
            normalize_embeddings=True,
            show_progress_bar=len(texts) > 20,
            device=self.device,
            convert_to_numpy=True,
        ).astype(np.float32)

    # ── Embedding → probabilidades
    def _classify(self, embeddings: np.ndarray) -> np.ndarray:
        X_t = torch.tensor(embeddings).to(self.device)
        with torch.no_grad():
            proba = self.mlp.predict_proba(X_t).cpu().numpy()
        return proba

    # ── r_j ∈ [0, 1]
    @staticmethod
    def _compute_rj(proba: np.ndarray) -> np.ndarray:
        """
        r_j = 0.5·P(EN_RIESGO) + 1.0·P(OBSOLETO)
        Interpretación:
          0.0 → VIGENTE   (sin riesgo)
          0.5 → EN_RIESGO (riesgo moderado)
          1.0 → OBSOLETO  (riesgo máximo)
        """
        return np.clip(0.5 * proba[:, 1] + 1.0 * proba[:, 2], 0.0, 1.0)

    # ─────────────────────────────────────────────────────────────────────
    # API PÚBLICA
    # ─────────────────────────────────────────────────────────────────────

    def score_texto(self, texto: str) -> dict:
        """Clasifica un único texto y retorna dict con r_j y probabilidades."""
        emb   = self._embed([texto])
        proba = self._classify(emb)
        r_j   = self._compute_rj(proba)[0]
        label = LABEL_NAMES[proba[0].argmax()]

        result = {
            "texto"      : texto[:80],
            "label"      : label,
            "r_j"        : round(float(r_j), 4),
            "p_vigente"  : round(float(proba[0, 0]), 4),
            "p_en_riesgo": round(float(proba[0, 1]), 4),
            "p_obsoleto" : round(float(proba[0, 2]), 4),
        }
        return result

    def score_dataframe(self, df: pd.DataFrame,
                         texto_col: str = "texto") -> pd.DataFrame:
        """
        Clasifica un DataFrame completo.
        Si no existe 'texto', lo construye desde columnas disponibles.
        """
        df = df.copy()

        # Normalizar columnas
        df.columns = [COL_MAP.get(c.lower(), c.lower()) for c in df.columns]

        # Construir texto si no existe
        if texto_col not in df.columns:
            df[texto_col] = self._build_texto(df)
            log(f"   Columna 'texto' construida desde columnas disponibles")

        texts = df[texto_col].fillna("").tolist()
        log(f"⚡ Scoring {len(texts):,} productos...")

        emb   = self._embed(texts)
        proba = self._classify(emb)
        r_j   = self._compute_rj(proba)

        df["label_pred"]  = [LABEL_NAMES[i] for i in proba.argmax(axis=1)]
        df["p_vigente"]   = proba[:, 0].round(4)
        df["p_en_riesgo"] = proba[:, 1].round(4)
        df["p_obsoleto"]  = proba[:, 2].round(4)
        df["r_j"]         = r_j.round(4)

        return df

    @staticmethod
    def _build_texto(df: pd.DataFrame) -> pd.Series:
        """Construye texto descriptivo desde columnas del DataFrame."""
        parts = []
        if "producto" in df.columns:
            parts.append(df["producto"].fillna(""))
        if "marca" in df.columns:
            parts.append(("marca: " + df["marca"].fillna("")))
        if "categoria" in df.columns:
            parts.append(("categoria: " + df["categoria"].fillna("")))
        if "precio_pen" in df.columns:
            parts.append(("precio: " + df["precio_pen"].astype(str)))
        if not parts:
            raise ValueError("No se encontraron columnas para construir texto")
        return pd.concat(parts, axis=1).apply(
            lambda r: " | ".join(v for v in r if v.strip()), axis=1
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. EXPORTAR FEATURE r_j PARA OE9 (NSGA-III)
# ─────────────────────────────────────────────────────────────────────────────

def export_feature_oe9(scores_df: pd.DataFrame):
    """
    Genera el archivo feature_rj_OE9.csv para el pipeline NSGA-III.

    Columnas exportadas:
      sku         → identificador del producto
      producto    → nombre
      r_j         → feature de obsolescencia ∈ [0, 1]
      label_pred  → etiqueta predicha
      p_vigente   → probabilidad clase VIGENTE
      p_en_riesgo → probabilidad clase EN_RIESGO
      p_obsoleto  → probabilidad clase OBSOLETO
    """
    oe9_cols = ["sku", "producto", "marca", "categoria",
                "precio_pen", "r_j", "label_pred",
                "p_vigente", "p_en_riesgo", "p_obsoleto"]
    oe9_cols_exist = [c for c in oe9_cols if c in scores_df.columns]

    oe9_df = scores_df[oe9_cols_exist].copy()
    oe9_df = oe9_df.sort_values("r_j", ascending=False).reset_index(drop=True)
    oe9_df["rank_obsolescencia"] = range(1, len(oe9_df) + 1)

    oe9_df.to_csv(FEATURE_OE9, index=False, encoding="utf-8")
    log(f"💾 Feature OE9 exportado: {FEATURE_OE9}  ({len(oe9_df):,} registros)")

    # Resumen por clase
    log("\n📊 Distribución de clases (producción):")
    for label in LABEL_NAMES:
        n   = (oe9_df["label_pred"] == label).sum()
        pct = n / len(oe9_df) * 100
        rj_mean = oe9_df[oe9_df["label_pred"] == label]["r_j"].mean()
        log(f"   {label:12s}: {n:>3} ({pct:5.1f}%) | r_j medio = {rj_mean:.4f}")

    log(f"\n   r_j global → min={oe9_df['r_j'].min():.4f} "
        f"max={oe9_df['r_j'].max():.4f} "
        f"media={oe9_df['r_j'].mean():.4f}")

    return oe9_df


# ─────────────────────────────────────────────────────────────────────────────
# 5. MAIN — CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="OE4 — Scorer de Obsolescencia (E5-large + MLP)"
    )
    parser.add_argument("--input",     type=str, default=None,
                        help="CSV de productos a clasificar")
    parser.add_argument("--texto",     type=str, default=None,
                        help="Texto de un producto individual")
    parser.add_argument("--export-oe9", action="store_true",
                        help="Exportar feature r_j para pipeline NSGA-III")
    parser.add_argument("--device",    type=str, default=None,
                        choices=["cuda", "cpu"],
                        help="Forzar device (default: auto)")
    args = parser.parse_args()

    log("=" * 60)
    log("  obsolescencia_scorer.py — OE4 Scorer Producción")
    log(f"  Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 60)

    scorer = ObsolescenciaScorer(device=args.device)

    # ── MODO 1: Texto individual
    if args.texto:
        log(f"\n🔍 Clasificando texto individual:")
        log(f"   '{args.texto[:80]}'")
        result = scorer.score_texto(args.texto)
        log(f"\n   {'─'*45}")
        log(f"   Label     : {result['label']}")
        log(f"   r_j       : {result['r_j']}")
        log(f"   P(VIGENTE)  : {result['p_vigente']}")
        log(f"   P(EN_RIESGO): {result['p_en_riesgo']}")
        log(f"   P(OBSOLETO) : {result['p_obsoleto']}")
        log(f"   {'─'*45}")
        return

    # ── MODO 2: CSV completo
    if args.input:
        input_path = Path(args.input)
        if not input_path.exists():
            log(f"❌ Archivo no encontrado: {input_path}")
            return

        log(f"\n📂 Cargando: {input_path}")
        df = pd.read_csv(input_path, encoding="utf-8")
        log(f"   {len(df):,} registros | cols: {list(df.columns)}")

        scores_df = scorer.score_dataframe(df)

        # Guardar scores producción
        scores_df.to_csv(SCORES_PROD, index=False, encoding="utf-8")
        log(f"\n💾 Scores guardados: {SCORES_PROD}")

        # Preview top 10
        top10 = scores_df.sort_values("r_j", ascending=False).head(10)
        log(f"\n📋 Top 10 productos por riesgo (r_j):")
        log(f"   {'Producto':<45} {'Label':>10} {'r_j':>6}")
        log(f"   {'-'*65}")
        for _, row in top10.iterrows():
            prod  = str(row.get("producto", row.get("sku", "N/A")))[:44]
            label = row["label_pred"]
            rj    = row["r_j"]
            log(f"   {prod:<45} {label:>10} {rj:>6.4f}")

        # Exportar feature OE9
        if args.export_oe9:
            log("\n📤 Exportando feature r_j para OE9 (NSGA-III)...")
            export_feature_oe9(scores_df)

    # ── MODO 3: Sin argumentos → usar corpus de entrenamiento
    else:
        log("\n⚠️  Sin --input especificado.")
        log("   Usando corpus de entrenamiento: data/embeddings_meta.csv")

        meta_path = DATA_DIR / "embeddings_meta.csv"
        if not meta_path.exists():
            log("❌ No se encontró embeddings_meta.csv")
            log("   Uso: python obsolescencia_scorer.py --input <archivo.csv>")
            return

        df        = pd.read_csv(meta_path, encoding="utf-8")
        scores_df = scorer.score_dataframe(df, texto_col="texto")

        scores_df.to_csv(SCORES_PROD, index=False, encoding="utf-8")
        log(f"\n💾 Scores guardados: {SCORES_PROD}")

        log("\n📤 Exportando feature r_j para OE9 (NSGA-III)...")
        export_feature_oe9(scores_df)

    log("\n" + "=" * 60)
    log("✅ obsolescencia_scorer.py completado")
    log("🔜 Siguiente: integrar feature_rj_OE9.csv en pipeline NSGA-III")
    log("=" * 60)


if __name__ == "__main__":
    main()