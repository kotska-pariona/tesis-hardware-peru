import pathlib as _pl

p = _pl.Path("agent/pe5_agent.py")
src = p.read_text(encoding="utf-8")

# Buscar el anchor real
OLD = '        "--category", type=str, default=None,\n        help="Filtrar por categoría (CPU, GPU, RAM, etc.)"\n    )\n    args = parser.parse_args()'
NEW = '        "--category", type=str, default=None,\n        help="Filtrar por categoría (CPU, GPU, RAM, etc.)"\n    )\n    parser.add_argument(\n        "--budget", type=float, default=None,\n        help="Presupuesto total en S/. para asignación knapsack (opcional)"\n    )\n    args = parser.parse_args()'

if OLD in src:
    src = src.replace(OLD, NEW, 1)
    print("  OK  --budget insertado")
else:
    # fallback: insertar antes de args = parser.parse_args()
    OLD2 = "    args = parser.parse_args()"
    NEW2 = ('    parser.add_argument(\n'
            '        "--budget", type=float, default=None,\n'
            '        help="Presupuesto total en S/. para asignacion knapsack (opcional)"\n'
            '    )\n'
            '    args = parser.parse_args()')
    if OLD2 in src:
        src = src.replace(OLD2, NEW2, 1)
        print("  OK  --budget insertado (fallback)")
    else:
        print("  WARN  no se pudo insertar")

p.write_text(src, encoding="utf-8")
