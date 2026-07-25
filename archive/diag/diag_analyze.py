import pathlib as _pl
lines = _pl.Path("agent/pe5_agent.py").read_text(encoding="utf-8").splitlines()
for i, l in enumerate(lines[635:670], start=636):
    print(f"{i:4d} | {l}")
