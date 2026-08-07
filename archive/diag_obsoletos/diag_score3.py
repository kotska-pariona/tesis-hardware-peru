import pathlib as _pl

p = _pl.Path("agent/pe5_agent.py")
lines = p.read_text(encoding="utf-8").splitlines()

# Ver pesos W_ROI, W_TREND, W_OBS y como se llama compute_decision
print("=== PESOS (buscar W_ROI W_TREND W_OBS) ===")
for i, line in enumerate(lines, start=1):
    if any(x in line for x in ["W_ROI", "W_TREND", "W_OBS", "ROI_CAP", "roi_pct"]):
        print(f"{i:4d} | {line}")
