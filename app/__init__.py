import os
from datetime import timedelta
from flask import Flask
from .db import init_db, import_students_if_available


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-me"),
        DATABASE=os.environ.get("DATABASE", os.path.join(app.instance_path, "asignaciones.db")),
        STUDENTS_XLSX=os.environ.get("STUDENTS_XLSX", ""),
        ADMIN_EMAIL=os.environ.get("ADMIN_EMAIL", "docente@unibague.edu.co"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", "cambie-esta-clave"),
        ADMIN_NAME=os.environ.get("ADMIN_NAME", "Daniel Palomo"),
        ASSIGNMENT_OVERRIDES=os.environ.get("ASSIGNMENT_OVERRIDES", ""),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    if test_config:
        app.config.update(test_config)

    os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)
    init_db(app)
    import_students_if_available(app)

    from .routes import bp
    app.register_blueprint(bp)
    return app
