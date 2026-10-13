"""
normalize_brand_model_v4.py
===========================
Mejora de brand_norm / model_norm para:
  - RAM    : extrae capacidad+tipo+velocidad como model_norm
  - LAPTOP : extrae modelo comercial (IdeaPad, Pavilion, ZBook, etc.)
  - COOLER : añade Thermalright, Lian Li, EKWB, Razer, ID-Cooling, etc.
  - CASE   : limpia títulos que son solo marca, añade darkFlash, Vetroo, etc.
Regenera group_key y sobreescribe train/val/test.csv en data/processed/
"""

import re
import pandas as pd
from pathlib import Path

# ─────────────────────────────────────────────
# 1. BRAND PATCHES — marcas que llegan como Unknown
# ─────────────────────────────────────────────
BRAND_PATCHES = {
    # COOLER
    r'\bthermalright\b':   'Thermalright',
    r'\blian[\s\-]?li\b':  'Lian Li',
    r'\bekwb\b':           'EKWB',
    r'\brazer\b':          'Razer',
    r'\bid[\s\-]?cooling\b': 'ID-Cooling',
    r'\bnoctua\b':         'Noctua',
    r'\bbe[\s\-]?quiet\b': 'BeQuiet',
    r'\barctic\b':         'Arctic',
    r'\bfractal[\s\-]?design\b': 'Fractal',
    r'\bminorsonic\b':     'Minorsonic',
    # CASE
    r'\bdarkflash\b':      'DarkFlash',
    r'\bvetroo\b':         'Vetroo',
    r'\bvevor\b':          'Vevor',
    r'\bphanteks\b':       'Phanteks',
    r'\bcorsair\b':        'Corsair',
    r'\bfractal\b':        'Fractal',
    r'\bsilverstone\b':    'SilverStone',
    r'\bantec\b':          'Antec',
    r'\bhalion\b':         'Halion',
    r'\bantryx\b':         'Antryx',
    # LAPTOP
    r'\bhonor\b':          'Honor',
    r'\bskytech\b':        'Skytech',
    r'\bsager\b':          'Sager',
    r'\beluktronics\b':    'Eluktronics',
    r'\brazer\b':          'Razer',
    r'\bteros\b':          'Teros',
    r'\bhuawei\b':         'Huawei',
    r'\bsamsung\b':        'Samsung',
    r'\bgigabyte\b':       'Gigabyte',
    r'\bacer\b':           'Acer',
    r'\basus\b':           'Asus',
    # RAM
    r'\bgeil\b':           'GeIL',
    r'\bdato\b':           'Dato',
    r'\bteam[\s\-]?group\b': 'TeamGroup',
    r'\badata\b':          'Adata',
    r'\bpny\b':            'PNY',
    r'\bpatriott?\b':      'Patriot',
    r'\bv[\-\s]?color\b':  'VColor',
}

# ─────────────────────────────────────────────
# 2. MODEL EXTRACTORS por hw_type
# ─────────────────────────────────────────────

def extract_ram_model(title: str) -> str:
    """
    Extrae especificación de RAM como model_norm.
    Ejemplos:
      "Corsair Vengeance LPX 16GB DDR4 3200MHz" → "16GB DDR4-3200"
      "Kingston Fury 32GB (2x16GB) DDR5 6000MHz CL38" → "32GB DDR5-6000"
      "Micron 8GB 2666V DDR4" → "8GB DDR4-2666"
    """
    t = title.upper()

    # Capacidad total (priorizar la más grande si hay kit)
    cap = None
    # Kits: "2x16GB", "2X32GB", "4x8GB"
    m = re.search(r'(\d+)\s*[xX×]\s*(\d+)\s*GB', t)
    if m:
        cap = f"{int(m.group(1))*int(m.group(2))}GB"
    else:
        m = re.search(r'(\d+)\s*GB', t)
        if m:
            cap = f"{m.group(1)}GB"

    if not cap:
        return "Unknown"

    # Tipo DDR
    ddr = None
    for pat, label in [
        (r'DDR5', 'DDR5'), (r'DDR4', 'DDR4'),
        (r'DDR3L', 'DDR3L'), (r'DDR3', 'DDR3'),
        (r'LPDDR5X', 'LPDDR5X'), (r'LPDDR5', 'LPDDR5'),
        (r'LPDDR4X', 'LPDDR4X'), (r'LPDDR4', 'LPDDR4'),
    ]:
        if re.search(pat, t):
            ddr = label
            break

    if not ddr:
        # Intentar inferir de PC4/PC5
        m2 = re.search(r'PC(\d)-(\d+)', t)
        if m2:
            gen = m2.group(1)
            ddr = 'DDR4' if gen == '4' else ('DDR5' if gen == '5' else 'DDR3')

    if not ddr:
        return cap  # Solo capacidad si no hay tipo

    # Velocidad (MHz)
    speed = None
    # Patrones: 3200MHz, 5200MHZ, DDR4-3200, PC4-25600
    for pat in [
        r'DDR\d[LX]*[\s\-](\d{3,5})',
        r'(\d{3,5})\s*MHZ',
        r'(\d{3,5})\s*MT',
    ]:
        m3 = re.search(pat, t)
        if m3:
            spd = int(m3.group(1))
            if 800 <= spd <= 12000:
                speed = str(spd)
                break

    if not speed:
        # PC4-XXXXX → velocidad = XXXXX / 8
        m4 = re.search(r'PC[345]-(\d{4,6})', t)
        if m4:
            spd = int(int(m4.group(1)) / 8)
            speed = str(spd)

    if speed:
        return f"{cap} {ddr}-{speed}"
    return f"{cap} {ddr}"


