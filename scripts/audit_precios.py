import pandas as pd

def audit_precios():
    # Cargar la matriz
    df = pd.read_csv("data/features/oe9_feature_matrix.csv")
    
    print("--- COLUMNAS DISPONIBLES EN LA MATRIZ ---")
    print(list(df.columns))
    
    # Buscamos columnas que contengan 'precio' o 'costo'
    cols_precio = [c for c in df.columns if 'precio' in c.lower() or 'costo' in c.lower()]
    print(f"\n--- COLUMNAS RELACIONADAS A PRECIOS ---")
    print(cols_precio)
    
    # Si encuentras las columnas correctas, ajusta los nombres aquí abajo:
    # Por ejemplo, si ves 'precio_local_pen' y 'precio_import_usd'
    # o algo similar a 'costo_base'
    
    # Si quieres que yo analice, por favor pega aquí la lista de columnas 
    # que imprimió el script arriba.
    
if __name__ == "__main__":
    audit_precios()
