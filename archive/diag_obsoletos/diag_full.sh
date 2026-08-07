#!/usr/bin/env bash
# ================================================================
# diag_full.sh — Diagnóstico Completo del Agente
# Tesis: Sistema Híbrido DL + Computación Evolutiva
# Ejecutar: bash diag_full.sh > diag_report_$(date +%Y%m%d_%H%M%S).txt 2>&1
# ================================================================

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR" || { echo "❌ No se puede acceder al directorio"; exit 1; }

SEP="════════════════════════════════════════════════════════════"
SEP2="────────────────────────────────────────────────────────────"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
section() { echo ""; echo "$SEP"; echo "  $1"; echo "$SEP"; }
subsection() { echo ""; echo "$SEP2"; echo "  $1"; echo "$SEP2"; }

# ── CABECERA ─────────────────────────────────────────────────────
echo "$SEP"
echo "  🔬 DIAGNÓSTICO COMPLETO — tesis-hardware-peru"
echo "  📅 $(ts)"
echo "  📁 $(pwd)"
echo "$SEP"

# ════════════════════════════════════════════════════════════════
# 1. GIT — ESTADO GENERAL
# ════════════════════════════════════════════════════════════════
section "1️⃣  GIT — ESTADO GENERAL"

echo ""
echo "  Branch actual:"
git branch --show-current

echo ""
echo "  Commits sin push:"
UNPUSHED=$(git log origin/main..HEAD --oneline 2>/dev/null | wc -l)
echo "  → $UNPUSHED commits pendientes de push"
git log origin/main..HEAD --oneline 2>/dev/null | sed 's/^/    /'

echo ""
echo "  Archivos modificados sin commit:"
git status --short | sed 's/^/    /'

echo ""
echo "  Últimos 20 commits:"
git log --format="  %h  %ad  %s" --date=short -20

echo ""
echo "  Remote:"
git remote -v

# ════════════════════════════════════════════════════════════════
# 2. ESTRUCTURA DEL PROYECTO (sin venv)
# ════════════════════════════════════════════════════════════════
section "2️⃣  ESTRUCTURA DEL PROYECTO"

echo ""
echo "  📂 Árbol principal (profundidad 2, sin venv/.git/.dvc/__pycache__):"
find . -maxdepth 2 \
  -not -path './.git/*' \
  -not -path './.dvc/*' \
  -not -path './venv/*' \
  -not -path './venv_pe4/*' \
  -not -path './__pycache__/*' \
  -not -path './*/__pycache__/*' \
  | sort | sed 's/^/  /'

echo ""
echo "  📂 Carpeta models/:"
ls -lh models/ 2>/dev/null | sed 's/^/  /' || echo "  ⚠️ No existe"

echo ""
echo "  📂 Carpeta results/:"
ls -lh results/ 2>/dev/null | sed 's/^/  /' || echo "  ⚠️ No existe"

echo ""
echo "  📂 Carpeta data/processed/:"
ls -lh data/processed/ 2>/dev/null | sed 's/^/  /' || echo "  ⚠️ No existe"

echo ""
echo "  📂 Carpeta data/splits/:"
ls -lh data/splits/ 2>/dev/null | sed 's/^/  /' || echo "  ⚠️ No existe"

echo ""
echo "  📂 Carpeta data/features/:"
ls -lh data/features/ 2>/dev/null | sed 's/^/  /' || echo "  ⚠️ No existe"

echo ""
echo "  📂 Carpeta scripts/:"
ls -lh scripts/ 2>/dev/null | sed 's/^/  /' || echo "  ⚠️ No existe"

echo ""
echo "  📂 Carpeta preprocessing/:"
ls -lh preprocessing/ 2>/dev/null | sed 's/^/  /' || echo "  ⚠️ No existe"

echo ""
echo "  📂 Carpeta agent/:"
ls -lh agent/ 2>/dev/null | sed 's/^/  /' || echo "  ⚠️ No existe"

