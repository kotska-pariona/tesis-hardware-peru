# 📚 Documentación del Proyecto HDS-ROI v6.2

**Sistema Híbrido ML + CE para Dropshipping de Hardware**

**Autor:** Kotska Rony Pariona Martinez | UNI-FIIS
**Fecha:** 12 Nov 2026

---

## 📊 Resumen Ejecutivo

- **Total archivos:** 109
- **Tamaño total:** 1.5 MB
- **Líneas de código:** 36,878

## 📁 Estructura del Proyecto

### agent/

**3 archivos** | **85.2 KB** | **2,206 líneas**

| Archivo | Tamaño | Líneas | Descripción |
|---------|--------|--------|-------------|
| `pe5_agent.py` | 42.7 KB | 1105 | !/usr/bin/env python3 |
| `main.py` | 37.6 KB | 939 | !/usr/bin/env python3 |
| `scraper_competencia.py` | 4.9 KB | 162 |  |

### scripts/

**52 archivos** | **575.2 KB** | **13,884 líneas**

| Archivo | Tamaño | Líneas | Descripción |
|---------|--------|--------|-------------|
| `pe2_multihorizonte.py` | 40.4 KB | 909 | ============================================================================= |
| `oe5_nsga3.py` | 30.5 KB | 738 |  |
| `pe3b_matching.py` | 29.7 KB | 638 |  |
| `oe4c_sensitivity.py` | 28.8 KB | 670 |  |
| `pe3_competitividad.py` | 28.2 KB | 623 |  |
| `oe4b_optimizer.py` | 27.8 KB | 610 |  |
| `pe2_clean_and_train.py` | 22.8 KB | 528 |  |
| `pe3c_costo_real.py` | 22.6 KB | 514 |  |
| `pe2_eval_fix.py` | 22.0 KB | 504 |  |
| `oe9_nsga3_llm.py` | 21.4 KB | 565 |  |
| `oe9_nsga3.py` | 21.2 KB | 559 | ============================================================================= |
| `evaluate_models.py` | 18.6 KB | 417 |  |
| `optimize_portfolio_simple.py` | 17.4 KB | 468 | !/usr/bin/env python3 |
| `pe2_train_tft.py` | 17.3 KB | 410 |  |
| `pe2_lgbm.py` | 16.9 KB | 397 |  |
| `pe2_debug_tft.py` | 14.6 KB | 328 |  |
| `pe4_train_e5.py` | 14.3 KB | 332 | -*- coding: utf-8 -*- |
| `scraper_internacional.py` | 13.9 KB | 330 |  |
| `train_pe2_v5.py` | 13.7 KB | 354 |  |
| `normalize_brand_model_v4.py` | 13.5 KB | 395 |  |
| `normalizar_master.py` | 13.0 KB | 286 | ============================================================================= |
| `oe4a_roi_calculator.py` | 12.5 KB | 299 |  |
| `oe4_corpus_builder.py` | 12.0 KB | 297 |  |
| `oe4_corpus_builder_v4.py` | 11.9 KB | 292 |  |
| `oe4_e5large.py` | 7.9 KB | 197 |  |
| `oe4_classifier_v2.py` | 7.6 KB | 191 |  |
| `pe4_build_dataset.py` | 7.6 KB | 181 |  |
| `pe4_train_bert.py` | 7.5 KB | 186 |  |
| `pe2_diag_history.py` | 5.9 KB | 136 |  |
| `audit_all_results.py` | 5.0 KB | 151 |  |
| `audit_oe9_rj_port_definition_D.py` | 4.9 KB | 122 |  |
| `audit_roi_precios_integridad.py` | 4.2 KB | 94 |  |
| `consolidar_master.py` | 3.8 KB | 101 | scripts/consolidar_master.py |
| `audit_oe9_objective_smoke.py` | 3.7 KB | 106 | Carga matriz |
| `oe4_infer_rj.py` | 3.6 KB | 87 |  |
| `audit_nsga3_convergence.py` | 3.3 KB | 86 |  |
| `oe4_e5_embedder_v2.py` | 3.0 KB | 86 |  |
| `audit_oe9_rj_category_impact_c.py` | 2.5 KB | 76 |  |
| `audit_oe9_category_impact_c.py` | 2.3 KB | 74 |  |
| `audit_oe9_rj_definition_audit.py` | 2.3 KB | 65 | parse r_j |
| `audit_oe9_financial_consistency.py` | 2.2 KB | 69 |  |
| `audit_oe9_portfolio_roi_smoke.py` | 2.0 KB | 68 |  |
| `audit_oe9_factibility.py` | 1.9 KB | 54 | rj_max viene del resumen |
| `audit_oe9_rj_distribution.py` | 1.5 KB | 43 |  |
| `audit_all_results_fields_v2.py` | 1.4 KB | 53 |  |
| `audit_oe9_rj_sensitivity_b.py` | 1.3 KB | 40 |  |
| `audit_all_json_rjmax_G.py` | 1.0 KB | 40 |  |
| `add_advanced_features.py` | 0.9 KB | 26 | Cargar datos |
| `audit_oe9_full_diagnostic.py` | 0.8 KB | 25 |  |
| `audit_oe9_matrix_basic.py` | 0.8 KB | 25 |  |
| `audit_precios.py` | 0.8 KB | 23 | Cargar la matriz |
| `audit_oe9_thresholds_F.py` | 0.5 KB | 16 |  |

