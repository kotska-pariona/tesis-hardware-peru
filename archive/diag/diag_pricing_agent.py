import pathlib as _pl
lines = _pl.Path("agent/pe5_agent.py").read_text(encoding="utf-8").splitlines()

print("=== PricingAgent — definición ===")
for i, l in enumerate(lines, start=1):
    if "PricingAgent" in l or "class Pricing" in l:
        print(f"{i:4d} | {l}")
