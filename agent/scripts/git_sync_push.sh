#!/bin/bash
###############################################################################
# git_sync_push.sh  v1.0
# ══════════════════════
# Reemplaza el bloque de sincronización git del workflow.
#
# FIX CRÍTICO: El orden anterior era:
#   1. git pull --rebase   ← fallaba porque el índice tenía cambios sin commit
#   2. (nunca se llegaba a commitear/pushear)
#
# Orden correcto:
#   1. git add -A + commit  → working dir queda limpio
#   2. git pull --rebase    → aplica el commit local sobre lo último del remoto
#   3. git push             → con reintentos si hay carrera con otro workflow
#
# Uso en el workflow (reemplaza el step de "Commit & Push"):
#   - name: Commit & Push MASTER
#     run: bash agent/scripts/git_sync_push.sh
#     env:
#       BATCH_ID: ${{ env.BATCH_ID }}
###############################################################################

set -uo pipefail  # NO usamos -e: queremos controlar los fallos manualmente

BRANCH="${GITHUB_REF_NAME:-main}"
BATCH_ID="${BATCH_ID:-manual_$(date +%Y%m%d_%H%M%S)}"
MAX_RETRIES=3

echo "════════════════════════════════════════════════"
echo "  Git Sync & Push — batch=${BATCH_ID}"
echo "════════════════════════════════════════════════"

git config user.name  "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

# ── [FIX] Paso 1: COMMIT PRIMERO — deja el índice limpio ────────────────
echo ""
echo "[1/3] Preparando commit local..."
git add -A

if git diff --cached --quiet; then
    echo "  ℹ️  Sin cambios para commitear (¿scrapers no generaron datos?)"
    COMMIT_CREADO=false
else
    N_FILES=$(git diff --cached --name-only | wc -l)
    git commit -m "🤖 Auto-update batch ${BATCH_ID} (${N_FILES} archivos)" \
        --author="github-actions[bot] <github-actions[bot]@users.noreply.github.com>"
    echo "  ✅ Commit creado: ${N_FILES} archivos"
    COMMIT_CREADO=true
fi

# ── Paso 2: PULL --REBASE — ahora sí, con índice limpio ──────────────────
echo ""
echo "[2/3] Sincronizando con remoto (rebase)..."
REBASE_OK=false

for i in $(seq 1 "$MAX_RETRIES"); do
    if git pull --rebase origin "$BRANCH" 2>&1; then
        echo "  ✅ Rebase exitoso (intento $i)"
        REBASE_OK=true
        break
    else
        echo "  ⚠️  Rebase falló (intento $i/$MAX_RETRIES) — abortando y reintentando"
        git rebase --abort 2>/dev/null || true
        sleep $((i * 5))
    fi
done

if [ "$REBASE_OK" = false ]; then
    echo "  ❌ No se pudo hacer rebase tras ${MAX_RETRIES} intentos"
    echo "  💾 Los cambios quedan commiteados LOCALMENTE (no se pierden en este job)"
    echo "  ⚠️  Requiere intervención manual: revisar conflictos en ${BRANCH}"
    exit 1
fi

# ── Paso 3: PUSH — con reintentos por posibles carreras ─────────────────
if [ "$COMMIT_CREADO" = true ]; then
    echo ""
    echo "[3/3] Pusheando a origin/${BRANCH}..."
    PUSH_OK=false

    for i in $(seq 1 "$MAX_RETRIES"); do
        if git push origin "$BRANCH" 2>&1; then
            echo "  ✅ Push exitoso (intento $i)"
            PUSH_OK=true
            break
        else
            echo "  ⚠️  Push falló (intento $i/$MAX_RETRIES) — re-sincronizando"
            git pull --rebase origin "$BRANCH" || true
            sleep $((i * 5))
        fi
    done

    if [ "$PUSH_OK" = false ]; then
        echo "  ❌ Push falló tras ${MAX_RETRIES} intentos"
        exit 1
    fi
else
    echo ""
    echo "[3/3] Sin commit nuevo — nada que pushear"
fi

echo ""
echo "════════════════════════════════════════════════"
echo "  ✅ Git sync completado — MASTER sincronizado"
echo "════════════════════════════════════════════════"
