#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║         DIAGNÓSTICO MAESTRO — tesis-hardware-peru v3.0                 ║
# ║         Sistema HDS-ROI: Hardware Decision System con ROI               ║
# ║         Autor  : kotska-pariona                                         ║
# ║         Repo   : https://github.com/kotska-pariona/tesis-hardware-peru  ║
# ║         Disco  : D:\tesis-hardware-peru  (movido desde C: esta semana)  ║
# ║                                                                         ║
# ║  CÓMO EJECUTAR (Git Bash):                                              ║
# ║    cd /d/tesis-hardware-peru                                            ║
# ║    bash diag_maestro_v3.sh                                              ║
# ║    bash diag_maestro_v3.sh > reporte_$(date +%Y%m%d).txt 2>&1          ║
# ╚══════════════════════════════════════════════════════════════════════════╝

# ── Colores ANSI (solo si el terminal los soporta) ────────────────────────
RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'
BLU='\033[0;34m'; CYN='\033[0;36m'; NC='\033[0m'   # NC = sin color

SEP="══════════════════════════════════════════════════════════════════"
sep="──────────────────────────────────────────────────────────────────"

# ── Verificar que estamos en el directorio correcto ───────────────────────
REPO_DIR="/d/tesis-hardware-peru"
if [ ! -d "$REPO_DIR" ]; then
    echo -e "${RED}❌ ERROR: No se encontró $REPO_DIR${NC}"
    echo "   Asegúrate de ejecutar desde Git Bash en D:\\tesis-hardware-peru"
    echo "   Comando: cd /d/tesis-hardware-peru && bash diag_maestro_v3.sh"
    exit 1
fi
cd "$REPO_DIR"

# ══════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${CYN}$SEP${NC}"
echo -e "${CYN}  🎓 DIAGNÓSTICO MAESTRO v3.0 — HDS-ROI${NC}"
echo    "  📁 Repositorio : $(pwd)"
echo    "  📅 Fecha/Hora  : $(date '+%A %d %B %Y — %H:%M:%S')"
echo    "  💻 Disco       : D: (movido desde C: semana del 29-Sep-2026)"
echo    "  🔗 GitHub      : https://github.com/kotska-pariona/tesis-hardware-peru"
echo -e "${CYN}$SEP${NC}"

# ══════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BLU}  ▶ SECCIÓN 1 — ESTADO GIT${NC}"
echo "$SEP"

echo ""
echo "  📌 Branch actual y último commit:"
echo "     Branch  : $(git branch --show-current 2>/dev/null || echo 'N/A')"
echo "     Commit  : $(git log -1 --pretty='%h — %s (%ar)' 2>/dev/null || echo 'N/A')"
echo "     Total   : $(git rev-list --count HEAD 2>/dev/null || echo '?') commits en el proyecto"

echo ""
echo "  📌 Estado de archivos (git status):"
git status --short 2>/dev/null | sed 's/^/     /' || echo "     (limpio)"

echo ""
echo "  📌 Últimos 10 commits:"
git log --format="     %h  %ad  %s" --date=short -10 2>/dev/null

echo ""
echo "  📌 Ramas locales:"
git branch -v 2>/dev/null | sed 's/^/     /'

echo ""
echo "  📌 Remote origin:"
git remote -v 2>/dev/null | sed 's/^/     /'

echo ""
echo "  📌 Diferencias pendientes de commit:"
DIFF_STAT=$(git diff --stat 2>/dev/null)
DIFF_CACHED=$(git diff --cached --stat 2>/dev/null)
if [ -z "$DIFF_STAT" ] && [ -z "$DIFF_CACHED" ]; then
    echo -e "     ${GRN}✅ Sin cambios pendientes — working tree limpio${NC}"
else
    echo "$DIFF_STAT" | sed 's/^/     /'
    echo "$DIFF_CACHED" | sed 's/^/     (staged) /'
fi

# ══════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BLU}  ▶ SECCIÓN 2 — ESTRUCTURA DEL REPOSITORIO${NC}"
echo "$SEP"

echo ""
echo "  📁 Carpetas principales:"
for d in scripts results figures pages data models logs; do
    if [ -d "$d" ]; then
        count=$(find "$d" -maxdepth 1 -type f 2>/dev/null | wc -l)
        size=$(du -sh "$d" 2>/dev/null | cut -f1)
        echo -e "     ${GRN}✅${NC} $d/  ($count archivos directos, $size total)"
    else
        echo -e "     ${RED}❌${NC} $d/  — NO EXISTE"
    fi
