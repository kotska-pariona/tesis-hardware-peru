name: Agente Tesis - Batch 24h

on:
  workflow_dispatch:
    inputs:
      pages:
        description: 'Paginas por categoria (default: 3 para CI)'
        required: false
        default: '3'
  schedule:
    - cron: '0 7 * * *'   # 02:00 Lima (UTC-5)

permissions:
  contents: write

jobs:
  scraping_batch:
    runs-on: ubuntu-latest
    timeout-minutes: 90

    steps:
      # ── 1. Checkout ──────────────────────────────────────────────────
      - name: Checkout repositorio
        uses: actions/checkout@v4
        with:
          fetch-depth: 0
          token: ${{ secrets.GITHUB_TOKEN }}

      # ── 2. Python ────────────────────────────────────────────────────
      - name: Configurar Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      # ── 3. Dependencias ──────────────────────────────────────────────
      - name: Instalar dependencias
        run: |
          python -m pip install --upgrade pip
          pip install requests beautifulsoup4 lxml fake-useragent pandas schedule

      # ── 4. Test de configuracion ─────────────────────────────────────
      - name: Verificar configuracion
        run: python agent/main.py --test

      # ── 5. Ejecutar scraping ─────────────────────────────────────────
      - name: Ejecutar batch de scraping
        run: |
          PAGES=${{ github.event.inputs.pages || '3' }}
          echo "Ejecutando con PAGES=$PAGES"
          python agent/main.py --batch --pages $PAGES
        env:
          PYTHONUNBUFFERED: "1"

      # ── 6. Verificar datos generados ─────────────────────────────────
      - name: Verificar CSV generado
        run: |
          if [ -f "data/raw/MASTER_hardware_peru.csv" ]; then
            echo "✅ Master CSV encontrado"
            wc -l data/raw/MASTER_hardware_peru.csv
            head -2 data/raw/MASTER_hardware_peru.csv
          else
            echo "⚠️  Master CSV no encontrado — verificar logs"
          fi
          ls -la data/raw/ || echo "Directorio data/raw vacio"

      # ── 7. Commit y push de datos ────────────────────────────────────
      - name: Commit datos al repositorio
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/raw/ logs/ || true
          if git diff --staged --quiet; then
            echo "Sin cambios nuevos para commitear"
          else
            TIMESTAMP=$(date -u '+%Y-%m-%d %H:%M UTC')
            git commit -m "data: batch automatico $TIMESTAMP [skip ci]"
            git push
            echo "✅ Datos pusheados exitosamente"
          fi

      # ── 8. Resumen final ─────────────────────────────────────────────
      - name: Mostrar estadisticas finales
        if: always()
        run: |
          python agent/main.py --stats || echo "Stats no disponibles"
