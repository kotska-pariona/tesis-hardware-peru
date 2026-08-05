import pandas as pd
import numpy as np
from pymoo.algorithms.moo.nsga3 import NSGA3
from pymoo.core.problem import Problem
from pymoo.optimize import minimize
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM
from pymoo.operators.sampling.rnd import FloatRandomSampling
from pymoo.termination import get_termination
from pymoo.util.ref_dirs import get_reference_directions

# Cargar datos
path = "data/features/oe9_feature_matrix.csv"
df = pd.read_csv(path, encoding="utf-8")
df["r_j"] = pd.to_numeric(df["r_j"], errors="coerce")
df["roi_unitario_pct"] = pd.to_numeric(df["roi_unitario_pct"], errors="coerce")
df["precio_local_pen"] = pd.to_numeric(df["precio_local_pen"], errors="coerce")

print("=== AUDITORÍA DE CONVERGENCIA NSGA-III ===\n")
print(f"Total SKUs: {len(df)}")
print(f"r_j stats: min={df['r_j'].min():.4f}, max={df['r_j'].max():.4f}, mean={df['r_j'].mean():.4f}")
print(f"ROI stats: min={df['roi_unitario_pct'].min():.2f}, max={df['roi_unitario_pct'].max():.2f}, mean={df['roi_unitario_pct'].mean():.2f}")

# Problema de optimización simplificado
class OE9Problem(Problem):
    def __init__(self, df_data):
        self.df = df_data.reset_index(drop=True)
        n_vars = len(self.df)
        # Definir límites: cada variable es binaria (0 o 1)
        super().__init__(n_var=n_vars, n_obj=2, n_ieq_constr=1, type_var=int, 
                         xl=np.zeros(n_vars), xu=np.ones(n_vars))
    
    def _evaluate(self, x, out, *args, **kwargs):
        f1 = np.zeros(len(x))  # Maximizar ROI
        f2 = np.zeros(len(x))  # Minimizar costo
        g3 = np.zeros(len(x))  # Restricción riesgo
        
        for i, solution in enumerate(x):
            selected = solution > 0.5
            if selected.sum() == 0:
                f1[i] = 1e6  # Penalizar soluciones vacías
                f2[i] = 1e6
                g3[i] = 1e6
            else:
                f1[i] = -self.df.loc[selected, "roi_unitario_pct"].mean()  # Negativo para minimizar
                f2[i] = self.df.loc[selected, "precio_local_pen"].sum()
                g3[i] = self.df.loc[selected, "r_j"].mean() - 0.5  # Debe ser <= 0
        
        out["F"] = np.column_stack([f1, f2])
        out["G"] = g3

problem = OE9Problem(df)

# Generar puntos de referencia para NSGA-III
ref_dirs = get_reference_directions("das-dennis", 2, n_partitions=12)

# Ejecutar optimizador con pocos recursos para diagnóstico
algorithm = NSGA3(
    pop_size=20,
    ref_dirs=ref_dirs,
    sampling=FloatRandomSampling(),
    crossover=SBX(prob=0.9, eta=15),
    mutation=PM(eta=20),
    eliminate_duplicates=True
)

res = minimize(
    problem,
    algorithm,
    termination=get_termination("n_gen", 20),
    seed=42,
    verbose=False
)

print(f"\n=== RESULTADOS ===")
print(f"Soluciones encontradas: {len(res.F)}")
print(f"Mejor F1 (ROI): {-res.F[:, 0].min():.2f}%")
print(f"Mejor F2 (Costo Total): S/. {res.F[:, 1].min():.2f}")
print(f"Restricción g3 violada: {(res.G[:, 0] > 0).sum()} soluciones")
print(f"Restricción g3 cumplida: {(res.G[:, 0] <= 0).sum()} soluciones")
print(f"\nPrimeras 10 soluciones (F1=ROI%, F2=Costo, g3=Riesgo-0.5):")
print("Rank | F1(ROI%) | F2(Costo) | g3(Riesgo) | Viable")
print("-" * 55)
for i in range(min(10, len(res.F))):
    viable = "✓" if res.G[i, 0] <= 0 else "✗"
    print(f"{i+1:4d} | {-res.F[i, 0]:8.2f} | {res.F[i, 1]:9.2f} | {res.G[i, 0]:10.4f} | {viable}")
