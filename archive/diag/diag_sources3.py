import pathlib as _pl

# Ver las primeras 80 líneas de pe5_agent.py (imports)
lines = _pl.Path("agent/pe5_agent.py").read_text(encoding="utf-8").splitlines()
print("=== Imports (líneas 1-80) ===")
for i, l in enumerate(lines[:80], start=1):
    print(f"  {i:4d} | {l}")

# Buscar LOCAL_SOURCES en TODOS los archivos del proyecto recursivamente
print("\n=== Búsqueda global LOCAL_SOURCES en todo el proyecto ===")
for f in _pl.Path(".").rglob("*.py"):
    try:
        text = f.read_text(encoding="utf-8")
        if "LOCAL_SOURCES" in text and "=" in text:
            flines = text.splitlines()
            for i, l in enumerate(flines, start=1):
                if "LOCAL_SOURCES" in l and ("=" in l or "[" in l):
                    print(f"  {f}:{i:4d} | {l}")
    except:
        pass
