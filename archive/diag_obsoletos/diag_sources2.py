import pathlib as _pl

# Buscar en todos los .py del proyecto
for f in _pl.Path("agent").rglob("*.py"):
    lines = f.read_text(encoding="utf-8").splitlines()
    for i, l in enumerate(lines, start=1):
        if "LOCAL_SOURCES" in l or "IMPORT_SOURCES" in l:
            print(f"  {f}:{i:4d} | {l}")

print("\n=== También buscar en raíz ===")
for f in _pl.Path(".").glob("*.py"):
    lines = f.read_text(encoding="utf-8").splitlines()
    for i, l in enumerate(lines, start=1):
        if "LOCAL_SOURCES" in l or "IMPORT_SOURCES" in l:
            print(f"  {f}:{i:4d} | {l}")
