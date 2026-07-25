import pathlib as _pl

p = _pl.Path("agent/pe5_agent.py")
src = p.read_text(encoding="utf-8")
original_len = len(src)
results = []

# ── FIX-9: pasar category a PricingAgent ─────────────────────────────────
OLD9 = "    agent = PricingAgent(master_csv=args.master)\n    df    = agent.run()"
NEW9 = "    agent = PricingAgent(master_csv=args.master, category=args.category or \"\")\n    df    = agent.run()"

if OLD9 in src:
    src = src.replace(OLD9, NEW9, 1)
    results.append("OK  FIX-9: category pasado a PricingAgent")
else:
    results.append("!!  FIX-9: patron no encontrado")

# ── FIX-10: eliminar bloque allocate_budget duplicado ────────────────────
OLD10 = (
    "\n    # -- Asignacion de presupuesto --\n"
    "    budget = get_budget(args.budget)\n"
    "    log.info(f'[BUDGET] Presupuesto total: S/. {budget:,.2f}')\n"
    "    records = df.to_dict('records')\n"
    "    records = allocate_budget(records, budget)\n"
)
if OLD10 in src:
    src = src.replace(OLD10, "", 1)
    results.append("OK  FIX-10: bloque allocate_budget duplicado eliminado")
else:
    results.append("!!  FIX-10: duplicado no encontrado (puede ya estar limpio)")

# ── FIX-11: eliminar filtro post-run redundante (ya filtra run()) ─────────
OLD11 = (
    "    # Mostrar top N\n"
    "    filter_df = df\n"
    "    if args.category:\n"
    "        filter_df = df[\n"
    "            df[\"category\"].str.upper() == args.category.upper()\n"
    "        ]\n"
    "\n"
    "    print(f\"\\n{'═'*70}\")\n"
    "    print(f\"  TOP {args.top} DECISIONES PE5 v{VERSION}\")\n"
    "    print(f\"{'═'*70}\")\n"
    "    top = filter_df.head(args.top)"
)
NEW11 = (
    "    # Mostrar top N\n"
    "    print(f\"\\n{'═'*70}\")\n"
    "    print(f\"  TOP {args.top} DECISIONES PE5 v{VERSION}\")\n"
    "    print(f\"{'═'*70}\")\n"
    "    top = df.head(args.top)"
)

if OLD11 in src:
    src = src.replace(OLD11, NEW11, 1)
    results.append("OK  FIX-11: filtro post-run redundante eliminado")
else:
    results.append("!!  FIX-11: patron no encontrado")

p.write_text(src, encoding="utf-8")
print(f"\n  Archivo: {p} ({original_len} -> {len(src)} chars)")
for r in results:
    print(f"  {r}")
