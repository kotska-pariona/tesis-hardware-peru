import pathlib

p = pathlib.Path("agent/pe5_agent.py")
lines = p.read_text(encoding="utf-8").splitlines()

# Mostrar contexto alrededor de línea 765
print("=== Contexto líneas 758-770 ===")
for i, line in enumerate(lines[757:770], start=758):
    print(f"{i:4d} | {repr(line)}")
