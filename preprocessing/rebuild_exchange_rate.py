"""
rebuild_exchange_rate.py
Reconstruye MASTER_exchange_rate.csv desde TODOS los batch_*_dolar.csv
Parsea fechas en formato mixto, aplica ffill para fines de semana,
y guarda con fechas ISO limpias.
"""
import csv
import re
import pandas as pd
from pathlib import Path

DATA_DIR = Path("data/raw")
TC_MIN   = 3.30
TC_MAX   = 3.60

MONTH_MAP = {
    "jan":"01","feb":"02","mar":"03","apr":"04",
    "may":"05","jun":"06","jul":"07","aug":"08",
    "sep":"09","oct":"10","nov":"11","dec":"12"
}

def parse_date(raw: str, timestamp: str = "") -> str:
    raw = (raw or "").strip()
    # ISO directo
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw
    # "Sun, 12 Jul 2026" o "Sun, 12 Ju"
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{2,3})", raw)
    if m:
        day = m.group(1).zfill(2)
        mon = MONTH_MAP.get(m.group(2).lower()[:3], "07")
        yr  = re.search(r"(\d{4})", raw)
        if yr:
            year = yr.group(1)
        else:
            # inferir año desde timestamp
            yt = re.search(r"(\d{4})", timestamp or "")
            year = yt.group(1) if yt else "2026"
        return f"{year}-{mon}-{day}"
    # fallback: tomar fecha del timestamp
    if timestamp:
        tm = re.match(r"(\d{4}-\d{2}-\d{2})", timestamp)
        if tm:
            return tm.group(1)
    return ""

# ── 1. Leer TODOS los batch_*_dolar.csv ──────────────────────
dolar_files = sorted(DATA_DIR.glob("*dolar*.csv"))
print(f"📂 Archivos _dolar encontrados: {len(dolar_files)}")

records = []
for f in dolar_files:
    with open(f, encoding="utf-8-sig", errors="replace") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        date_raw  = r.get("date","")
        timestamp = r.get("timestamp","")
        date_iso  = parse_date(date_raw, timestamp)
        try:
            mid = float(r.get("mid",""))
        except (ValueError, TypeError):
            mid = None
        try:
            buy = float(r.get("buy",""))
        except (ValueError, TypeError):
            buy = None
        try:
            sell = float(r.get("sell",""))
        except (ValueError, TypeError):
            sell = None

        print(f"   {f.name}: raw='{date_raw}' → '{date_iso}'  "
              f"buy={buy}  mid={mid}  sell={sell}")

        if date_iso and mid and TC_MIN <= mid <= TC_MAX:
            records.append({
                "date": date_iso,
                "buy":  buy,
                "mid":  mid,
                "sell": sell
            })

# ── 2. Consolidar — un TC por día (promedio si hay varios) ───
tc_df = pd.DataFrame(records)
tc_df["date"] = pd.to_datetime(tc_df["date"])
tc_df = (
    tc_df.groupby("date")
    .agg({"buy":"mean","mid":"mean","sell":"mean"})
    .reset_index()
    .sort_values("date")
)

print(f"\n📊 TCs únicos por día antes del ffill:")
for _, r in tc_df.iterrows():
    print(f"   {r['date'].date()}  buy={r['buy']:.4f}  "
          f"mid={r['mid']:.4f}  sell={r['sell']:.4f}")

# ── 3. Rango completo con ffill ───────────────────────────────
fecha_min = tc_df["date"].min()
fecha_max = pd.Timestamp.today().normalize()
rango     = pd.date_range(fecha_min, fecha_max, freq="D")

tc_full = (
    pd.DataFrame({"date": rango})
    .merge(tc_df, on="date", how="left")
)
tc_full[["buy","mid","sell"]] = (
    tc_full[["buy","mid","sell"]].ffill().bfill().round(4)
)

print(f"\n📅 Serie completa con ffill ({len(tc_full)} días):")
for _, r in tc_full.iterrows():
    dia = r["date"].strftime("%a")
    tag = "🔁 ffill" if dia in ("Sat","Sun") else "      "
    print(f"   {r['date'].date()}  {dia}  {tag}  "
          f"buy={r['buy']}  mid={r['mid']}  sell={r['sell']}")

# ── 4. Guardar MASTER_exchange_rate.csv limpio ────────────────
out_path = DATA_DIR / "MASTER_exchange_rate.csv"
out_rows = [
    {
        "date": r["date"].strftime("%Y-%m-%d"),
        "buy":  r["buy"],
        "mid":  r["mid"],
        "sell": r["sell"]
    }
    for _, r in tc_full.iterrows()
]

with open(out_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["date","buy","mid","sell"])
    writer.writeheader()
    writer.writerows(out_rows)

print(f"\n✅ MASTER_exchange_rate.csv reconstruido: {len(out_rows)} entradas")
print(f"   Rango: {out_rows[0]['date']} → {out_rows[-1]['date']}")