### scrapers/

**1 archivos** | **7.5 KB** | **225 líneas**

| Archivo | Tamaño | Líneas | Descripción |
|---------|--------|--------|-------------|
| `ripley_pe_scraper.py` | 7.5 KB | 225 | !/usr/bin/env python3 |

### pages/

**15 archivos** | **166.0 KB** | **4,334 líneas**

| Archivo | Tamaño | Líneas | Descripción |
|---------|--------|--------|-------------|
| `page_prediccion_demanda.py` | 34.4 KB | 771 | pages/page_prediccion_demanda.py |
| `page_obsolescencia.py` | 28.6 KB | 632 | pages/page_obsolescencia.py |
| `page_comparativa.py` | 24.6 KB | 538 | pages/page_comparativa.py |
| `motor_decision.py` | 10.8 KB | 328 | pages/motor_decision.py - Motor de Decisión (Página Principal) |
| `arbitraje_roi.py` | 10.5 KB | 251 | pages/arbitraje_roi.py |
| `decision_final.py` | 9.1 KB | 277 | pages/decision_final.py - Página de Decisión Final y Recomendaciones |
| `components_sidebar.py` | 9.0 KB | 238 | components_sidebar.py - Componente de Barra Lateral |
| `analisis_riesgo.py` | 8.2 KB | 243 | pages/analisis_riesgo.py - Análisis de Riesgo y Obsolescencia |
| `simulador_compra.py` | 8.1 KB | 271 | pages/simulador_compra.py - Simulador de Compra con Presupuesto |
| `oe9_comparativa.py` | 5.5 KB | 208 | pages/oe9_comparativa.py - Comparativa OE9 (24 Soluciones Pareto) |
| `page_optimizer.py` | 5.5 KB | 138 |  |
| `datos_reporte.py` | 4.3 KB | 167 | pages/datos_reporte.py - Reporte de Datos de Scraping y Entrenamiento |
| `analisis_modelos.py` | 4.2 KB | 152 | pages/analisis_modelos.py - Análisis de Modelos Individuales |
| `app.py` | 3.2 KB | 120 | app.py - Aplicación Principal Dash v6.0 |
| `__init__.py` | 0.0 KB | 0 |  |

### Raíz/

**38 archivos** | **731.8 KB** | **16,229 líneas**

