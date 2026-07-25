import pathlib as _pl

p = _pl.Path("agent/pe5_agent.py")
src = p.read_text(encoding="utf-8")
original_len = len(src)
results = []

# ── FIX-7a: agregar self.category al __init__ ─────────────────────────────
OLD0 = (
    "    def __init__(self, master_csv: Path = MASTER_CSV):\n"
    "        self.master_csv = master_csv\n"
    "        self.df_master  = pd.DataFrame()\n"
    "        self.df_local   = pd.DataFrame()\n"
    "        self.df_import  = pd.DataFrame()\n"
    "        self.results    = []\n"
    "        self._obs_pipe  = None   # [FIX-1] pipeline PE4 precargado"
)
NEW0 = (
    "    def __init__(self, master_csv: Path = MASTER_CSV, category: str = \"\"):\n"
    "        self.master_csv = master_csv\n"
    "        self.category   = category  # [FIX-7] filtro de categoría\n"
    "        self.df_master  = pd.DataFrame()\n"
    "        self.df_local   = pd.DataFrame()\n"
    "        self.df_import  = pd.DataFrame()\n"
    "        self.results    = []\n"
    "        self._obs_pipe  = None   # [FIX-1] pipeline PE4 precargado"
)

if OLD0 in src:
    src = src.replace(OLD0, NEW0, 1)
    results.append("OK  FIX-7a: self.category agregado al __init__")
else:
    results.append("!!  FIX-7a: patron __init__ no encontrado")

# ── FIX-7b: filtro --category en run() ───────────────────────────────────
OLD1 = (
    "        categories = [\n"
    "            c for c in self.df_master[\"category_norm\"].unique()\n"
    "            if c != \"OTHER\"\n"
    "        ]\n"
    "        log.info(f\"  Categorías a analizar: {len(categories)}\")"
)
NEW1 = (
    "        all_cats = [\n"
    "            c for c in self.df_master[\"category_norm\"].unique()\n"
    "            if c != \"OTHER\"\n"
    "        ]\n"
    "        # [FIX-7b] Respetar --category si se especificó\n"
    "        if self.category:\n"
    "            requested = [c.strip().upper() for c in self.category.split(\",\")]\n"
    "            categories = [c for c in all_cats if c.upper() in requested]\n"
    "            if not categories:\n"
    "                log.warning(\n"
    "                    f\"  Categoria '{self.category}' no encontrada. \"\n"
    "                    f\"Disponibles: {sorted(all_cats)}\"\n"
    "                )\n"
    "                return pd.DataFrame()\n"
    "        else:\n"
    "            categories = all_cats\n"
    "        log.info(f\"  Categorías a analizar: {len(categories)}\")"
)

if OLD1 in src:
    src = src.replace(OLD1, NEW1, 1)
    results.append("OK  FIX-7b: filtro --category en run()")
else:
    results.append("!!  FIX-7b: patron run() no encontrado")

# ── FIX-8: MAX_ROWS=15_000 en _analyze_category() ────────────────────────
OLD2 = (
    "        local_cat  = self.df_local[\n"
    "            self.df_local[\"category_norm\"] == category\n"
    "        ].copy()\n"
    "        import_cat = self.df_import[\n"
    "            self.df_import[\"category_norm\"] == category\n"
    "        ].copy()"
)
NEW2 = (
    "        MAX_ROWS = 15_000  # [FIX-8] evitar OOM en categorias grandes\n"
    "        local_cat  = self.df_local[\n"
    "            self.df_local[\"category_norm\"] == category\n"
    "        ].head(MAX_ROWS).copy()\n"
    "        import_cat = self.df_import[\n"
    "            self.df_import[\"category_norm\"] == category\n"
    "        ].head(MAX_ROWS).copy()"
)

if OLD2 in src:
    src = src.replace(OLD2, NEW2, 1)
    results.append("OK  FIX-8: MAX_ROWS=15000 en _analyze_category()")
else:
    results.append("!!  FIX-8: patron _analyze_category no encontrado")

# ── FIX-9: pasar category al instanciar el agente en main() ──────────────
# Buscar donde se instancia el agente (PE5Agent() o similar)
import re
# Patrón: agent = PE5Agent() o similar
m = re.search(r'(\w+)\s*=\s*PE5Agent\(([^)]*)\)', src)
if m:
    old_inst = m.group(0)
    agent_var = m.group(1)
    old_args  = m.group(2).strip()
    if "category" not in old_inst:
        if old_args:
            new_inst = f"{agent_var} = PE5Agent({old_args}, category=args.category or \"\")"
        else:
            new_inst = f"{agent_var} = PE5Agent(category=args.category or \"\")"
        src = src.replace(old_inst, new_inst, 1)
        results.append(f"OK  FIX-9: category pasado al instanciar PE5Agent")
    else:
        results.append("OK  FIX-9: category ya estaba en la instanciación")
else:
    results.append("!!  FIX-9: no se encontró PE5Agent() en main()")

p.write_text(src, encoding="utf-8")

print(f"\n  Archivo: {p} ({original_len} -> {len(src)} chars)")
for r in results:
    print(f"  {r}")
