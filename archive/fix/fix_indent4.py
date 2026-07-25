import pathlib

p = pathlib.Path("agent/pe5_agent.py")
src = p.read_text(encoding="utf-8")

# ── 1. Ver contexto alrededor de df = agent.run() ─────────────────────────────
lines = src.splitlines()
for i, line in enumerate(lines[870:890], start=871):
    print(f"{i:4d} | {repr(line)}")
