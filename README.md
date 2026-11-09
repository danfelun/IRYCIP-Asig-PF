# PROYECTO ORIGEN · Asignador de Proyecto Final

Aplicación web para realizar la asignación única de temas del proyecto final del curso **INTERNET: Redes y Comunicaciones IP**.

## Funcionalidad

- Acceso estudiantil mediante **correo institucional**, sin contraseña.
- El correo se valida contra una matriz privada `EstudiantesGrupos.xlsx`.
- El **primer estudiante** de cada grupo que confirma la selección determina el proyecto del grupo.
- Los compañeros que ingresen posteriormente solo pueden consultar la asignación ya registrada.
- Los temas se distribuyen primero sin repetición; si existen más grupos que temas disponibles, el sistema comienza a reutilizar los temas de forma equilibrada.
- Las asignaciones privadas definidas en `.env` se reservan y no participan en el sorteo general.
- Panel docente protegido con correo y contraseña.
- **Asignación manual desde el panel docente** para grupos que no participaron en el sorteo.
- **Creación de nuevos temas desde el panel docente**, disponibles de inmediato para futuras asignaciones.
- **Panel docente con actualización automática cada 5 segundos**, sin recargar manualmente la página.
- La sesión administrativa se conserva al actualizar el navegador y también al probar el flujo estudiantil desde el mismo navegador.
- El número de grupos **no está codificado**: se obtiene automáticamente de la matriz activa.
- Botón **Sincronizar matriz** para volver a leer el Excel sin reiniciar el contenedor.
- Exportación del cuadro de asignaciones a PDF con identidad visual **PROYECTO ORIGEN**.
- Estilo visual inspirado en **ORIGEN · Redes que conectan conocimiento**.

## Grupos dinámicos

La aplicación no presupone que existan 12 grupos. Al leer `EstudiantesGrupos.xlsx` identifica los números de grupo presentes y construye el panel automáticamente.

Por ejemplo, una matriz con grupos:

```text
1, 2, 3, 4, 5, 6, 7, 8
```

producirá un panel de 8 grupos. Una matriz con grupos hasta el 14 producirá un panel de 14 grupos.

Al iniciar la aplicación, la matriz se sincroniza automáticamente. También puede forzarse la actualización desde:

```text
Panel docente → Sincronizar matriz
```

Los estudiantes que ya no estén presentes en la matriz quedan inactivos y no podrán ingresar, pero no se eliminan de la base de datos para preservar la trazabilidad histórica de las asignaciones.

## Actualización en vivo del panel docente

El panel consulta el estado de las asignaciones cada 5 segundos mediante una petición interna y actualiza:

- cantidad de grupos asignados;
- cantidad de pendientes;
- barra de progreso;
- tema seleccionado;
- estudiante que realizó la selección;
- fecha y hora de la asignación.

No es necesario utilizar `F5` para observar nuevas asignaciones.

Si la matriz cambia el número de grupos, el panel realiza una recarga normal y conserva la sesión docente.

## Persistencia de sesión

Las sesiones utilizan la `SECRET_KEY` definida en `.env` y permanecen activas por varias horas. Para evitar cierres inesperados:

1. defina una `SECRET_KEY` fija y segura;
2. no regenere `.env` cada vez que levanta el contenedor;
3. mantenga el volumen de configuración y la base de datos como se define en `docker-compose.yml`.

Ejemplo para generar una clave:

```bash
openssl rand -hex 32
```

## Privacidad

La matriz de estudiantes contiene nombres y correos institucionales. **No debe subirse a un repositorio público**.

El proyecto incluye reglas `.gitignore` para excluir:

```text
data/*.xlsx
data/*.xls
data/*.csv
instance/*.db
.env
```

Antes de publicar el repositorio, confirme siempre con:

```bash
git status
```

## Matriz esperada

Primera hoja de `EstudiantesGrupos.xlsx`:

| Nombre | Correo Institucional | Grupo |
|---|---|---:|
| ... | ... | 1 |
| ... | ... | 2 |

Los números de grupo deben ser enteros positivos, pero no existe un máximo fijo.

## Puesta en marcha con Docker Compose

### 1. Copiar la matriz privada

```bash
cp /ruta/EstudiantesGrupos.xlsx data/EstudiantesGrupos.xlsx
```

### 2. Crear variables de entorno

```bash
cp .env.example .env
```

Edite `.env` y cambie obligatoriamente:

```text
SECRET_KEY=
ADMIN_NAME=Daniel Palomo
ADMIN_EMAIL=
ADMIN_PASSWORD=
```

La aplicación espera dentro del contenedor:

```text
STUDENTS_XLSX=/private/EstudiantesGrupos.xlsx
DATABASE=/data/asignaciones.db
```

### 3. Asignaciones reservadas

La configuración especial se mantiene fuera del código público:

```text
ASSIGNMENT_OVERRIDES=10:G10-FIXED
```

No publique el archivo `.env`.

### 4. Construir e iniciar

```bash
docker compose up -d --build
```

### 5. Acceder

Estudiantes:

```text
http://IP_SERVIDOR:8080/login
```

Panel docente:

```text
http://IP_SERVIDOR:8080/admin/login
```

