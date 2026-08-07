"""
FIX-20: Whitelist filter por categoria
Aplica ANTES de calcular precio_mediano en _analyze_category.
En lugar de blacklist (infinita), usamos whitelist de terminos
que DEBEN aparecer en el titulo para ser considerado valido.
"""
import pathlib, re

TARGET = pathlib.Path("agent/pe5_agent.py")
src = TARGET.read_text(encoding="utf-8")

# ── Whitelist por categoria ──────────────────────────────────────────────────
WHITELIST_BLOCK = '''
        # [FIX-20] Whitelist filter: solo titulos que contengan keywords del producto
        # Elimina contaminacion (CASIO, escritorios, TVs, PCs completas en cat CPU, etc.)
        CATEGORY_WHITELIST = {
            "CPU": [
                "procesador","processor","ryzen","intel","core i","core ultra",
                "athlon","threadripper","xeon","pentium","celeron","i3","i5","i7","i9",
                "amd","ghz","lga","am4","am5","am3"
            ],
            "GPU": [
                "tarjeta","grafica","gpu","geforce","radeon","rtx","gtx","rx ",
                "nvidia","amd","vga","gddr","video card","graphics"
            ],
            "RAM": [
                "ram","memoria","ddr","dimm","sodimm","mhz","gb ddr",
                "memory","kingston","corsair","crucial","hyperx","gskill","teamgroup"
            ],
            "SSD": [
                "ssd","nvme","m.2","solid state","nand","pcie","sata",
                "samsung 870","samsung 980","wd blue","wd black","kingston",
                "crucial","seagate","disco solido"
            ],
            "MONITOR": [
                "monitor","pantalla","display","ips","va panel","hz","ms ",
                "1080p","1440p","4k","ultrawide","curved","gaming monitor"
            ],
            "MOTHERBOARD": [
                "motherboard","placa","mainboard","lga","am4","am5","atx","micro atx",
                "mini itx","z790","b650","x670","b550","z690","h610","b760"
            ],
            "PSU": [
                "fuente","psu","power supply","watt","80 plus","modular",
                "corsair","evga","seasonic","thermaltake","cooler master"
            ],
            "COOLER": [
                "cooler","disipador","ventilador","fan","aio","liquid cool",
                "noctua","be quiet","arctic","deepcool","thermalright","cpu cooler"
            ],
            "CASE": [
                "case","gabinete","torre","chasis","atx","mid tower","full tower",
                "mini itx","tempered glass","nzxt","fractal","lian li","corsair"
            ],
        }

        _whitelist = CATEGORY_WHITELIST.get(category, [])
        if _whitelist:
            def _has_whitelist(title_str):
                t = str(title_str).lower()
                return any(kw in t for kw in _whitelist)
            _before_wl = len(local_cat)
            local_cat = local_cat[local_cat["title"].apply(_has_whitelist)]
            _removed_wl = _before_wl - len(local_cat)
            if _removed_wl > 0:
                log.debug(f"  [FIX-20] {category}: {_removed_wl} titulos ruidosos eliminados "
                          f"({_removed_wl/_before_wl*100:.1f}%)")
            if local_cat.empty:
                log.warning(f"  [FIX-20] {category}: sin datos tras whitelist filter")
                return

'''

# Insertar DESPUES del filtro LOCAL_PRICE_MIN_PEN (tras el bloque FIX-16)
# Anchor: la linea "if local_cat.empty:" que sigue al filtro de precio minimo
OLD_ANCHOR = (
    "        local_cat = local_cat[local_cat[\"price_pen\"] >= _local_min]\n"
    "        if local_cat.empty:\n"
    "            return\n"
    "\n"
    "        precio_mediano = float(local_cat[\"price_pen\"].median())"
)
NEW_ANCHOR = (
    "        local_cat = local_cat[local_cat[\"price_pen\"] >= _local_min]\n"
    "        if local_cat.empty:\n"
    "            return\n"
    "\n"
    + WHITELIST_BLOCK +
    "        precio_mediano = float(local_cat[\"price_pen\"].median())"
)

if OLD_ANCHOR in src:
    new_src = src.replace(OLD_ANCHOR, NEW_ANCHOR, 1)
    print("[1] Whitelist filter insertado correctamente")
else:
    print("[ERROR] No se encontro el anchor — verificar indentacion")
    # Buscar lineas cercanas para debug
    for i, line in enumerate(src.splitlines()):
        if "precio_mediano = float(local_cat" in line:
            print(f"  Anchor cercano en L{i+1}: {line!r}")
    new_src = src

TARGET.write_text(new_src, encoding="utf-8")
print("FIX-20 aplicado -> agent/pe5_agent.py")
