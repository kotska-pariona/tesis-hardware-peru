import pathlib as _pl

lines = _pl.Path("analisis/roi_calculator.py").read_text(encoding="utf-8").splitlines()

print("=== LOCAL_SOURCES / IMPORT_SOURCES (líneas 85-130) ===")
for i, l in enumerate(lines[84:135], start=85):
    print(f"  {i:4d} | {l}")

# También ver la función _match_local_price (FIX-12)
print("\n=== _match_local_price (FIX-12) ===")
in_fn = False
for i, l in enumerate(lines, start=1):
    if "_match_local_price" in l and "def " in l:
        in_fn = True
    if in_fn:
        print(f"  {i:4d} | {l}")
        if in_fn and i > 10 and l.strip() == "" and lines[i].strip().startswith("def "):
            break
        if i > 300:
            break
