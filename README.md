# HDS-ROI v6.0 — Sistema Híbrido ML + Computación Evolutiva
## Optimización de ROI en Dropshipping de Hardware — Perú

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://python.org)
[![DVC](https://img.shields.io/badge/DVC-3.67-purple)](https://dvc.org)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

**Autor:** Kotska Rony Pariona Martinez | UNI-FIIS  
**Grado:** Maestro en Ciencias — Inteligencia Artificial  
**Repo:** https://github.com/kotska-pariona/tesis-hardware-peru

---

## Estado del Sistema (02/10/2026)

| OE | Componente | Resultado | Estado |
|---|---|---|---|
| OE1 | Pipeline ETL | 336K+ reg, 9 fuentes, 97 ejecuciones | ✅ |
| OE2 | LightGBM predicción | MAPE 0.64%, R²=0.9968 | ✅ |
| OE3 | Competitividad CP | MAPE 0.91%, DA 92.9% | ✅ |
| OE4 | E5-large obsolescencia | F1-Macro 0.9966 | ✅ |
| OE5 | NSGA-III base | 75 soluciones Pareto | ✅ |
| OE6 | Mondrian CP | Cobertura 95.97% | ✅ |
| OE7 | Dashboard Plotly | 9 páginas, puerto 8050 | ✅ |
| OE8 | Evaluación SUS | Pendiente octubre 2026 | ⚠️ |
| OE9 | NSGA-III + SCPO | ROI máx. 93.88%, 46 Pareto | ✅ |
| OE10 | Portafolios ROI | +43% / +68% / +94% | ✅ |

## Modelos en HuggingFace

| Modelo | HuggingFace | Métrica |
|---|---|---|
| E5-large fine-tuned | [kotska-pariona/pe4-e5-obsolescence](https://huggingface.co/kotska-pariona/pe4-e5-obsolescence) | F1=0.9966 |

## Reproducibilidad

\`\`\`bash
git clone https://github.com/kotska-pariona/tesis-hardware-peru
dvc pull
dvc repro
python dashboard/app.py
\`\`\`
