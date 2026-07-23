#!/usr/bin/env bash
# ============================================================
#  PE4 — Dataset Verifier v1.0
#  Uso: bash pe4_verify_dataset.sh <archivo.csv>
#  Detecta: columnas, etiquetas, clases, distribución
# ============================================================

set -euo pipefail

# ── Colores ──────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

# ── Argumento ────────────────────────────────────────────────
if [[ $# -lt 1 ]]; then
  echo -e "${RED}❌ Uso: bash $0 <archivo.csv>${NC}"
  echo -e "   Ejemplo: bash $0 MASTER_hardware_peru.csv"
  exit 1
fi

FILE="$1"

if [[ ! -f "$FILE" ]]; then
  echo -e "${RED}❌ Archivo no encontrado: $FILE${NC}"
  exit 1
fi

# ── Separador detectado automáticamente ──────────────────────
FIRST_LINE=$(head -1 "$FILE")
if echo "$FIRST_LINE" | grep -q ";"; then
  SEP=";"
elif echo "$FIRST_LINE" | grep -q "|"; then
  SEP="|"
else
  SEP=","
fi
echo -e "${CYAN}🔍 Separador detectado: '${SEP}'${NC}"

# ── Función barra de progreso ─────────────────────────────────
bar() {
  local val=$1 max=$2 width=30
  local filled=$(( val * width / (max > 0 ? max : 1) ))
  local bar_str=""
  for ((i=0; i<filled; i++)); do bar_str+="█"; done
  for ((i=filled; i<width; i++)); do bar_str+="░"; done
  echo "$bar_str"
}

# ============================================================
echo ""
echo -e "${BOLD}${CYAN}============================================================${NC}"
echo -e "${BOLD}${CYAN}  📋 SECCIÓN 1 — ESTRUCTURA GENERAL DEL ARCHIVO${NC}"
echo -e "${BOLD}${CYAN}============================================================${NC}"

# Total de filas (sin header)
TOTAL_ROWS=$(( $(wc -l < "$FILE") - 1 ))
echo -e "  📁 Archivo:        ${BOLD}$FILE${NC}"
echo -e "  📏 Tamaño:         $(du -sh "$FILE" | cut -f1)"
echo -e "  📊 Filas totales:  ${BOLD}$(printf "%'d" $TOTAL_ROWS)${NC}"

# Columnas desde header
HEADER=$(head -1 "$FILE")
IFS="$SEP" read -ra COLS <<< "$HEADER"
NUM_COLS=${#COLS[@]}
echo -e "  🗂️  Columnas:       ${BOLD}$NUM_COLS${NC}"

echo ""
echo -e "  ${BOLD}Columnas detectadas:${NC}"
for i in "${!COLS[@]}"; do
  COL_NAME=$(echo "${COLS[$i]}" | tr -d '"' | xargs)
  echo -e "    [$(printf "%02d" $((i+1)))] ${GREEN}${COL_NAME}${NC}"
done

# ============================================================
echo ""
echo -e "${BOLD}${CYAN}============================================================${NC}"
echo -e "${BOLD}${CYAN}  🏷️  SECCIÓN 2 — BÚSQUEDA DE COLUMNAS DE ETIQUETA${NC}"
echo -e "${BOLD}${CYAN}============================================================${NC}"

# Palabras clave para detectar columna de etiqueta
LABEL_KEYWORDS="etiqueta|label|obsolesc|estado|status|clase|class|categoria|category|tipo|type"

LABEL_COLS=()
for i in "${!COLS[@]}"; do
  COL_CLEAN=$(echo "${COLS[$i]}" | tr -d '"' | xargs | tr '[:upper:]' '[:lower:]')
  if echo "$COL_CLEAN" | grep -qE "$LABEL_KEYWORDS"; then
    LABEL_COLS+=("$((i+1)):${COLS[$i]}")
    echo -e "  ✅ ${GREEN}Columna candidata encontrada:${NC} '${COLS[$i]}' (col $((i+1)))"
  fi
done

if [[ ${#LABEL_COLS[@]} -eq 0 ]]; then
  echo -e "  ${YELLOW}⚠️  No se encontró columna de etiqueta explícita${NC}"
  echo -e "  ${YELLOW}   → Se usará etiquetado semi-automático por keywords${NC}"
fi

# ============================================================
echo ""
echo -e "${BOLD}${CYAN}============================================================${NC}"
echo -e "${BOLD}${CYAN}  📊 SECCIÓN 3 — DISTRIBUCIÓN DE CLASES POR COLUMNA${NC}"
echo -e "${BOLD}${CYAN}============================================================${NC}"

for ENTRY in "${LABEL_COLS[@]}"; do
  COL_IDX=$(echo "$ENTRY" | cut -d: -f1)
  COL_NAME=$(echo "$ENTRY" | cut -d: -f2 | tr -d '"' | xargs)

  echo ""
  echo -e "  ${BOLD}📌 Columna: '${COL_NAME}' (posición $COL_IDX)${NC}"
  echo -e "  ─────────────────────────────────────────────"

  # Distribución de valores únicos con awk
  awk -v col="$COL_IDX" -v sep="$SEP" -v total="$TOTAL_ROWS" '
  BEGIN { FS=sep }
  NR > 1 {
    gsub(/"/, "", $col)
    val = $col
    gsub(/^[ \t]+|[ \t]+$/, "", val)
    if (val == "") val = "(vacío)"
    count[val]++
  }
  END {
    for (v in count) {
      pct = count[v] * 100 / total
      printf "  %-25s %6d  (%5.1f%%)\n", v, count[v], pct
    }
  }' "$FILE" | sort -t'%' -k1 -rn

  # Valores únicos totales
  UNIQUE=$(awk -v col="$COL_IDX" -v sep="$SEP" '
    BEGIN{FS=sep} NR>1{gsub(/"/, "", $col); print $col}
  ' "$FILE" | sort -u | wc -l)
  echo -e "  ${CYAN}  → Valores únicos: $UNIQUE${NC}"

  # Nulos / vacíos
  NULLS=$(awk -v col="$COL_IDX" -v sep="$SEP" '
    BEGIN{FS=sep} NR>1{ gsub(/"/, "", $col); if($col=="" || $col=="NULL" || $col=="null" || $col=="NA") n++ }
    END{print n+0}
  ' "$FILE")
  echo -e "  ${YELLOW}  → Nulos/vacíos:   $NULLS${NC}"
done

# ============================================================
echo ""
echo -e "${BOLD}${CYAN}============================================================${NC}"
echo -e "${BOLD}${CYAN}  🔤 SECCIÓN 4 — KEYWORDS DE OBSOLESCENCIA EN TÍTULOS${NC}"
echo -e "${BOLD}${CYAN}============================================================${NC}"

# Detectar columna de título automáticamente
TITLE_COL=0
for i in "${!COLS[@]}"; do
  COL_CLEAN=$(echo "${COLS[$i]}" | tr -d '"' | xargs | tr '[:upper:]' '[:lower:]')
  if echo "$COL_CLEAN" | grep -qE "titulo|title|nombre|name|producto|product|descripcion|desc"; then
    TITLE_COL=$((i+1))
    echo -e "  🔍 Columna de título detectada: '${COLS[$i]}' (col $TITLE_COL)"
    break
  fi
done

if [[ $TITLE_COL -gt 0 ]]; then
  echo ""
  echo -e "  ${RED}🔴 Keywords → OBSOLETO:${NC}"
  for KW in "legacy" "old gen" "refurbished" "reacondicionado" "descontinuado" \
            "discontinued" "usado" "segunda mano" "antiguo" "anterior"; do
    CNT=$(awk -v col="$TITLE_COL" -v sep="$SEP" -v kw="$KW" '
      BEGIN{FS=sep; IGNORECASE=1} NR>1{
        gsub(/"/, "", $col)
        if (tolower($col) ~ tolower(kw)) c++
      } END{print c+0}
    ' "$FILE")
    if [[ $CNT -gt 0 ]]; then
      PCT=$(awk "BEGIN{printf \"%.1f\", $CNT*100/$TOTAL_ROWS}")
      echo -e "    '${KW}': ${BOLD}$CNT${NC} productos (${PCT}%)"
    fi
  done

  echo ""
  echo -e "  ${GREEN}🟢 Keywords → VIGENTE/NUEVO:${NC}"
  for KW in "nuevo" "new" "latest" "gen 5" "ddr5" "pcie 5" "rtx 50" "rx 9" \
            "ryzen 9" "core i9" "nvme" "gen5"; do
    CNT=$(awk -v col="$TITLE_COL" -v sep="$SEP" -v kw="$KW" '
      BEGIN{FS=sep; IGNORECASE=1} NR>1{
        gsub(/"/, "", $col)
        if (tolower($col) ~ tolower(kw)) c++
      } END{print c+0}
    ' "$FILE")
    if [[ $CNT -gt 0 ]]; then
      PCT=$(awk "BEGIN{printf \"%.1f\", $CNT*100/$TOTAL_ROWS}")
      echo -e "    '${KW}': ${BOLD}$CNT${NC} productos (${PCT}%)"
    fi
  done
else
  echo -e "  ${YELLOW}⚠️  No se detectó columna de título automáticamente${NC}"
  echo -e "  ${YELLOW}   → Edita TITLE_COL manualmente en el script${NC}"
fi

# ============================================================
echo ""
echo -e "${BOLD}${CYAN}============================================================${NC}"
echo -e "${BOLD}${CYAN}  🔢 SECCIÓN 5 — VALORES ÚNICOS POR COLUMNA (RESUMEN)${NC}"
echo -e "${BOLD}${CYAN}============================================================${NC}"
echo ""

for i in "${!COLS[@]}"; do
  COL_NAME=$(echo "${COLS[$i]}" | tr -d '"' | xargs)
  COL_IDX=$((i+1))

  UNIQUE=$(awk -v col="$COL_IDX" -v sep="$SEP" '
    BEGIN{FS=sep} NR>1{gsub(/"/, "", $col); vals[$col]=1}
    END{print length(vals)}
  ' "$FILE")

  NULLS=$(awk -v col="$COL_IDX" -v sep="$SEP" '
    BEGIN{FS=sep} NR>1{
      gsub(/"/, "", $col)
      if($col=="" || $col=="NULL" || $col=="null" || $col=="NA") n++
    } END{print n+0}
  ' "$FILE")

  # Tipo inferido
  SAMPLE=$(awk -v col="$COL_IDX" -v sep="$SEP" '
    BEGIN{FS=sep} NR==2{gsub(/"/, "", $col); print $col}
  ' "$FILE")

  if echo "$SAMPLE" | grep -qE '^[0-9]+(\.[0-9]+)?$'; then
    DTYPE="numeric"
  elif echo "$SAMPLE" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}'; then
    DTYPE="date"
  else
    DTYPE="text"
  fi

  printf "  %-30s únicos=%-8s nulos=%-6s tipo=%s\n" \
    "${COL_NAME}" "$UNIQUE" "$NULLS" "$DTYPE"
done

# ============================================================
echo ""
echo -e "${BOLD}${CYAN}============================================================${NC}"
echo -e "${BOLD}${CYAN}  📌 SECCIÓN 6 — DIAGNÓSTICO FINAL PE4${NC}"
echo -e "${BOLD}${CYAN}============================================================${NC}"
echo ""

HAS_LABEL=${#LABEL_COLS[@]}
HAS_TITLE=$([[ $TITLE_COL -gt 0 ]] && echo 1 || echo 0)

[[ $HAS_LABEL -gt 0 ]] && \
  echo -e "  ✅ ${GREEN}Etiquetas explícitas:   SÍ (${#LABEL_COLS[@]} columna/s)${NC}" || \
  echo -e "  ❌ ${RED}Etiquetas explícitas:   NO → Necesita etiquetado automático${NC}"

[[ $HAS_TITLE -eq 1 ]] && \
  echo -e "  ✅ ${GREEN}Columna de título:      SÍ (col $TITLE_COL)${NC}" || \
  echo -e "  ❌ ${RED}Columna de título:      NO detectada${NC}"

echo ""
echo -e "  ${BOLD}🎯 Configuración recomendada para BERT:${NC}"
echo -e "     INPUT:   titulo [SEP] categoria [SEP] marca"
echo -e "     TARGET:  etiqueta_obsolescencia"
echo -e "     CLASES:  0=vigente | 1=en_transicion | 2=obsoleto"
echo -e "     MODELO:  dccuchile/bert-base-spanish-wwm-cased"
echo ""
echo -e "${BOLD}${GREEN}============================================================${NC}"
echo -e "${BOLD}${GREEN}  ✅ VERIFICACIÓN PE4 COMPLETADA${NC}"
echo -e "${BOLD}${GREEN}============================================================${NC}"