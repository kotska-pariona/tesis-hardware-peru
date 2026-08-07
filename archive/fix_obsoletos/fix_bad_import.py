import pathlib

p = pathlib.Path("agent/pe5_agent.py")
src = p.read_text(encoding="utf-8")

# Eliminar la linea invalida del primer script
BAD = "    import pandas as pd as _pd\n    df = _pd.DataFrame(records)\n"
GOOD = ""

if BAD in src:
    src = src.replace(BAD, GOOD, 1)
    print("  OK  linea invalida eliminada")
else:
    print("  WARN  linea no encontrada, buscando variantes...")
    for i, line in enumerate(src.splitlines(), 1):
        if "import pandas as pd as" in line or "_pd.DataFrame" in line:
            print(f"  {i:4d} | {repr(line)}")

p.write_text(src, encoding="utf-8")
print("  OK  guardado")
