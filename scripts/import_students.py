import argparse
from app.db import import_students_xlsx

p = argparse.ArgumentParser(description="Importa la matriz privada de estudiantes a SQLite")
p.add_argument("xlsx")
p.add_argument("--db", default="instance/asignaciones.db")
args = p.parse_args()
count = import_students_xlsx(args.xlsx, args.db)
print(f"Importados/actualizados {count} estudiantes en {args.db}")
