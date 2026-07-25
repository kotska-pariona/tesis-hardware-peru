import pathlib as _pl
lines = _pl.Path("agent/pe5_agent.py").read_text(encoding="utf-8").splitlines()

print("=== __init__ del agente ===")
in_init = False
for i, l in enumerate(lines, start=1):
    if "def __init__" in l:
        in_init = True
    if in_init:
        print(f"{i:4d} | {l}")
    if in_init and i > 10 and l.strip() == "":
        # parar después de 40 líneas del init
        pass
    if in_init and "def " in l and "__init__" not in l:
        break