# Modelos comerciales de laptop (orden importa: más específico primero)
LAPTOP_MODEL_PATTERNS = [
    # Lenovo
    (r'ideapad[\s\-]?(\w+)', 'IdeaPad'),
    (r'thinkpad[\s\-]?(\w+)', 'ThinkPad'),
    (r'thinkbook[\s\-]?(\w+)', 'ThinkBook'),
    (r'legion[\s\-]?(\w+)', 'Legion'),
    (r'yoga[\s\-]?(\w+)', 'Yoga'),
    (r'slim[\s\-]?(\d+)', 'Slim'),
    (r'loq[\s\-]?(\w+)', 'LOQ'),
    # HP
    (r'pavilion[\s\-]?(\w+)', 'Pavilion'),
    (r'envy[\s\-]?(\w+)', 'Envy'),
    (r'spectre[\s\-]?(\w+)', 'Spectre'),
    (r'omen[\s\-]?(\w+)', 'Omen'),
    (r'victus[\s\-]?(\w+)', 'Victus'),
    (r'elitebook[\s\-]?(\w+)', 'EliteBook'),
    (r'probook[\s\-]?(\w+)', 'ProBook'),
    (r'zbook[\s\-]?(\w+)', 'ZBook'),
    (r'omnibook[\s\-]?(\w+)', 'OmniBook'),
    # Dell
    (r'xps[\s\-]?(\w+)', 'XPS'),
    (r'inspiron[\s\-]?(\w+)', 'Inspiron'),
    (r'latitude[\s\-]?(\w+)', 'Latitude'),
    (r'precision[\s\-]?(\w+)', 'Precision'),
    (r'alienware[\s\-]?(\w+)', 'Alienware'),
    (r'vostro[\s\-]?(\w+)', 'Vostro'),
    (r'dell pro[\s\-]?(\w+)', 'DellPro'),
    # ASUS
    (r'rog[\s\-]?(\w+)', 'ROG'),
    (r'tuf[\s\-]?(\w+)', 'TUF'),
    (r'zenbook[\s\-]?(\w+)', 'ZenBook'),
    (r'vivobook[\s\-]?(\w+)', 'VivoBook'),
    (r'expertbook[\s\-]?(\w+)', 'ExpertBook'),
    # Acer
    (r'nitro[\s\-]?(\w+)', 'Nitro'),
    (r'predator[\s\-]?(\w+)', 'Predator'),
    (r'aspire[\s\-]?(\w+)', 'Aspire'),
    (r'swift[\s\-]?(\w+)', 'Swift'),
    (r'spin[\s\-]?(\w+)', 'Spin'),
    # MSI
    (r'raider[\s\-]?(\w+)', 'Raider'),
    (r'stealth[\s\-]?(\w+)', 'Stealth'),
    (r'katana[\s\-]?(\w+)', 'Katana'),
    (r'titan[\s\-]?(\w+)', 'Titan'),
    (r'creator[\s\-]?(\w+)', 'Creator'),
    (r'prestige[\s\-]?(\w+)', 'Prestige'),
    (r'cyborg[\s\-]?(\w+)', 'Cyborg'),
    # Apple
    (r'macbook\s?air[\s\-]?(\w*)', 'MacBook Air'),
    (r'macbook\s?pro[\s\-]?(\w*)', 'MacBook Pro'),
    # Razer
    (r'razer blade[\s\-]?(\w+)', 'Blade'),
    # Honor
    (r'magicbook[\s\-]?(\w+)', 'MagicBook'),
    # Samsung
    (r'galaxy book[\s\-]?(\w+)', 'Galaxy Book'),
    # Huawei
    (r'matebook[\s\-]?(\w+)', 'MateBook'),
    # Genérico gaming
    (r'gaming laptop', 'Gaming'),
]

