import pathlib

p = pathlib.Path("agent/pe5_agent.py")
lines = p.read_text(encoding="utf-8").splitlines()

# Mostrar más contexto para entender la estructura
print("=== Contexto líneas 750-780 ===")
for i, line in enumerate(lines[749:780], start=750):
    print(f"{i:4d} | {repr(line)}")
