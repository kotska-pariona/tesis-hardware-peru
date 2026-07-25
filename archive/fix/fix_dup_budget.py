import pathlib as _pl

p = _pl.Path("agent/pe5_agent.py")
src = p.read_text(encoding="utf-8")

# Contar cuántas veces aparece --budget
count = src.count('"--budget"')
print(f"  INFO  --budget aparece {count} veces")

if count > 1:
    # Eliminar el bloque duplicado (el del fallback, que quedó ANTES de parse_args)
    DUP = (
        '    parser.add_argument(\n'
        '        "--budget", type=float, default=None,\n'
        '        help="Presupuesto total en S/. para asignacion knapsack (opcional)"\n'
        '    )\n'
        '    args = parser.parse_args()'
    )
    CLEAN = '    args = parser.parse_args()'

    if DUP in src:
        src = src.replace(DUP, CLEAN, 1)
        print("  OK  duplicado eliminado")
    else:
        print("  WARN  patrón duplicado no encontrado exacto, revisión manual")
elif count == 1:
    print("  OK  solo existe una vez, nada que hacer")
else:
    print("  WARN  --budget no encontrado en absoluto")

p.write_text(src, encoding="utf-8")
print(f"  INFO  ahora --budget aparece {src.count('\"--budget\"')} veces")
