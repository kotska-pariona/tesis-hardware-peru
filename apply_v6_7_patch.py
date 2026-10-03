#!/usr/bin/env python3
# =============================================================================
# apply_v6_7_patch.py — Aplica el patch v6.7 sobre dashboard_v5_main.py
# Uso: python apply_v6_7_patch.py
# =============================================================================

import re, shutil
from pathlib import Path
from datetime import datetime

SRC  = Path("dashboard_v5_main.py")
DEST = Path("dashboard_v5_main.py")
BAK  = Path(f"archive/bak_dashboard_v6_7_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py")

if not SRC.exists():
    print("❌ No se encontró dashboard_v5_main.py")
    exit(1)

# Backup
BAK.parent.mkdir(exist_ok=True)
shutil.copy(SRC, BAK)
print(f"✅ Backup: {BAK}")

code = SRC.read_text(encoding="utf-8")

# ── [1] Versión en sidebar ────────────────────────────────────────────────────
code = code.replace(
    '"v6.0 · Dropshipping Hardware"',
    '"v6.7 · Dropshipping Hardware"'
)
code = code.replace(
    '"v6.1 · Dropshipping Hardware"',
    '"v6.7 · Dropshipping Hardware"'
)
print("✅ [1] Versión sidebar → v6.7")

# ── [2] APP_CONFIG title ──────────────────────────────────────────────────────
code = re.sub(
    r'"title":\s*"HDS-ROI v[0-9.]+?"',
    '"title": "HDS-ROI v6.7"',
    code
)
print("✅ [2] APP_CONFIG title → HDS-ROI v6.7")

# ── [3] Badge DEFENSA ─────────────────────────────────────────────────────────
code = code.replace(
    '"DEFENSA LISTA ✓"',
    '"DEFENSA LISTA ✓ · v6.7"'
)
print("✅ [3] Badge DEFENSA → v6.7")

# ── [4] Agregar ruta /oe5 en display_page ────────────────────────────────────
OLD_ROUTE = '    elif pathname == "/pareto":\n        return page_pareto()'
NEW_ROUTE = (
    '    elif pathname == "/oe5":\n        return page_oe5()\n'
    '    elif pathname == "/pareto":\n        return page_pareto()'
)
if OLD_ROUTE in code:
    code = code.replace(OLD_ROUTE, NEW_ROUTE)
    print("✅ [4] Ruta /oe5 agregada en display_page()")
else:
    print("⚠️  [4] Ruta /oe5 — patrón no encontrado, agregar manualmente")

# ── [5] Agregar nav_link OE5 en sidebar ──────────────────────────────────────
OLD_NAV = '        nav_link("📐 Pareto Original",     "/pareto",         ICONS["chart"]),'
NEW_NAV = (
    '        nav_link("⚙️  NSGA-III OE5",       "/oe5",            "⚙️"),\n'
    '        nav_link("📐 Pareto Original",     "/pareto",         ICONS["chart"]),'
)
if OLD_NAV in code:
    code = code.replace(OLD_NAV, NEW_NAV)
    print("✅ [5] Nav link OE5 agregado en sidebar")
else:
    print("⚠️  [5] Nav link OE5 — patrón no encontrado, agregar manualmente")

# ── [6] Agregar HV KPI en home banner ────────────────────────────────────────
OLD_KPI = (
    "        dbc.Col(dbc.Card([dbc.CardBody([\n"
    "            html.P(\"SKUs Obsoletos\","
)
NEW_KPI = (
    "        dbc.Col(dbc.Card([dbc.CardBody([\n"
    "            html.P(\"HV Pareto OE5\", className=\"mb-1\",\n"
    "                   style={\"color\": COLORS[\"text_dim\"], \"fontSize\": \"0.7rem\",\n"
    "                          \"textTransform\": \"uppercase\", \"fontWeight\": 600}),\n"
    "            html.H3(\"0.9031\", className=\"mb-0\",\n"
    "                    style={\"color\": COLORS[\"green\"], \"fontWeight\": 800}),\n"
    "            html.Small(\"≥ 0.85 meta ✅ · SCPO\",\n"
    "                       style={\"color\": COLORS[\"text_dim\"]}),\n"
    "        ], style={\"textAlign\": \"center\", \"padding\": \"14px\"})],\n"
    "        style={\"background\": COLORS[\"bg\"],\n"
    "               \"border\": f\"2px solid {COLORS['green']}\",\n"
    "               \"borderRadius\": \"10px\"}), md=3),\n\n"
    "        dbc.Col(dbc.Card([dbc.CardBody([\n"
    "            html.P(\"SKUs Obsoletos\","
)
if OLD_KPI in code:
    code = code.replace(OLD_KPI, NEW_KPI, 1)
    print("✅ [6] KPI HV=0.9031 agregado en home banner")
else:
    print("⚠️  [6] KPI HV — patrón no encontrado, agregar manualmente")

# ── [7] Actualizar print de inicio ───────────────────────────────────────────
code = code.replace(
    '"  🚀 HDS-ROI v6.0 — Motor de Decisión Inteligente"',
    '"  🚀 HDS-ROI v6.7 — Motor de Decisión Inteligente"'
)
code = re.sub(
    r'"  📈 Páginas: \d+"',
    '"  📈 Páginas: 15"'
)
print("✅ [7] Print de inicio → v6.7")

# ── Escribir archivo modificado ───────────────────────────────────────────────
DEST.write_text(code, encoding="utf-8")
print(f"\n✅ dashboard_v5_main.py actualizado a v6.7")
print("   Ahora agrega manualmente las funciones page_ablacion() y page_oe5()")
print("   desde dashboard_v6_7_patch.py (reemplaza las existentes)")
print("\n   Para ejecutar:")
print("   python dashboard_v5_main.py")