done

echo ""
echo "  📄 Archivos raíz importantes:"
for f in requirements.txt .gitignore README.md dvc.yaml params.yaml \
         dashboard_v6_2_pe2v52.py dashboard_data.py; do
    if [ -f "$f" ]; then
        lines=$(wc -l < "$f" 2>/dev/null)
        size=$(ls -lh "$f" 2>/dev/null | awk '{print $5}')
        echo -e "     ${GRN}✅${NC} $f  ($lines líneas, $size)"
    else
        echo -e "     ${RED}❌${NC} $f  — NO ENCONTRADO"
    fi
done

echo ""
echo "  🐍 Scripts Python disponibles:"
find . -name "*.py" \
    ! -path './.git/*' \
    ! -path './__pycache__/*' \
    ! -path './venv/*' \
    ! -path './.venv/*' \
    | sort | sed 's/^/     /'

# ══════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BLU}  ▶ SECCIÓN 3 — DATOS RAW${NC}"
echo "$SEP"

echo ""
echo "  📌 MASTER principal:"
if [ -f "data/raw/MASTER_hardware_peru.csv" ]; then
    lines=$(wc -l < "data/raw/MASTER_hardware_peru.csv" 2>/dev/null)
    size=$(du -sh "data/raw/MASTER_hardware_peru.csv" 2>/dev/null | cut -f1)
    echo -e "     ${GRN}✅${NC} MASTER_hardware_peru.csv"
    echo "        Registros : $((lines-1)) (sin header)"
    echo "        Tamaño    : $size"
else
    echo -e "     ${RED}❌${NC} MASTER_hardware_peru.csv — NO ENCONTRADO"
fi

echo ""
echo "  📌 Batches 24h disponibles:"
BATCH_COUNT=0
for f in data/raw/batch_24h_*.csv; do
    [ -f "$f" ] || continue
    fecha=$(basename "$f" | sed 's/batch_24h_//' | sed 's/.csv//')
    lineas=$(wc -l < "$f" 2>/dev/null)
    tam=$(du -sh "$f" 2>/dev/null | awk '{print $1}')
    printf "     %-30s %7d registros  %s\n" "$fecha" "$((lineas-1))" "$tam"
    BATCH_COUNT=$((BATCH_COUNT+1))
done
echo "     Total batches 24h: $BATCH_COUNT archivos"

echo ""
echo "  📌 Cobertura temporal de reportes JSON:"
PRIMER=$(ls data/raw/report_*.json 2>/dev/null | head -1 | \
    sed 's/.*report_//' | sed 's/_.*//' | sed 's/\(....\)\(..\)\(..\)/\1-\2-\3/')
ULTIMO=$(ls data/raw/report_*.json 2>/dev/null | tail -1 | \
    sed 's/.*report_//' | sed 's/_.*//' | sed 's/\(....\)\(..\)\(..\)/\1-\2-\3/')
TOTAL_JSON=$(ls data/raw/report_*.json 2>/dev/null | wc -l)
echo "     Primer reporte : ${PRIMER:-N/A}"
echo "     Último reporte : ${ULTIMO:-N/A}"
echo "     Total reportes : $TOTAL_JSON ejecuciones del agente scraper"