def extract_laptop_model(title: str) -> str:
    t = title.lower()
    for pat, label in LAPTOP_MODEL_PATTERNS:
        m = re.search(pat, t)
        if m:
            suffix = m.group(1).upper() if m.lastindex and m.group(1) else ''
            # Limpiar sufijos no informativos
            if suffix in ('LAPTOP', 'COMPUTER', 'PC', 'WITH', 'AND', ''):
                return label
            # Limitar a 6 chars para evitar ruido
            suffix = suffix[:6].rstrip('-')
            return f"{label} {suffix}".strip() if suffix else label
    return "Unknown"


COOLER_MODEL_PATTERNS = [
    # AIO por tamaño
    (r'(\d{3})\s*mm\s*(aio|liquid|water)', lambda m: f"AIO-{m.group(1)}mm"),
    (r'aio\s*(\d{3})', lambda m: f"AIO-{m.group(1)}mm"),
    (r'(360|280|240|120)\s*(?:mm)?\s*(?:radiator|rad)', lambda m: f"AIO-{m.group(1)}mm"),
    # Air cooler
    (r'(nh[\-\s]?\w+)', lambda m: m.group(1).upper().replace(' ','-')),
    # Modelos con nombre propio
    (r'(masterliquid\s*\w+)', lambda m: m.group(1).title()),
    (r'(hyper\s*\d+\w*)', lambda m: m.group(1).title()),
    (r'(galahad\s*\w+)', lambda m: 'Galahad'),
    (r'(frozen\s*\w+)', lambda m: 'Frozen'),
    (r'(trofeo\s*\w+)', lambda m: 'Trofeo'),
    (r'(mjolnir\s*\w+)', lambda m: 'Mjolnir'),
    (r'(aqua\s*elite\s*\w+)', lambda m: 'AquaElite'),
    (r'(hydroshift\s*\w+)', lambda m: 'HydroShift'),
    (r'(hanbo\s*\w+)', lambda m: 'Hanbo'),
    (r'(nucleus\s*\w+)', lambda m: 'Nucleus'),
]

def extract_cooler_model(title: str) -> str:
    t = title.lower()
    for pat, fn in COOLER_MODEL_PATTERNS:
        m = re.search(pat, t)
        if m:
            result = fn(m)
            return result[:30] if result else "Unknown"
    # Fallback: AIO genérico si menciona tamaño
    m = re.search(r'\b(360|280|240|120)\b', t)
    if m:
        return f"AIO-{m.group(1)}mm"
    return "Unknown"


CASE_MODEL_PATTERNS = [
    (r'lancool\s*(\w+)', 'Lancool'),
    (r'meshify\s*(\w+)', 'Meshify'),
    (r'define\s*(\w+)', 'Define'),
    (r'torrent\s*(\w+)', 'Torrent'),
    (r'4000[dx]?\b', '4000D'),
    (r'5000[dx]?\b', '5000D'),
    (r'h[567]\d*\s*(?:flow)?\b', None),  # NZXT H510, H710, H6 Flow
    (r'p\d{3}\b', None),                  # Phanteks P400, P500
    (r'rx[\-\s]?\d+', None),              # Antryx RX-450
    (r'pure base\s*(\w+)', 'PureBase'),
    (r'dark base\s*(\w+)', 'DarkBase'),
    (r'view\s*(\d+)', 'View'),
    (r'core\s*[vp]\s*(\d+)', 'Core'),
    (r'commander\s*(\w+)', 'Commander'),
    (r'enthoo\s*(\w+)', 'Enthoo'),
    (r'evolv\s*(\w+)', 'Evolv'),
    (r'pop[\s\-]?(\w+)', 'Pop'),
]

