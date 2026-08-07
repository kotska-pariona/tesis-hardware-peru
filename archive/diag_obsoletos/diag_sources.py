import pathlib as _pl

lines = _pl.Path("agent/pe5_agent.py").read_text(encoding="utf-8").splitlines()

print("=== Constantes LOCAL_SOURCES / IMPORT_SOURCES ===")
for i, l in enumerate(lines, start=1):
    if any(k in l for k in ["LOCAL_SOURCES", "IMPORT_SOURCES", "source_lower", "category_norm"]):
        print(f"  {i:4d} | {l}")

print("\n=== Líneas 560-620 (contexto _load_data) ===")
for i, l in enumerate(lines[555:625], start=556):
    print(f"  {i:4d} | {l}")