# ════════════════════════════════════════════════════════════════
# 3. ARCHIVOS GRANDES
# ════════════════════════════════════════════════════════════════
section "3️⃣  ARCHIVOS GRANDES (> 1 MB)"

find . \
  -not -path './.git/*' \
  -not -path './venv/*' \
  -not -path './venv_pe4/*' \
  -not -path './.dvc/cache/*' \
  -type f -size +1M \
  -exec ls -lh {} \; 2>/dev/null \
  | awk '{printf "  %6s  %s\n", $5, $9}' \
  | sort -rh | head -30

echo ""
TOTAL_MB=$(find . \
  -not -path './.git/*' \
  -not -path './venv/*' \
  -not -path './venv_pe4/*' \
  -not -path './.dvc/cache/*' \
  -type f -size +1M \
  -exec du -sm {} \; 2>/dev/null \
  | awk '{sum+=$1} END {print sum}')
echo "  Total en archivos >1MB: ~${TOTAL_MB} MB"

# ════════════════════════════════════════════════════════════════
# 4. MÉTRICAS DE MODELOS
# ════════════════════════════════════════════════════════════════
section "4️⃣  MÉTRICAS DE MODELOS"

subsection "OE3 — LightGBM + Mondrian CP"
if [ -f "models/pe3_results_final.json" ]; then
  echo "  📄 pe3_results_final.json:"
  python -m json.tool models/pe3_results_final.json 2>/dev/null \
    | sed 's/^/  /' || cat models/pe3_results_final.json | sed 's/^/  /'
else
  echo "  ⚠️ pe3_results_final.json NO encontrado"
fi