def extract_case_model(title: str) -> str:
    t = title.lower()
    for pat, label in CASE_MODEL_PATTERNS:
        m = re.search(pat, t)
        if m:
            if label:
                suffix = m.group(1).upper() if m.lastindex and m.group(1) else ''
                suffix = suffix[:6].rstrip('-')
                return f"{label} {suffix}".strip() if suffix else label
            else:
                return m.group(0).upper().replace(' ', '-')
    return "Unknown"


# ─────────────────────────────────────────────
# 3. FUNCIÓN PRINCIPAL
# ─────────────────────────────────────────────

def patch_brand(title: str, current_brand: str) -> str:
    if current_brand != "Unknown":
        return current_brand
    t = title.lower()
    for pat, brand in BRAND_PATCHES.items():
        if re.search(pat, t, re.IGNORECASE):
            return brand
    return "Unknown"


def extract_model(row) -> str:
    hw   = row["hw_type"]
    title = str(row["title"])
    current = str(row["model_norm"])

    if current != "Unknown":
        return current

    if hw == "ram":
        return extract_ram_model(title)
    elif hw == "laptop":
        return extract_laptop_model(title)
    elif hw == "cooler":
        return extract_cooler_model(title)
    elif hw == "case":
        return extract_case_model(title)
    return "Unknown"


def build_group_key(row) -> str:
    hw    = row["hw_type"]
    brand = row["brand_norm"]
    model = row["model_norm"]
    L1_hw = {"cpu", "gpu", "motherboard", "ssd"}
    L2_hw = {"ram", "monitor", "psu", "laptop"}
    if brand != "Unknown" and model != "Unknown":
        return f"{brand}|{model}"
    elif brand != "Unknown":
        if hw in L1_hw:
            return f"{brand}|{hw}"
        elif hw in L2_hw:
            return f"{brand}|{hw}"
        else:
            return f"{brand}|{hw}"
    else:
        return f"unk|{hw}"


def process_split(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    print(f"  Leyendo {path.name}: {len(df):,} filas")

    # Patch brand
    df["brand_norm"] = df.apply(
        lambda r: patch_brand(str(r["title"]), str(r["brand_norm"])), axis=1
    )

    # Patch model
    df["model_norm"] = df.apply(extract_model, axis=1)

    # Reconstruir group_key
    df["group_key"] = df.apply(build_group_key, axis=1)

    # Reconstruir brand_model (alias usado en algunos scripts)
    df["brand_model"] = df["brand_norm"] + "|" + df["model_norm"]

    return df


# ─────────────────────────────────────────────
# 4. EJECUTAR EN LOS 3 SPLITS
# ─────────────────────────────────────────────

if __name__ == "__main__":
    base = Path("data/processed")
    results = {}

    for split in ["train", "val", "test"]:
        p = base / f"{split}.csv"
        df = process_split(p)
        df.to_csv(p, index=False)
        print(f"  ✅ Guardado {split}.csv")

        # Métricas por hw_type
        print(f"\n  {'hw_type':<15} {'Brand%':>8} {'Model%':>8} {'Full%':>8}  {'Keys':>6}")
        for hw in sorted(df["hw_type"].unique()):
            sub = df[df["hw_type"] == hw]
            b    = (sub["brand_norm"] != "Unknown").mean() * 100
            m    = (sub["model_norm"] != "Unknown").mean() * 100
            full = ((sub["brand_norm"] != "Unknown") & (sub["model_norm"] != "Unknown")).mean() * 100
            keys = sub["group_key"].nunique()
            flag = "✅" if full >= 75 else ("🟡" if full >= 50 else "🔴")
            print(f"  {flag} {hw:<13} {b:>7.1f}% {m:>7.1f}% {full:>7.1f}%  {keys:>6,}")

        l1 = ((df["brand_norm"] != "Unknown") & (df["model_norm"] != "Unknown")).sum()
        l2 = ((df["brand_norm"] != "Unknown") & (df["model_norm"] == "Unknown")).sum()
        l3 = (df["brand_norm"] == "Unknown").sum()
        total = len(df)
        print(f"\n  GLOBAL [{split}]: "
              f"L1={l1:,}({100*l1/total:.0f}%) "
              f"L2={l2:,}({100*l2/total:.0f}%) "
              f"L3={l3:,}({100*l3/total:.0f}%)")
        print()

    print("✅ Normalización v4 completada.")