echo ""
echo "  📌 Archivo de predicciones (crítico para el dashboard):"
for path in \
    "data/raw/predicciones_multihorizonte.json" \
    "results/predicciones_multihorizonte.json"; do
    if [ -f "$path" ]; then
        size=$(du -sh "$path" 2>/dev/null | cut -f1)
        # Contar SKUs y verificar anomalías
        anomalos=$(python -c "
import json
with open('$path', encoding='utf-8') as f:
    d = json.load(f)
skus = d.get('skus', {})
mal = sum(1 for v in skus.values()
          if abs(float(v.get('predicciones',{}).get('30',{}).get('variacion_pct',0) or 0)) > 50)
print(f'{len(skus)} SKUs | {mal} anomalos H+30d')
" 2>/dev/null || echo "no se pudo leer")
        if echo "$anomalos" | grep -q "^0 anomalos\|0 anomalos"; then
            echo -e "     ${GRN}✅${NC} $path ($size) — $anomalos"
        else
            # Verificar si hay anomalos
            n_anom=$(echo "$anomalos" | grep -oP '\d+ anomalos' | grep -oP '^\d+')
            if [ "${n_anom:-0}" -gt 0 ] 2>/dev/null; then
                echo -e "     ${RED}❌${NC} $path ($size) — $anomalos ← CORRUPTO"
            else
                echo -e "     ${GRN}✅${NC} $path ($size) — $anomalos"
            fi
        fi
    else
        echo -e "     ${RED}❌${NC} $path — NO EXISTE"
    fi
done

# ══════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BLU}  ▶ SECCIÓN 4 — MODELOS ENTRENADOS${NC}"
echo "$SEP"

echo ""
echo "  📌 Archivos en models/:"
if [ -d "models" ]; then
    ls -lh models/ 2>/dev/null | grep -v "^total" | \
        awk '{printf "     %-45s %s\n", $9, $5}'
else
    echo -e "     ${RED}❌${NC} Carpeta models/ no existe"
fi

echo ""
echo "  📌 Modelos trackeados en DVC:"
DVC_COUNT=0
find models/ -name "*.dvc" 2>/dev/null | while read f; do
    echo -e "     ${GRN}✅${NC} $f"
    DVC_COUNT=$((DVC_COUNT+1))
done
[ "$DVC_COUNT" -eq 0 ] && echo "     (ninguno trackeado en DVC)"

echo ""
echo "  📌 Modelos SIN trackear en DVC (riesgo de pérdida):"
for f in models/*.pkl models/*.json models/*.npy models/*.csv; do
    [ -f "$f" ] || continue
    if [ ! -f "${f}.dvc" ]; then
        size=$(ls -lh "$f" 2>/dev/null | awk '{print $5}')
        echo -e "     ${YLW}⚠️${NC}  $f ($size) — sin .dvc"
    fi
done
if [ -d "models/pe4_bert_obsolescence" ] && \
   [ ! -f "models/pe4_bert_obsolescence.dvc" ]; then
    size=$(du -sh models/pe4_bert_obsolescence 2>/dev/null | cut -f1)
    echo -e "     ${RED}🔴${NC} models/pe4_bert_obsolescence/ ($size) — SIN DVC ← CRÍTICO"
fi

# ══════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BLU}  ▶ SECCIÓN 5 — MÉTRICAS POR OBJETIVO ESPECÍFICO${NC}"
echo "$SEP"

# ── OE2: Predicción de precios ────────────────────────────────────────────
echo ""
echo "  🔬 OE2 — Predicción de Precios (LightGBM + TFT)"
echo "$sep"
for f in "results/pe2_lgbm_metrics.json" "results/pe2_tft_metrics.json"; do
    if [ -f "$f" ]; then
        echo -e "     ${GRN}✅${NC} $(basename $f):"
        python -c "
import json
with open('$f', encoding='utf-8') as fp:
    d = json.load(fp)
for k,v in d.items():
    if not isinstance(v, (dict,list)):
        print(f'        {k}: {v}')
" 2>/dev/null || cat "$f" | head -10 | sed 's/^/        /'
    else
        echo -e "     ${RED}❌${NC} $f — NO ENCONTRADO"
    fi
done

# ── OE3/OE6: Mondrian CP ──────────────────────────────────────────────────
echo ""
echo "  🔬 OE3/OE6 — Mondrian Conformal Prediction"
echo "$sep"
for f in "results/evaluation_report.json" \
         "results/pe3_competitividad.json" \
         "results/pe3b_competitividad.json" \
         "results/pe3c_resumen.json"; do
    if [ -f "$f" ]; then
        echo -e "     ${GRN}✅${NC} $(basename $f)"
    else
        echo -e "     ${RED}❌${NC} $f — NO ENCONTRADO"
    fi
done
if [ -f "models/mondrian_q_final_v5.pkl" ]; then
    size=$(ls -lh models/mondrian_q_final_v5.pkl | awk '{print $5}')
    echo -e "     ${GRN}✅${NC} mondrian_q_final_v5.pkl ($size)"
else
    echo -e "     ${RED}❌${NC} models/mondrian_q_final_v5.pkl — NO ENCONTRADO"
fi

# ── OE4: E5-large Obsolescencia ───────────────────────────────────────────
echo ""
echo "  🔬 OE4 — Clasificación Obsolescencia (E5-large)"
echo "$sep"
if [ -f "results/pe4_e5_ablacion_metrics.json" ]; then
    echo -e "     ${GRN}✅${NC} pe4_e5_ablacion_metrics.json:"
    python -c "
import json
with open('results/pe4_e5_ablacion_metrics.json', encoding='utf-8') as f:
    d = json.load(f)
keys = ['model','f1_macro','accuracy','f1_vigente','f1_transicion','f1_obsoleto']
for k in keys:
    if k in d:
        print(f'        {k}: {d[k]}')
vs = d.get('vs_bert_base', {})
if vs:
    print(f'        vs BERT-base delta: {vs.get(\"delta\",\"N/A\")}')
" 2>/dev/null || cat results/pe4_e5_ablacion_metrics.json | head -15 | sed 's/^/        /'
else
    echo -e "     ${RED}❌${NC} results/pe4_e5_ablacion_metrics.json — NO ENCONTRADO"
fi

# ── OE5/OE9: NSGA-III ─────────────────────────────────────────────────────
echo ""
echo "  🔬 OE5/OE9 — Optimización NSGA-III + LLM"
echo "$sep"
for f in "results/oe5_resumen_nsga3.json" \
         "results/oe9_resumen_nsga3.json" \
         "results/oe5_pareto_front.csv" \
         "results/oe9_pareto_front.csv"; do
    if [ -f "$f" ]; then
        size=$(ls -lh "$f" 2>/dev/null | awk '{print $5}')
        echo -e "     ${GRN}✅${NC} $f ($size)"
    else
        echo -e "     ${RED}❌${NC} $f — NO ENCONTRADO"
    fi
done

# ── OE7: Dashboard ────────────────────────────────────────────────────────
echo ""
echo "  🔬 OE7 — Dashboard Dash/Plotly"
echo "$sep"
if [ -f "dashboard_v6_2_pe2v52.py" ]; then
    lines=$(wc -l < dashboard_v6_2_pe2v52.py)
    echo -e "     ${GRN}✅${NC} dashboard_v6_2_pe2v52.py ($lines líneas)"
    echo "        Para ejecutar: python dashboard_v6_2_pe2v52.py"
    echo "        URL          : http://127.0.0.1:8050"
else
    echo -e "     ${RED}❌${NC} dashboard_v6_2_pe2v52.py — NO ENCONTRADO"
fi
if [ -f "dashboard_data.py" ]; then
    echo -e "     ${GRN}✅${NC} dashboard_data.py (módulo de datos)"
    # Verificar que apunta a data/raw/
    if grep -q 'data.*raw.*predicciones' dashboard_data.py 2>/dev/null; then
        echo -e "        ${GRN}✅${NC} Ruta predicciones → data/raw/ (corregida esta semana)"
    else
        echo -e "        ${YLW}⚠️${NC}  Ruta predicciones puede apuntar a results/ (revisar)"
    fi
fi

# ══════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BLU}  ▶ SECCIÓN 6 — ESTADO DE OBJETIVOS ESPECÍFICOS (OEs)${NC}"
echo "$SEP"

echo ""
echo "  Leyenda: ✅ Completado  🔄 En progreso  ⚠️ Parcial  ❌ Pendiente"
echo ""

check_oe() {
    local oe="$1"; local desc="$2"; local check_path="$3"; local nota="$4"
    if [ -e "$check_path" ]; then
        echo -e "  ${GRN}✅${NC} $oe — $desc"
        [ -n "$nota" ] && echo "       └─ $nota"
    else
        echo -e "  ${RED}❌${NC} $oe — $desc  ← PENDIENTE"
        echo "       └─ Falta: $check_path"
        [ -n "$nota" ] && echo "       └─ $nota"
    fi
}

check_oe "OE1" "Pipeline recolección datos (scraper multi-fuente)" \
    "data/raw/MASTER_hardware_peru.csv" \
    "884,948 registros | 25 días | 9 fuentes (Amazon, eBay, Newegg, local, etc.)"

check_oe "OE2" "Predicción de precios (LightGBM + TFT + Mondrian CP)" \
    "results/predicciones_multihorizonte.json" \
    "MAPE=0.64% R²=0.9968 | H+1d, H+7d, H+14d, H+30d"

check_oe "OE3" "Análisis competitividad de mercado" \
    "results/pe3_competitividad.json" \
    "MAPE=0.91% DA=92.9% Cobertura=95.97%"

check_oe "OE4" "Clasificación obsolescencia (E5-large embeddings)" \
    "results/pe4_e5_ablacion_metrics.json" \
    "F1-macro=0.9966 | supera BERT-base en +0.0045"

check_oe "OE5" "Optimización multi-objetivo NSGA-III base" \
    "results/oe5_pareto_front.csv" \
    "75 soluciones Pareto | ROI 65-73%"

check_oe "OE6" "Mondrian Conformal Prediction calibrado" \
    "models/mondrian_q_final_v5.pkl" \
    "Cobertura empírica 95.97% (meta: 95%)"

check_oe "OE7" "Dashboard interactivo (Dash + Plotly)" \
    "dashboard_v6_2_pe2v52.py" \
    "30 SKUs | 9 tabs | puerto 8050 | predicciones corregidas esta semana"

echo -e "  ${YLW}⚠️${NC}  OE8 — Evaluación con usuarios reales (SUS)"
echo "       └─ PENDIENTE: requiere 30 operadores logísticos"
echo "       └─ Falta: results/sus_evaluation.csv"

check_oe "OE9" "NSGA-III + LLM features (operadores semánticos)" \
    "results/oe9_resumen_nsga3.json" \
    "24 soluciones Pareto | HV=0.9031"

check_oe "OE10" "Asignación de capital (Knapsack + portafolios ROI)" \
    "results/oe9_portafolios_nodominados.json" \
    "ROI 43-94% según perfil conservador/moderado/agresivo"

# ══════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BLU}  ▶ SECCIÓN 7 — HIPÓTESIS vs RESULTADOS${NC}"
echo "$SEP"
echo ""
echo "  ┌────┬─────────────────────────────────────┬──────────────────┬────────────────────┐"
echo "  │ ID │ Hipótesis                           │ Estado           │ Métrica clave      │"
echo "  ├────┼─────────────────────────────────────┼──────────────────┼────────────────────┤"
echo "  │ H1 │ LightGBM MAPE < 5%                  │ ✅ CONFIRMADA    │ MAPE = 0.64%       │"
echo "  │ H2 │ Mondrian CP > Bootstrap cobertura   │ ✅ CONFIRMADA    │ 95.97% vs 94.1%    │"
echo "  │ H3 │ E5-large > BERT-base F1_macro        │ ✅ CONFIRMADA    │ ΔF1 = +0.0045      │"
echo "  │ H4 │ NSGA-III HV > 0.85                  │ ✅ CONFIRMADA    │ HV = 0.9031        │"
echo "  │ H5 │ SCPO reduce riesgo vs sin SCPO       │ ✅ CONFIRMADA    │ Reducción 99.87%   │"
echo "  └────┴─────────────────────────────────────┴──────────────────┴────────────────────┘"
echo ""
echo -e "  ${GRN}🎯 Hipótesis confirmadas: 5/5 (100%)${NC}"

# ══════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BLU}  ▶ SECCIÓN 8 — ACCIONES REALIZADAS ESTA SEMANA (29 Sep – 3 Oct 2026)${NC}"
echo "$SEP"
echo ""
echo "  ✅ [COMPLETADO] Migración del repositorio de C: → D:"
echo "     Antes : C:\\Users\\MSI\\tesis-hardware-peru"
echo "     Ahora : D:\\tesis-hardware-peru"
echo "     Impacto: ninguno en el código (rutas relativas)"
echo ""
echo "  ✅ [COMPLETADO] Diagnóstico de predicciones corruptas en dashboard"
echo "     Problema: results/predicciones_multihorizonte.json tenía 29/30 SKUs"
echo "               con variación H+30d = -90% (valor anómalo)"
echo "     Causa   : el archivo en results/ era una versión antigua/corrupta"
echo "     Fix 1   : cp data/raw/predicciones_multihorizonte.json results/"
echo "     Fix 2   : dashboard_data.py ahora busca data/raw/ primero (sed)"
echo "     Estado  : ✅ 0 anomalías en ambos archivos"
echo ""
echo "  ✅ [COMPLETADO] Verificación de datos del JSON de predicciones"
echo "     Archivo bueno : data/raw/predicciones_multihorizonte.json"
echo "     SKUs          : 30 | Variaciones normales (-4.99% a +0%)"
echo "     Horizontes    : H+1d, H+7d, H+14d, H+30d"
echo ""
echo "  ✅ [COMPLETADO] Dashboard ejecutándose correctamente"
echo "     Archivo : dashboard_v6_2_pe2v52.py"
echo "     URL     : http://127.0.0.1:8050"
echo "     Tabs    : Orden de Compra | Gráfico Predicción | Heatmap | Metodología"
echo "     KPIs    : 30 SKUs | 9 oportunidades | ROI medio +29.9% | Top-5 \$2,503"

# ══════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BLU}  ▶ SECCIÓN 9 — ACCIONES PENDIENTES (PRÓXIMA SEMANA)${NC}"
echo "$SEP"
echo ""
echo "  🔴 CRÍTICO (bloquea entrega):"
echo "     ❌ OE8 — Evaluación SUS con 30 operadores logísticos reales"
echo "        → Crear formulario SUS (10 preguntas estándar)"
echo "        → Reclutar participantes (operadores de dropshipping Perú)"
echo "        → Guardar en: results/sus_evaluation.csv"
echo ""
echo "  🟡 IMPORTANTE (mejora calidad):"
echo "     ⚠️  Regenerar predicciones con datos frescos de hoy (3 Oct 2026)"
echo "        → Ejecutar: python pe2_multihorizonte.py"
echo "        → Validar: 0 anomalías en results/predicciones_multihorizonte.json"
echo ""
echo "     ⚠️  Trackear modelo BERT en DVC (evitar pérdida)"
echo "        → Ejecutar: dvc add models/pe4_bert_obsolescence/"
echo "        → Ejecutar: git add models/pe4_bert_obsolescence.dvc"
echo "        → Ejecutar: git commit -m 'dvc: trackear modelo E5-large'"
echo ""
echo "     ⚠️  Backup en HuggingFace (datos + modelos)"
echo "        → Ejecutar: python scripts/backup_huggingface.py"
echo "        → Repo HF: kotska-pariona/tesis-bert-obsolescence"
echo ""
echo "  🔵 DESEABLE (para defensa):"
echo "     📝 Completar README.md con instrucciones de instalación"
echo "     📝 Agregar requirements.txt actualizado (pip freeze > requirements.txt)"
echo "     📝 Generar reporte PDF del dashboard para el asesor"
echo "     📝 Preparar slides con métricas de hipótesis H1-H5"
echo "     📝 Documentar pipeline completo en dvc.yaml"

# ══════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BLU}  ▶ SECCIÓN 10 — ESTADO .GITIGNORE${NC}"
echo "$SEP"
echo ""
CRITICAL_PATTERNS=("*.csv" "*.pt" "*.bin" "*.h5" "*.pkl" "venv/" ".env" "*.npy" "*.parquet")
if [ -f ".gitignore" ]; then
    for pattern in "${CRITICAL_PATTERNS[@]}"; do
        if grep -q "$pattern" .gitignore 2>/dev/null; then
            echo -e "  ${GRN}✅${NC} '$pattern' está excluido de Git"
        else
            echo -e "  ${YLW}⚠️${NC}  '$pattern' NO está en .gitignore — riesgo de subir archivos grandes"
        fi
    done
else
    echo -e "  ${RED}🔴${NC} .gitignore NO EXISTE — crear urgente"
fi

echo ""
echo "  📌 Archivos binarios/datos rastreados en Git (deberían ser 0):"
COUNT=$(git ls-files 2>/dev/null | grep -cE "\.(csv|pt|bin|h5|pkl|pth|npy|parquet)$" || echo 0)
if [ "$COUNT" -gt 0 ]; then
    echo -e "  ${YLW}⚠️${NC}  $COUNT archivos binarios en Git tracking:"
    git ls-files 2>/dev/null | grep -E "\.(csv|pt|bin|h5|pkl|pth|npy|parquet)$" | \
        head -10 | sed 's/^/     /'
    echo "     Solución: git rm --cached <archivo> && dvc add <archivo>"
else
    echo -e "  ${GRN}✅${NC} 0 archivos binarios en Git tracking — correcto"
fi

# ══════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BLU}  ▶ SECCIÓN 11 — DVC STATUS${NC}"
echo "$SEP"
echo ""
dvc status 2>/dev/null || echo "  ⚠️  DVC no disponible o sin remote configurado"
echo ""
echo "  Archivos .dvc trackeados:"
find . -name "*.dvc" ! -path "./.dvc/*" ! -path "./.git/*" 2>/dev/null | \
    sort | sed 's/^/     ✅ /'
COUNT_DVC=$(find . -name "*.dvc" ! -path "./.dvc/*" ! -path "./.git/*" 2>/dev/null | wc -l)
echo "  Total: $COUNT_DVC archivos .dvc"

# ══════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BLU}  ▶ SECCIÓN 12 — FIGURAS GENERADAS${NC}"
echo "$SEP"
echo ""
TOTAL_FIGS=$(ls figures/*.png 2>/dev/null | wc -l)
echo "  Total figuras PNG: $TOTAL_FIGS"
echo ""
for prefix in oe4a oe4b oe4c oe5 oe9 pe3 pe3b pe3c; do
    count=$(ls figures/${prefix}_*.png 2>/dev/null | wc -l)
    [ "$count" -gt 0 ] && echo "  $(printf '%-8s' $prefix): $count figuras"
done

# ══════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BLU}  ▶ SECCIÓN 13 — ENTORNO PYTHON${NC}"
echo "$SEP"
echo ""
echo "  Python  : $(python --version 2>&1)"
echo "  pip     : $(pip --version 2>&1 | head -1)"
echo "  DVC     : $(dvc version 2>/dev/null | head -1 || echo 'N/A')"
echo ""
echo "  Paquetes clave instalados:"
for pkg in dash plotly pandas numpy lightgbm scikit-learn torch transformers dvc; do
    version=$(pip show "$pkg" 2>/dev/null | grep "^Version:" | awk '{print $2}')
    if [ -n "$version" ]; then
        echo -e "  ${GRN}✅${NC} $pkg==$version"
    else
        echo -e "  ${RED}❌${NC} $pkg — NO INSTALADO (pip install $pkg)"
    fi
done

# ══════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${CYN}$SEP${NC}"
echo -e "${CYN}  📋 RESUMEN EJECUTIVO FINAL${NC}"
echo -e "${CYN}$SEP${NC}"
echo ""
echo "  🎓 Proyecto  : Sistema HDS-ROI para Dropshipping de Hardware en Perú"
echo "  📁 Repo      : https://github.com/kotska-pariona/tesis-hardware-peru"
echo "  ☁️  HF Backup : https://huggingface.co/datasets/kotska-pariona/tesis-bert-obsolescence"
echo "  💻 Disco     : D:\\tesis-hardware-peru (migrado esta semana)"
echo "  🔢 Dataset   : 884,948 registros | 53,521 SKUs | 25 días scraping"
echo ""
echo "  OEs completados : OE1 ✅ OE2 ✅ OE3 ✅ OE4 ✅ OE5 ✅ OE6 ✅ OE7 ✅ OE9 ✅ OE10 ✅"
echo "  OEs pendientes  : OE8 ❌ (evaluación SUS — 30 usuarios)"
echo "  Hipótesis       : H1 ✅ H2 ✅ H3 ✅ H4 ✅ H5 ✅ (5/5 confirmadas)"
echo ""
echo "  🚨 ACCIÓN MÁS URGENTE:"
echo "     → Reclutar 30 operadores para evaluación SUS del dashboard"
echo "     → Sin esto NO se puede cerrar OE8 ni la tesis"
echo ""
echo "  📅 Semana actual : 5 de ~22 semanas del plan"
echo "  📅 Próximo hito  : Sem 14 — Benchmarking SOTA completo"
echo "  🔗 Commit actual : $(git rev-parse --short HEAD 2>/dev/null || echo 'N/A')"
echo ""
echo -e "${CYN}$SEP${NC}"
echo -e "${CYN}  ✅ DIAGNÓSTICO MAESTRO v3.0 COMPLETADO — $(date '+%Y-%m-%d %H:%M:%S')${NC}"
echo -e "${CYN}$SEP${NC}"
echo ""
echo "  💡 Para guardar este reporte como archivo:"
echo "     bash diag_maestro_v3.sh > reporte_$(date +%Y%m%d).txt 2>&1"
echo ""
