import pandas as pd
import re, json

df = pd.read_csv('data/raw/MASTER_normalizado.csv', low_memory=False)
TC   = 3.75
COSTO_IMP = 0.30

FUENTES_LOCALES = {'falabella_pe','falabella','hiraoka_pe','hiraoka',
                   'ripley_pe','ripley','coolbox_pe','coolbox',
                   'linio_pe','mercadolibre_pe','juntoz_pe'}
FUENTES_CHINA   = {'aliexpress'}

# FIX-1: Patron SOLO desktop + exclusion mobile
PATRON_DESKTOP = [
    r'(rtx\s*\d{4}\s*(?:ti|super|xt)?)',
    r'(rx\s*\d{4}\s*(?:xt|gre|xtx)?)',
    r'(gtx?\s*\d{4}\s*(?:ti|super)?)',
    r'(i[3579][\s\-]\d{4,5}(?:k|kf|f|kfx)?(?!\w))',
    r'(ryzen\s*[3579]\s*\d{4}(?:x3d|x|g|gre|xt)?(?!\w))',
    r'(core\s*ultra\s*[579]\s*\d{3}(?:k|kf|f)?(?!\w))',
]

PATRON_MOBILE = re.compile(
    r'(i[3579][\s\-]\d{4,5}[hHuUgGpPeE]\w*'
    r'|core\s*ultra\s*[579]\s*\d{3}[hHuUgGpP]\w*'
    r'|ryzen\s*[3579]\s*\d{4}[uUhHeE]\w*)',
    re.IGNORECASE
)

def normalizar_modelo(titulo):
    t = str(titulo).lower()
    if PATRON_MOBILE.search(t):
        return None
    for pat in PATRON_DESKTOP:
        m = re.search(pat, t)
        if m:
            mod = m.group(1).strip()
            mod = re.sub(r'\s*-\s*', '-', mod)
            mod = re.sub(r'\s+', ' ', mod)
            mod = re.sub(r'(i[3579])\s+(\d)', r'\1-\2', mod)
            mod = re.sub(r'(ryzen\s*[3579])\s+(\d)', r'\1 \2', mod)
            return mod.strip()
    return None

print('Construyendo indice de precios por modelo (solo desktop)...')

df_china = df[df['source'].isin(FUENTES_CHINA) &
              df['price_usd'].notna() & (df['price_usd'] > 0)].copy()
df_local = df[df['source'].str.lower().isin(FUENTES_LOCALES) &
              df['price_pen'].notna() & (df['price_pen'] > 0)].copy()

df_china['modelo_norm'] = df_china['title'].apply(normalizar_modelo)
df_local['modelo_norm'] = df_local['title'].apply(normalizar_modelo)

idx_compra = (df_china[df_china['modelo_norm'].notna()]
              .groupby('modelo_norm')['price_usd']
              .agg(['median','count'])
              .rename(columns={'median':'precio_compra_usd','count':'n_compra'}))

idx_venta  = (df_local[df_local['modelo_norm'].notna()]
              .groupby('modelo_norm')['price_pen']
              .agg(['median','count'])
              .rename(columns={'median':'precio_venta_pen','count':'n_venta'}))

cruce = idx_compra.join(idx_venta, how='inner')

cruce['precio_venta_usd']    = cruce['precio_venta_pen'] / TC
cruce['costo_importado_usd'] = cruce['precio_compra_usd'] * (1 + COSTO_IMP)
cruce['precio_objetivo_usd'] = cruce['precio_venta_usd'] * 0.95
cruce['markup_neto']         = cruce['precio_objetivo_usd'] / cruce['costo_importado_usd']
cruce['roi_pct']             = (cruce['markup_neto'] - 1) * 100

# FIX-2: Ratio coherente (excluir laptop vs chip)
cruce['ratio_precio'] = cruce['precio_venta_usd'] / cruce['precio_compra_usd']
cruce = cruce[cruce['ratio_precio'] <= 3.5]

# FIX-3: Filtros de calidad + n_venta >= 3
cruce_valido = cruce[
    (cruce['roi_pct'] > -50) &
    (cruce['roi_pct'] < 300) &
    (cruce['precio_compra_usd'] > 50) &
    (cruce['n_venta'] >= 3)
].sort_values('roi_pct', ascending=False)

print()
print('=== TOP OPORTUNIDADES - SOLO DESKTOP (LIMPIO) ===')
print('(AliExpress China -> Venta PE | +30% importacion | n_venta >= 3)')
print()
cols = ['precio_compra_usd','precio_venta_usd','costo_importado_usd',
        'precio_objetivo_usd','markup_neto','roi_pct','n_compra','n_venta']
print(cruce_valido[cols].to_string())

print()
print('Total modelos validos (desktop, confiables):', len(cruce_valido))

output = {}
for modelo, row in cruce_valido.iterrows():
    confianza = ('alta'   if row['n_compra'] >= 3 and row['n_venta'] >= 5 else
                 'media'  if row['n_venta'] >= 3 else 'baja')
    output[modelo] = {
        'precio_compra_china_usd': round(row['precio_compra_usd'], 2),
        'costo_importado_usd':     round(row['costo_importado_usd'], 2),
        'precio_venta_pe_usd':     round(row['precio_venta_usd'], 2),
        'precio_objetivo_usd':     round(row['precio_objetivo_usd'], 2),
        'markup_neto':             round(row['markup_neto'], 3),
        'roi_pct':                 round(row['roi_pct'], 1),
        'n_compra':                int(row['n_compra']),
        'n_venta':                 int(row['n_venta']),
        'confianza':               confianza
    }

with open('data/raw/precios_por_modelo.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print('Guardado: data/raw/precios_por_modelo.json')
print()
print('Modelos por confianza:')
for nivel in ['alta','media','baja']:
    n = sum(1 for v in output.values() if v['confianza'] == nivel)
    print('  ' + nivel + ': ' + str(n))
