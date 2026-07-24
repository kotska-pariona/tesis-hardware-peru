"""
patch_exchange_rate.py  v2
Parsea fechas en formato mixto (ISO y "Mon, 13 Ju..."),
agrega fines de semana con ffill, y guarda el CSV limpio.
"""
import csv
import re
import pandas as pd
from pathlib import Path

DATA_DIR = Path("data/raw")
TC_MIN   = 3.50
TC_MAX   = 4.20
path     = DATA_DIR / "MASTER_exchange_rate.csv"

# ── 1. Leer CSV ───────────────────────────────────────────────
with open(path, encoding="utf-8-sig", errors="replace") as f:
    rows = list(csv.DictReader(f))

print(f"📂 Entradas actuales: {len(rows)}")

# ── 2. Parsear fechas con formato mixto ───────────────────────
MONTH_MAP = {
    "jan":"01","feb":"02","mar":"03","apr":"04",
    "may":"05","jun":"06","jul":"07","aug":"08",
    "sep":"09","oct":"10","nov":"11","dec":"12"
}

def parse_date_flexible(raw: str, timestamp: str = "") -> str:
    """
    Acepta:
      - '2026-07-10'           → '2026-07-10'
      - 'Mon, 13 Jul 2026...'  → '2026-07-13'
      - 'Mon, 13 Ju'           → infiere año desde timestamp
    """
    raw = (raw or "").strip()

    # Formato ISO directo
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw

    # Formato "Mon, 13 Jul 2026" o "Mon, 13 Ju"
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{2,3})", raw)
    if m:
        day  = m.group(1).zfill(2)
        mon  = MONTH_MAP.get(m.group(2).lower()[:3], "07")
        # Año: buscar en raw primero, luego en timestamp
        yr_m = re.search(r"(\d{4})", raw)
        if yr_m:
            year = yr_m.group(1)
        elif timestamp:
            yr_t = re.search(r"(\d{4})", timestamp)
            year = yr_t.group(1) if yr_t else "2026"
        else:
            year = "2026"
        return f"{year}-{mon}-{day}"

    # Fallback: intentar con timestamp
    if timestamp:
        ts_m = re.match(r"(\d{4}-\d{2}-\d{2})", timestamp)
        if ts_m:
            return ts_m.group(1)

    return ""

# ── 3. Construir DataFrame limpio ─────────────────────────────
records = []
for r in rows:
    date_parsed = parse_date_flexible(
        r.get("date",""),
        r.get("timestamp","")
    )
    mid_raw = r.get("mid","")
    try:
        mid_val = float(mid_raw)
    except (ValueError, TypeError):
        mid_val = None

    print(f"   raw='{r.get('date','')}' → parsed='{date_parsed}'  mid={mid_val}")
    if date_parsed:
        records.append({"date": date_parsed, "mid": mid_val})

tc_df = pd.DataFrame(records)
tc_df["date"] = pd.to_datetime(tc_df["date"], errors="coerce")
tc_df["mid"]  = pd.to_numeric(tc_df["mid"], errors="coerce")

# Marcar TCs fuera de rango como NaN
tc_df.loc[~tc_df["mid"].between(TC_MIN, TC_MAX), "mid"] = None

# ── 4. Rango completo con ffill ───────────────────────────────
fecha_min = tc_df["date"].min()
fecha_max = pd.Timestamp.today().normalize()
rango     = pd.date_range(fecha_min, fecha_max, freq="D")

tc_full = (
    pd.DataFrame({"date": rango})
    .merge(tc_df[["date","mid"]], on="date", how="left")
)
tc_full["mid"] = tc_full["mid"].ffill().bfill().round(4)

print(f"\n📅 Serie completa ({len(tc_full)} días):")
for _, row in tc_full.iterrows():
    dia = row["date"].strftime("%a")
    tag = "🔁 ffill" if dia in ("Sat","Sun") else ""
    print(f"   {row['date'].date()}  {dia}  mid={row['mid']}  {tag}")

# ── 5. Guardar — solo columnas date y mid ─────────────────────
out_rows = [
    {"date": r["date"].strftime("%Y-%m-%d"), "mid": r["mid"]}
    for _, r in tc_full.iterrows()
]

with open(path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["date","mid"])
    writer.writeheader()
    writer.writerows(out_rows)

print(f"\n✅ Guardado: {len(out_rows)} entradas con fechas ISO limpias")
print("   Ahora rebuild_master.py encontrará TC para TODOS los días incluido el 12-jul")