## Operación de la asignación

1. Un estudiante escribe su correo institucional.
2. El sistema identifica automáticamente su grupo.
3. Si el grupo todavía no tiene proyecto, puede confirmar una única asignación.
4. El backend registra el tema, el estudiante responsable y la fecha.
5. A partir de ese momento, cualquier integrante del grupo ve el mismo resultado.
6. El docente observa el cambio automáticamente desde su panel.
7. El docente puede descargar el consolidado en PDF.
8. Si un grupo no participa, el docente puede asignarle manualmente un tema pendiente desde el panel.
9. El docente también puede incorporar nuevos temas al banco sin modificar el código ni reiniciar el contenedor.

La elección se realiza dentro de una transacción de base de datos para impedir que dos estudiantes del mismo grupo obtengan temas diferentes si acceden casi simultáneamente.

## Gestión docente de asignaciones

El panel incluye una sección **Asignación manual**. Solo aparecen como candidatos los grupos activos que todavía están pendientes. El docente selecciona el grupo y el tema, y la aplicación registra:

- grupo asignado;
- tema;
- nombre del docente configurado en `ADMIN_NAME`;
- fecha y hora;
- método de asignación `manual`.

Las asignaciones realizadas por estudiantes continúan registrándose como método `student`. Esta diferencia se muestra en el panel y queda disponible para el reporte.

Los temas reservados mediante `ASSIGNMENT_OVERRIDES` siguen protegidos y no pueden asignarse manualmente a otro grupo distinto del configurado.

## Agregar temas desde el panel

En **Banco de temas** el docente puede registrar un tema nuevo indicando:

- título;
- plataforma;
- protocolos;
- enfoque de red;
- descripción breve.

El tema queda guardado en SQLite y participa inmediatamente en las asignaciones automáticas posteriores. No es necesario editar `topics.py`, reconstruir la imagen ni reiniciar el servicio.

Los temas creados desde el panel se conservan en `instance/asignaciones.db`; por tanto, no elimine la base si desea conservarlos.

## Más grupos que temas

Si el número de grupos supera la cantidad de temas no reservados, la aplicación reutiliza temas intentando mantener la menor cantidad posible de repeticiones. Esto permite cambiar el tamaño del curso sin modificar el código.

## Reporte PDF

El PDF utiliza la identidad visual de PROYECTO ORIGEN:

- fondo azul oscuro;
- acentos cian y naranja;
- tabla de alto contraste;
- estado pendiente destacado;
- fecha de generación en zona horaria `America/Bogota`;
- metadatos PDF identificados como PROYECTO ORIGEN.

El archivo se descarga con el nombre:

```text
PROYECTO_ORIGEN_Asignacion_Proyecto_Final.pdf
```

## Temas disponibles

- WordPress + MariaDB.
- Joomla + MariaDB.
- DNS con BIND9.
- DHCPv6.
- Servidor web Nginx o Apache.
- IIS en Windows Server.
- FTP / FTPS.
- SFTP.
- Correo básico con Postfix/Dovecot.
- DHCP IPv4 en Windows Server.
- DNS en Windows Server.
- DNS avanzado + servidor web HTTPS integrado.

## Consideración de seguridad

El acceso estudiantil por correo sin contraseña es **un mecanismo de identificación académica ligera**, no un sistema de autenticación fuerte. Cualquier persona que conozca el correo de otro estudiante podría intentar identificarse con él. Para el escenario planteado esto sigue exactamente el requisito de la actividad; si se despliega fuera de una red controlada, se recomienda posteriormente integrar autenticación institucional.

## Actualizar una instalación existente

La versión actual incluye una migración automática de la base de datos anterior para:

- retirar el límite fijo de 12 grupos;
- permitir reutilización equilibrada de temas cuando existan más grupos que temas;
- incorporar el estado activo/inactivo de estudiantes;
- registrar si una asignación fue realizada por un estudiante o por el docente;
- permitir temas personalizados persistentes creados desde el panel.

Antes de actualizar una instalación utilizada en producción académica se recomienda respaldar la base:

```bash
cp instance/asignaciones.db instance/asignaciones.db.bak
```

Después actualice los archivos y reconstruya:

```bash
docker compose down
docker compose up -d --build
```

No elimine `instance/asignaciones.db` si desea conservar las asignaciones existentes.

## Desarrollo local sin Docker

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python scripts/import_students.py /ruta/EstudiantesGrupos.xlsx --db instance/asignaciones.db
flask --app 'app:create_app()' run --debug
```

## Pruebas

```bash
python -m unittest discover -s tests -v
```

## Estructura

```text
ORIGEN_Asignacion_Proyecto_Final/
├── app/
│   ├── __init__.py
│   ├── db.py
│   ├── routes.py
│   ├── topics.py
│   ├── static/
│   │   └── style.css
│   └── templates/
├── data/
│   ├── README_PRIVATE_DATA.txt
│   └── students.example.txt
├── instance/
├── scripts/
│   └── import_students.py
├── tests/
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md
```

## Licencia / uso

Proyecto académico para **PROYECTO ORIGEN**. Antes de reutilizar la aplicación con otros cursos, sustituya la matriz privada y revise la configuración administrativa.
