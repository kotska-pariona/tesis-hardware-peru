import pathlib as _pl
lines = _pl.Path("agent/pe5_agent.py").read_text(encoding="utf-8").splitlines()

print("=== main() completo ===")
in_main = False
for i, l in enumerate(lines, start=1):
    if "def main(" in l or (not in_main and "if __name__" in l):
        in_main = True
    if in_main:
        print(f"{i:4d} | {l}")