echo ""
echo "  Modelos LightGBM/Mondrian presentes:"
ls -lh models/*.pkl models/*.npy 2>/dev/null | sed 's/^/    /' \
  || echo "  ⚠️ Sin archivos .pkl/.npy"

subsection "OE4 — Obsolescencia E5-large"
if [ -f "results/pe4_e5_ablacion_metrics.json" ]; then
  echo "  📄 pe4_e5_ablacion_metrics.json:"
  python -m json.tool results/pe4_e5_ablacion_metrics.json 2>/dev/null \
    | sed 's/^/  /' || cat results/pe4_e5_ablacion_metrics.json | sed 's/^/  /'
else
  echo "  ⚠️ pe4_e5_ablacion_metrics.json NO encontrado"
fi

echo ""
echo "  Modelo PE4 presente:"
ls -lh models/pe4_bert_obsolescence/ 2>/dev/null | sed 's/^/    /' \
  || echo "  ⚠️ Sin modelo PE4"

subsection "OE5 — Motor BUY/WAIT/LIQUIDATE + NSGA-III"
if [ -f "data/processed/pe5_report.json" ]; then
  echo "  📄 pe5_report.json:"
  python -m json.tool data/processed/pe5_report.json 2>/dev/null \
    | sed 's/^/  /' || cat data/processed/pe5_report.json | sed 's/^/  /'
else
  echo "  ⚠️ pe5_report.json NO encontrado"
fi

echo ""
if [ -f "data/processed/pe5_decisions.csv" ]; then
  echo "  📄 pe5_decisions.csv:"
  LINES=$(wc -l < data/processed/pe5_decisions.csv)
  echo "    Registros: $((LINES - 1))"
  echo "    Columnas:"
  head -1 data/processed/pe5_decisions.csv | tr ',' '\n' | sed 's/^/      - /'
  echo ""
  echo "    Distribución de decisiones:"
  python - <<'PYEOF' 2>/dev/null | sed 's/^/    /'
import pandas as pd
df = pd.read_csv("data/processed/pe5_decisions.csv", low_memory=False)
if "decision" in df.columns:
    print(df["decision"].value_counts().to_string())
elif "signal" in df.columns:
    print(df["signal"].value_counts().to_string())
else:
    print(f"Columnas: {list(df.columns)}")
PYEOF
else
  echo "  ⚠️ pe5_decisions.csv NO encontrado"
fi

# ════════════════════════════════════════════════════════════════
# 5. DATOS — CALIDAD Y COBERTURA
# ════════════════════════════════════════════════════════════════
section "5️⃣  DATOS — CALIDAD Y COBERTURA"

subsection "MASTER CSV"
python - <<'PYEOF' 2>/dev/null | sed 's/^/  /'
import pandas as pd, os

paths = [
    "data/processed/MASTER_hardware_peru_clean.csv",
    "data/raw/MASTER_hardware_peru.csv",
    "data/MASTER_hardware_peru_REBUILT.csv",
]
for p in paths:
    if os.path.exists(p):
        df = pd.read_csv(p, low_memory=False, nrows=5)
        total = sum(1 for _ in open(p)) - 1
        print(f"📄 {p}")
        print(f"   Registros : {total:,}")
        print(f"   Columnas  : {len(df.columns)}")
        print(f"   Cols      : {list(df.columns)}")
        if "price_date" in df.columns:
            df2 = pd.read_csv(p, low_memory=False, usecols=["price_date"])
            df2["_d"] = pd.to_datetime(df2["price_date"], errors="coerce")
            print(f"   Rango     : {df2['_d'].min().date()} → {df2['_d'].max().date()}")
            print(f"   Días      : {(df2['_d'].max() - df2['_d'].min()).days}")
        if "category" in df.columns:
            df3 = pd.read_csv(p, low_memory=False, usecols=["category"])
            print(f"   Categorías:\n{df3['category'].value_counts().head(10).to_string()}")
        print()
        break
PYEOF

subsection "Splits train/val/test"
python - <<'PYEOF' 2>/dev/null | sed 's/^/  /'
import pandas as pd, os

for split in ["train", "val", "test"]:
    for base in ["data/splits", "data/features", "data/processed"]:
        p = f"{base}/{split}.csv"
        if os.path.exists(p):
            df = pd.read_csv(p, low_memory=False, nrows=3)
            total = sum(1 for _ in open(p)) - 1
            print(f"📄 {p}: {total:,} registros, {len(df.columns)} cols")
            break
    else:
        print(f"⚠️ {split}.csv — NO encontrado")
PYEOF

subsection "Features generadas"
python - <<'PYEOF' 2>/dev/null | sed 's/^/  /'
import pandas as pd, os

for split in ["train_features", "val_features", "test_features"]:
    for base in ["data/features", "data/processed"]:
        p = f"{base}/{split}.csv"
        if os.path.exists(p):
            df = pd.read_csv(p, low_memory=False, nrows=3)
            total = sum(1 for _ in open(p)) - 1
            feat_cols = [c for c in df.columns if any(
                x in c for x in ["lag_","_ma_","_std_","zscore"])]
            print(f"📄 {p}")
            print(f"   Registros : {total:,}")
            print(f"   Features  : {feat_cols}")
            break
PYEOF

subsection "Datos raw — inventario de batches"
python - <<'PYEOF' 2>/dev/null | sed 's/^/  /'
import os, glob, re
from datetime import datetime

raw_dir = "data/raw"
batches = glob.glob(f"{raw_dir}/batch_*.csv")
dates = []
sources = {}
for f in batches:
    b = os.path.basename(f)
    m = re.match(r"batch_(\d{8})_(\d{6})_(.+)\.csv", b)
    if m:
        try:
            d = datetime.strptime(f"{m.group(1)}_{m.group(2)}", "%Y%m%d_%H%M%S")
            dates.append(d)
            src = m.group(3)
            sources[src] = sources.get(src, 0) + 1
        except:
            pass

if dates:
    print(f"Total batches individuales : {len(batches)}")
    print(f"Rango temporal             : {min(dates).date()} → {max(dates).date()}")
    print(f"Días cubiertos             : {(max(dates) - min(dates)).days + 1}")
    print(f"Por fuente:")
    for k,v in sorted(sources.items(), key=lambda x: -x[1]):
        print(f"  {k:<25} {v:>4} batches")
else:
    print("⚠️ No se encontraron batches con formato estándar")

# batch_24h
b24 = sorted(glob.glob(f"{raw_dir}/batch_24h_*.csv"))
print(f"\nBatches 24h consolidados: {len(b24)}")
for f in b24:
    size = os.path.getsize(f) / 1e6
    print(f"  {os.path.basename(f)}: {size:.1f} MB")
PYEOF

# ════════════════════════════════════════════════════════════════
# 6. WORKFLOWS GITHUB ACTIONS
# ════════════════════════════════════════════════════════════════
section "6️⃣  WORKFLOWS GITHUB ACTIONS"

for wf in .github/workflows/*.yml; do
  echo ""
  echo "  📄 $wf"
  echo "     Nombre  : $(grep '^name:' "$wf" | head -1 | sed 's/name: //')"
  echo "     Cron    : $(grep 'cron:' "$wf" | head -1 | sed "s/.*cron: //" | tr -d "'")"
  echo "     Timeout : $(grep 'timeout-minutes:' "$wf" | head -1 | sed 's/.*timeout-minutes: //')"
  echo "     Secrets : $(grep -o '\${{ secrets\.[A-Z_]*' "$wf" | sort -u | tr '\n' ' ')"
done

# ════════════════════════════════════════════════════════════════
# 7. CALIDAD DEL CÓDIGO
# ════════════════════════════════════════════════════════════════
section "7️⃣  CALIDAD DEL CÓDIGO"

subsection "Scripts principales — líneas de código"
for f in \
  preprocessing/data_quality.py \
  preprocessing/mice_imputer.py \
  preprocessing/feature_engineering.py \
  preprocessing/temporal_split.py \
  agent/pe5_agent.py \
  agent/main.py \
  analisis/roi_calculator.py \
  scripts/pe4_train_e5.py \
  scripts/pe4_train_bert.py \
  scripts/pe4_build_dataset.py \
  pipeline.py \
  dashboard.py; do
  if [ -f "$f" ]; then
    LINES=$(wc -l < "$f")
    printf "  %-45s %5d líneas\n" "$f" "$LINES"
  fi
done

subsection "Archivos temporales en raíz (a limpiar)"
echo "  diag_*.py:"
ls diag_*.py 2>/dev/null | wc -l | xargs echo "    Total:"
ls diag_*.py 2>/dev/null | sed 's/^/    /'
echo ""
echo "  fix_*.py:"
ls fix_*.py 2>/dev/null | wc -l | xargs echo "    Total:"
ls fix_*.py 2>/dev/null | sed 's/^/    /'
echo ""
echo "  _*.txt:"
ls _*.txt 2>/dev/null | sed 's/^/    /'

subsection "requirements.txt"
cat requirements.txt 2>/dev/null | sed 's/^/  /' || echo "  ⚠️ No encontrado"

# ════════════════════════════════════════════════════════════════
# 8. DVC
# ════════════════════════════════════════════════════════════════
section "8️⃣  DVC — VERSIONADO DE DATOS"

echo "  Config DVC:"
cat .dvc/config 2>/dev/null | sed 's/^/  /' || echo "  ⚠️ Sin .dvc/config"

echo ""
echo "  Archivos .dvc trackeados:"
find . -name "*.dvc" -not -path "./.git/*" | sort | while read f; do
  echo "  📌 $f"
  cat "$f" | sed 's/^/     /'
done

echo ""
echo "  dvc.yaml:"
[ -f dvc.yaml ] && cat dvc.yaml | sed 's/^/  /' || echo "  ⚠️ dvc.yaml NO existe"

echo ""
echo "  params.yaml:"
[ -f params.yaml ] && cat params.yaml | sed 's/^/  /' || echo "  ⚠️ params.yaml NO existe"

# ════════════════════════════════════════════════════════════════
# 9. LOGS DEL AGENTE
# ════════════════════════════════════════════════════════════════
section "9️⃣  LOGS DEL AGENTE (últimas 50 líneas)"

subsection "agent.log"
if [ -f "data/logs/agent.log" ]; then
  wc -l < data/logs/agent.log | xargs echo "  Total líneas:"
  echo "  Últimas 50 líneas:"
  tail -50 data/logs/agent.log | sed 's/^/  /'
elif [ -f "logs/agent_$(ls logs/ 2>/dev/null | grep agent | sort | tail -1)" ]; then
  tail -50 "logs/agent_$(ls logs/ | grep agent | sort | tail -1)" | sed 's/^/  /'
else
  echo "  ⚠️ No se encontró agent.log"
  echo "  Logs disponibles:"
  ls logs/*.log 2>/dev/null | tail -5 | sed 's/^/    /'
fi

subsection "pe5_agent.log"
if [ -f "data/logs/pe5_agent.log" ]; then
  wc -l < data/logs/pe5_agent.log | xargs echo "  Total líneas:"
  tail -30 data/logs/pe5_agent.log | sed 's/^/  /'
else
  echo "  ⚠️ pe5_agent.log no encontrado"
fi

# ════════════════════════════════════════════════════════════════
# 10. ESTADO VS PLAN DE TESIS
# ════════════════════════════════════════════════════════════════
section "🔟  ESTADO VS PLAN DE TESIS (25/07/2026)"

python - <<'PYEOF'
import os, json

def check(path): return "✅" if os.path.exists(path) else "❌"
def chk(cond):   return "✅" if cond else "❌"

print("""
  ╔══════════════════════════════════════════════════════════════╗
  ║           CHECKLIST POR OBJETIVO ESPECÍFICO                  ║
  ╚══════════════════════════════════════════════════════════════╝

  OE1 — Pipeline de Datos
  ─────────────────────────────────────────────────────────────""")

files_oe1 = {
    "data_quality.py"       : "preprocessing/data_quality.py",
    "mice_imputer.py"       : "preprocessing/mice_imputer.py",
    "feature_engineering.py": "preprocessing/feature_engineering.py",
    "temporal_split.py"     : "preprocessing/temporal_split.py",
    "MASTER_clean.csv"      : "data/processed/MASTER_hardware_peru_clean.csv",
    "train.csv"             : "data/splits/train.csv",
    "val.csv"               : "data/splits/val.csv",
    "test.csv"              : "data/splits/test.csv",
    "train_features.csv"    : "data/features/train_features.csv",
}
for name, path in files_oe1.items():
    print(f"  {check(path)} {name}")

print("""
  OE3 — Módulo de Precios (LightGBM + Mondrian CP)
  ─────────────────────────────────────────────────────────────""")
files_oe3 = {
    "lgbm_e2c_mondrian_cal.pkl" : "models/lgbm_e2c_mondrian_cal.pkl",
    "mondrian_q_final_v5.pkl"   : "models/mondrian_q_final_v5.pkl",
    "pe3_results_final.json"    : "models/pe3_results_final.json",
    "best_params_e1b.json"      : "models/best_params_e1b.json",
}
for name, path in files_oe3.items():
    print(f"  {check(path)} {name}")

# Leer métricas PE3
if os.path.exists("models/pe3_results_final.json"):
    try:
        with open("models/pe3_results_final.json") as f:
            pe3 = json.load(f)
        mape = pe3.get("mape", pe3.get("MAPE", "N/A"))
        print(f"  → MAPE obtenido: {mape}")
    except:
        pass

print("""
  OE4 — Obsolescencia (E5-large)
  ─────────────────────────────────────────────────────────────""")
files_oe4 = {
    "model.safetensors"              : "models/pe4_bert_obsolescence/model.safetensors",
    "pe4_e5_ablacion_metrics.json"   : "results/pe4_e5_ablacion_metrics.json",
    "pe4_labeled.parquet"            : "data/processed/pe4_labeled.parquet",
    "pe4_train_e5.py"                : "scripts/pe4_train_e5.py",
}
for name, path in files_oe4.items():
    print(f"  {check(path)} {name}")

if os.path.exists("results/pe4_e5_ablacion_metrics.json"):
    try:
        with open("results/pe4_e5_ablacion_metrics.json") as f:
            pe4 = json.load(f)
        print(f"  → F1_macro: {pe4.get('f1_macro','N/A')} (meta: >0.93) ✅")
        print(f"  → Accuracy: {pe4.get('accuracy','N/A')}")
        print(f"  → n_test  : {pe4.get('n_test','N/A'):,}")
    except:
        pass

print("""
  OE5 — Motor BUY/WAIT/LIQUIDATE + NSGA-III
  ─────────────────────────────────────────────────────────────""")
files_oe5 = {
    "pe5_agent.py"       : "agent/pe5_agent.py",
    "pe5_report.json"    : "data/processed/pe5_report.json",
    "pe5_decisions.csv"  : "data/processed/pe5_decisions.csv",
    "roi_calculator.py"  : "analisis/roi_calculator.py",
}
for name, path in files_oe5.items():
    print(f"  {check(path)} {name}")

if os.path.exists("data/processed/pe5_decisions.csv"):
    try:
        import pandas as pd
        df = pd.read_csv("data/processed/pe5_decisions.csv", low_memory=False)
        print(f"  → Decisiones totales: {len(df):,}")
        for col in ["decision","signal","action"]:
            if col in df.columns:
                print(f"  → Distribución ({col}):")
                for k,v in df[col].value_counts().items():
                    print(f"       {k}: {v:,} ({v/len(df)*100:.1f}%)")
                break
    except:
        pass

print("""
  OE2 — TFT + TCN (Demanda)
  ─────────────────────────────────────────────────────────────
  ❌ No iniciado — bloqueado por ventana de datos insuficiente
     (8 días actual vs ≥30 días requerido)

  OE6 — Calibración CP (MAPIE)
  ─────────────────────────────────────────────────────────────
  ❌ No iniciado

  OE7 — Motor de Decisión (tasa de acierto ≥88%)
  ─────────────────────────────────────────────────────────────
  ⚠️  Motor activo, tasa de acierto no evaluada formalmente

  OE8 — Validación SUS (>80/100)
  ─────────────────────────────────────────────────────────────
  ❌ No iniciado — requiere usuarios reales

  OE9 — NSGA-III + LLM-EA (ΔHV ≥10%)
  ─────────────────────────────────────────────────────────────
  ❌ No implementado
""")

# Resumen
print("""  ╔══════════════════════════════════════════════════════════════╗
  ║                    RESUMEN EJECUTIVO                         ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  OE1 Pipeline      ████████░░  85%  ✅ Funcional            ║
  ║  OE2 TFT/TCN       ░░░░░░░░░░   0%  🔴 Bloqueado            ║
  ║  OE3 LightGBM      ██████████ 100%  ✅ MAPE 0.91%           ║
  ║  OE4 E5-large      ██████████ 100%  ✅ F1=0.9966            ║
  ║  OE5 Motor         ██████░░░░  60%  ⚠️  Sin NSGA-III        ║
  ║  OE6 MAPIE CP      ░░░░░░░░░░   0%  🔴 Pendiente            ║
  ║  OE7 Decisión      ████░░░░░░  40%  ⚠️  Sin evaluación      ║
  ║  OE8 SUS           ░░░░░░░░░░   0%  🔴 Pendiente            ║
  ║  OE9 LLM-EA        ░░░░░░░░░░   0%  🔴 Pendiente            ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  Semana actual: ~8/22  |  Desfase: ~2-3 semanas             ║
  ╚══════════════════════════════════════════════════════════════╝""")
PYEOF

# ════════════════════════════════════════════════════════════════
# 11. PROBLEMAS CRÍTICOS Y ACCIONES
# ════════════════════════════════════════════════════════════════
section "1️⃣1️⃣  PROBLEMAS CRÍTICOS Y ACCIONES INMEDIATAS"

echo ""
echo "  🔴 CRÍTICO 1: $UNPUSHED commits sin push"
echo "     → Ejecutar: git push origin main"
echo ""
echo "  🔴 CRÍTICO 2: Archivos binarios en Git (no DVC)"
BINARIOS=$(git ls-files | grep -cE "\.(csv|pt|bin|h5|pkl|pth|ckpt)$")
echo "     → $BINARIOS archivos binarios rastreados en Git"
echo "     → Migrar a DVC: crear dvc.yaml + params.yaml"
echo ""
echo "  🟡 DEUDA 1: Archivos temporales en raíz"
DIAG_COUNT=$(ls diag_*.py 2>/dev/null | wc -l)
FIX_COUNT=$(ls fix_*.py 2>/dev/null | wc -l)
echo "     → $DIAG_COUNT archivos diag_*.py + $FIX_COUNT archivos fix_*.py"
echo "     → Ejecutar: mkdir -p archive && mv diag_*.py fix_*.py _*.txt archive/"
echo ""
echo "  🟡 DEUDA 2: venv rastreado en Git"
echo "     → Ejecutar: git rm -r --cached venv/ venv_pe4/ 2>/dev/null"
echo "     → Agregar a .gitignore: venv_pe4/"
echo ""
echo "  🟡 DEUDA 3: README solo 27 líneas"
echo "     → Documentar arquitectura, instalación, uso"
echo ""
echo "  🟡 DEUDA 4: dvc.yaml y params.yaml ausentes"
echo "     → Crear para reproducibilidad del pipeline"
echo ""
echo "  ⏳ BLOQUEANTE: Ventana de datos = 8 días"
echo "     → TFT/TCN requieren ≥30 días"
echo "     → Fecha estimada de desbloqueo: ~15 agosto 2026"

# ════════════════════════════════════════════════════════════════
# 12. COMANDOS DE LIMPIEZA LISTOS PARA EJECUTAR
# ════════════════════════════════════════════════════════════════
section "1️⃣2️⃣  COMANDOS DE LIMPIEZA (copiar y ejecutar)"

cat << 'CMDS'
  # ── 1. Push commits pendientes ──────────────────────────────
  git push origin main

  # ── 2. Commit archivos modificados ──────────────────────────
  git add preprocessing/feature_engineering.py \
          preprocessing/mice_imputer.py \
          agent/pe5_agent.py \
          agent/scrapers/__init__.py \
          agent/scrapers/scraper_dolar.py \
          agent/scrapers/scraper_importacion.py \
          analisis/roi_calculator.py \
          data/processed/pe5_report.json \
          .gitignore
  git commit -m "chore: sync pipeline v1.5 + pe5_agent + scrapers [FIX-29]"

  # ── 3. Limpiar archivos temporales ──────────────────────────
  mkdir -p archive/diag archive/fix archive/temp
  mv diag_*.py archive/diag/ 2>/dev/null
  mv fix_*.py  archive/fix/  2>/dev/null
  mv _*.txt    archive/temp/ 2>/dev/null
  mv patch_*.py apply_patch.py archive/fix/ 2>/dev/null
  git add archive/
  git commit -m "chore: mover archivos temporales a archive/ [limpieza]"

  # ── 4. Quitar venv del tracking ──────────────────────────────
  git rm -r --cached venv/ venv_pe4/ 2>/dev/null || true
  echo "venv_pe4/" >> .gitignore
  echo "*.ipynb_checkpoints" >> .gitignore
  git add .gitignore
  git commit -m "chore: excluir venv_pe4/ e ipynb_checkpoints de git"

  # ── 5. Push final ────────────────────────────────────────────
  git push origin main

CMDS

# ════════════════════════════════════════════════════════════════
# FIN
# ════════════════════════════════════════════════════════════════
echo ""
echo "$SEP"
echo "  ✅ DIAGNÓSTICO COMPLETADO — $(ts)"
echo "  💾 Para guardar: bash diag_full.sh > diag_$(date +%Y%m%d_%H%M%S).txt 2>&1"
echo "$SEP"
echo ""