| Archivo | Tamaño | Líneas | Descripción |
|---------|--------|--------|-------------|
| `dashboard_v6_2_pe2v52.py` | 158.2 KB | 3230 | ============================================================================= |
| `setup_dashboard.sh` | 42.2 KB | 803 | !/usr/bin/env bash |
| `diag_asesor_v6.sh` | 39.1 KB | 839 | !/usr/bin/env bash |
| `diag_maestro_v4.sh` | 38.9 KB | 754 | !/usr/bin/env bash |
| `diagnostico_hipotesis_d.sh` | 36.9 KB | 854 | !/usr/bin/env bash |
| `dashboard.py` | 36.8 KB | 847 | ============================================================================= |
| `diag_maestro_v5.sh` | 34.2 KB | 726 | !/usr/bin/env bash |
| `dashboard_v6_7_patch.py` | 31.1 KB | 602 | ============================================================================= |
| `diag_maestro_v3.sh` | 27.3 KB | 581 | !/usr/bin/env bash |
| `feature_integrator.py` | 27.1 KB | 614 | ============================================================================= |
| `dashboard_data.py` | 23.6 KB | 565 | ============================================================================= |
| `corpus_builder.py` | 21.2 KB | 493 | ============================================================================= |
| `classifier.py` | 20.8 KB | 496 | ============================================================================= |
| `pe4_pipeline.sh` | 18.0 KB | 436 | !/usr/bin/env bash |
| `obsolescencia_scorer.py` | 17.4 KB | 425 | ============================================================================= |
| `fix_bugs_criticos.py` | 16.1 KB | 290 |  |
| `train_pe2_v52.py` | 12.8 KB | 336 | -*- coding: utf-8 -*- |
| `e5_embedder.py` | 12.5 KB | 284 | ============================================================================= |
| `generar_inventario.sh` | 11.5 KB | 177 | ═══════════════════════════════════════════════════════════════════════════ |
| `dashboard_config.py` | 9.3 KB | 301 | ============================================================================= |
| `pe2_v52_patch.py` | 8.7 KB | 201 | ============================================================================= |
| `dashboard_fixed.py` | 8.6 KB | 237 |  |
| `fix_page_sensibilidad.py` | 8.3 KB | 198 |  |
| `fix_montecarlo_real.py` | 7.5 KB | 182 |  |
| `make_processed_v2.py` | 7.4 KB | 160 | make_processed_v2.py |
| `components_v6.py` | 6.9 KB | 177 | components_v6.py - Componentes Reutilizables para Dashboard v6.0 |
| `scraper_newegg.py` | 6.4 KB | 198 | !/usr/bin/env python3 |
| `diagnostico_dataset.py` | 5.8 KB | 134 |  |
| `migrate_master.py` | 5.7 KB | 159 | !/usr/bin/env python3 |
| `pipeline.py` | 5.5 KB | 140 |  |
| `apply_v6_7_patch.py` | 5.3 KB | 120 | !/usr/bin/env python3 |
| `config_v6.py` | 5.3 KB | 210 | config_v6.py - Configuración centralizada Dashboard v6.0 |
| `utils_v6.py` | 5.2 KB | 159 | utils_v6.py - Utilidades para Dashboard v6.0 |
| `predictor_modelo_v2.py` | 4.6 KB | 120 |  |
| `sync_and_fix.sh` | 4.1 KB | 117 | !/usr/bin/env bash |
| `dvc.yaml` | 1.1 KB | 46 |  |
| `params.yaml` | 0.3 KB | 14 |  |
| `run_dashboard.sh` | 0.1 KB | 4 | !/bin/bash |

## 🏆 Archivos Destacados

### Top 5 Más Grandes

| Archivo | Carpeta | Tamaño | Líneas |
|---------|---------|--------|--------|
| `dashboard_v6_2_pe2v52.py` | . | 158.2 KB | 3230 |
| `pe5_agent.py` | agent | 42.7 KB | 1105 |
| `setup_dashboard.sh` | . | 42.2 KB | 803 |
| `pe2_multihorizonte.py` | scripts | 40.4 KB | 909 |
| `diag_asesor_v6.sh` | . | 39.1 KB | 839 |

### Top 5 Más Largos

| Archivo | Carpeta | Líneas | Tamaño |
|---------|---------|--------|--------|
| `dashboard_v6_2_pe2v52.py` | . | 3230 | 158.2 KB |
| `pe5_agent.py` | agent | 1105 | 42.7 KB |
| `main.py` | agent | 939 | 37.6 KB |
| `pe2_multihorizonte.py` | scripts | 909 | 40.4 KB |
| `diagnostico_hipotesis_d.sh` | . | 854 | 36.9 KB |
