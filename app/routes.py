import io
import secrets
from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .db import get_db, import_students_xlsx, utc_now_iso

bp = Blueprint("main", __name__)
BOGOTA = ZoneInfo("America/Bogota")


def assignment_overrides():
    """Parsea asignaciones privadas desde ASSIGNMENT_OVERRIDES: 10:G10-FIXED,2:OTRO."""
    raw = current_app.config.get("ASSIGNMENT_OVERRIDES", "")
    result = {}
    for item in raw.split(","):
        item = item.strip()
        if not item or ":" not in item:
            continue
        group, code = item.split(":", 1)
        try:
            result[int(group.strip())] = code.strip()
        except ValueError:
            continue
    return result


def student_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("student_email"):
            return redirect(url_for("main.login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("main.admin_login"))
        return view(*args, **kwargs)
    return wrapped


def _format_assignment_time(iso_value):
    if not iso_value:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_value)
        return dt.astimezone(BOGOTA).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return str(iso_value).replace("T", " ")[:19]


@bp.get("/")
def index():
    return render_template("index.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        db = get_db()
        student = db.execute(
            "SELECT * FROM students WHERE email = ? AND active=1", (email,)
        ).fetchone()
        if not student:
            flash("El correo no se encuentra autorizado en la matriz activa del curso.", "error")
            return render_template("login.html", email=email), 403

        # No se limpia toda la sesión: el docente puede probar el flujo de estudiante
        # en el mismo navegador sin perder su sesión administrativa.
        session["student_email"] = student["email"]
        session["student_name"] = student["name"]
        session["group_no"] = student["group_no"]
        session.permanent = True
        return redirect(url_for("main.assignment"))
    return render_template("login.html")


@bp.post("/logout")
def logout():
    session.pop("student_email", None)
    session.pop("student_name", None)
    session.pop("group_no", None)
    return redirect(url_for("main.index"))


@bp.get("/asignacion")
@student_required
def assignment():
    db = get_db()
    group_no = session["group_no"]
    assignment = db.execute(
        """SELECT a.*, t.title, t.platform, t.protocols, t.network, t.summary
           FROM assignments a JOIN topics t ON t.code=a.topic_code
           WHERE a.group_no=?""",
        (group_no,),
    ).fetchone()
    return render_template("assignment.html", assignment=assignment)


@bp.post("/asignacion/sortear")
@student_required
def draw_assignment():
    db = get_db()
    group_no = int(session["group_no"])
    email = session["student_email"]
    name = session["student_name"]

    db.execute("BEGIN IMMEDIATE")
    try:
        existing = db.execute(
            "SELECT topic_code FROM assignments WHERE group_no=?", (group_no,)
        ).fetchone()
        if existing:
            db.execute("COMMIT")
            flash("El grupo ya cuenta con un tema asignado.", "info")
            return redirect(url_for("main.assignment"))

        overrides = assignment_overrides()
        reserved_codes = set(overrides.values())
        if group_no in overrides:
            selected = overrides[group_no]
        else:
            available_codes = [
                r["code"]
                for r in db.execute("SELECT code FROM topics ORDER BY code").fetchall()
                if r["code"] not in reserved_codes
            ]
            if not available_codes:
                raise RuntimeError("No existen temas disponibles para asignar")

            usage = {
                r["topic_code"]: r["c"]
                for r in db.execute(
                    "SELECT topic_code, COUNT(*) AS c FROM assignments GROUP BY topic_code"
                ).fetchall()
            }
            min_usage = min(usage.get(code, 0) for code in available_codes)
            candidates = [code for code in available_codes if usage.get(code, 0) == min_usage]
            selected = secrets.choice(candidates)

        db.execute(
            """INSERT INTO assignments(group_no,topic_code,claimed_by_email,claimed_by_name,assigned_at)
               VALUES(?,?,?,?,?)""",
            (group_no, selected, email, name, utc_now_iso()),
        )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    return redirect(url_for("main.assignment", reveal="1"))


@bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        ok_email = secrets.compare_digest(email, current_app.config["ADMIN_EMAIL"].lower())
        ok_password = secrets.compare_digest(password, current_app.config["ADMIN_PASSWORD"])
        if ok_email and ok_password:
            session["admin"] = True
            session.permanent = True
            return redirect(url_for("main.admin_dashboard"))
        flash("Credenciales administrativas inválidas.", "error")
    return render_template("admin_login.html")


@bp.post("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("main.index"))


def get_admin_rows(db):
    group_numbers = [
        r["group_no"]
        for r in db.execute(
            "SELECT DISTINCT group_no FROM students WHERE active=1 ORDER BY group_no"
        ).fetchall()
    ]

    groups = []
    for group_no in group_numbers:
        members = db.execute(
            "SELECT name,email FROM students WHERE group_no=? AND active=1 ORDER BY name",
            (group_no,),
        ).fetchall()
        a = db.execute(
            """SELECT a.*, t.title, t.platform, t.protocols, t.network
               FROM assignments a JOIN topics t ON t.code=a.topic_code
               WHERE a.group_no=?""",
            (group_no,),
        ).fetchone()
        groups.append({"group_no": group_no, "members": members, "assignment": a})
    return groups


def _admin_payload():
    groups = get_admin_rows(get_db())
    assigned_count = sum(1 for x in groups if x["assignment"])
    total_groups = len(groups)
    payload_groups = []
    for item in groups:
        a = item["assignment"]
        payload_groups.append({
            "group_no": item["group_no"],
            "members": [m["name"].title() for m in item["members"]],
            "assigned": bool(a),
            "topic": a["title"] if a else "",
            "platform": a["platform"] if a else "",
            "claimed_by": a["claimed_by_name"].title() if a else "",
            "assigned_at": _format_assignment_time(a["assigned_at"]) if a else "",
        })
    return {
        "assigned_count": assigned_count,
        "total_groups": total_groups,
        "groups": payload_groups,
    }


@bp.get("/admin")
@admin_required
def admin_dashboard():
    data = _admin_payload()
    return render_template(
        "admin.html",
        groups=get_admin_rows(get_db()),
        assigned_count=data["assigned_count"],
        total_groups=data["total_groups"],
    )


@bp.get("/admin/api/status")
def admin_status():
    if not session.get("admin"):
        return jsonify({"ok": False, "reason": "session_expired"}), 401
    payload = _admin_payload()
    payload["ok"] = True
    return jsonify(payload)


@bp.post("/admin/sincronizar-matriz")
@admin_required
def sync_matrix():
    path = current_app.config.get("STUDENTS_XLSX")
    if not path:
        flash("No hay una ruta STUDENTS_XLSX configurada.", "error")
        return redirect(url_for("main.admin_dashboard"))
    try:
        count = import_students_xlsx(path, current_app.config["DATABASE"])
        total_groups = get_db().execute(
            "SELECT COUNT(DISTINCT group_no) AS c FROM students WHERE active=1"
        ).fetchone()["c"]
        flash(f"Matriz sincronizada: {count} estudiantes en {total_groups} grupos activos.", "info")
    except Exception as exc:
        flash(f"No fue posible sincronizar la matriz: {exc}", "error")
    return redirect(url_for("main.admin_dashboard"))


def _pdf_page(canvas, doc):
    width, height = landscape(A4)
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#03101D"))
    canvas.rect(0, 0, width, height, fill=1, stroke=0)

    canvas.setFillColor(colors.HexColor("#00D9FF"))
    canvas.rect(0, height - 8, width, 8, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor("#FFAE00"))
    canvas.rect(0, 0, width, 4, fill=1, stroke=0)

    canvas.setStrokeColor(colors.HexColor("#174D72"))
    canvas.setLineWidth(0.7)
    canvas.line(28, 24, width - 28, 24)

    canvas.setFillColor(colors.HexColor("#7897B5"))
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(28, 12, "PROYECTO ORIGEN · INTERNET: Redes y Comunicaciones IP")
    canvas.drawRightString(width - 28, 12, f"Página {doc.page}")

    canvas.setTitle("PROYECTO ORIGEN - Asignación Proyecto Final")
    canvas.setAuthor("PROYECTO ORIGEN · Universidad de Ibagué")
    canvas.setCreator("ORIGEN · Panel docente")
    canvas.setSubject("Asignación de temas del proyecto final")
    canvas.restoreState()


@bp.get("/admin/exportar.pdf")
@admin_required
def export_pdf():
    groups = get_admin_rows(get_db())
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=28,
        leftMargin=28,
        topMargin=34,
        bottomMargin=34,
        title="PROYECTO ORIGEN - Asignación Proyecto Final",
        author="PROYECTO ORIGEN · Universidad de Ibagué",
        subject="Asignación de temas del proyecto final",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "OrigenTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=21,
        leading=25,
        textColor=colors.HexColor("#F3F8FF"),
        alignment=TA_CENTER,
        spaceAfter=2,
    )
    accent_style = ParagraphStyle(
        "OrigenAccent",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#00D9FF"),
        alignment=TA_CENTER,
    )
    subtitle_style = ParagraphStyle(
        "OrigenSub",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#A8BAD0"),
        alignment=TA_CENTER,
    )
    cell = ParagraphStyle(
        "cell",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=7.2,
        leading=9,
        textColor=colors.HexColor("#E6F0FA"),
    )
    cell_bold = ParagraphStyle(
        "cellBold",
        parent=cell,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#FFFFFF"),
    )
    pending = ParagraphStyle(
        "pending",
        parent=cell_bold,
        textColor=colors.HexColor("#FFD16B"),
    )

    now = datetime.now(BOGOTA).strftime("%d/%m/%Y · %H:%M")
    story = [
        Paragraph("PROYECTO ORIGEN", accent_style),
        Paragraph("Asignación del Proyecto Final", title_style),
        Paragraph("Servicios de capa de aplicación · DataCenter VLAN 40", subtitle_style),
        Paragraph(f"Consolidado docente · generado {now} (America/Bogota)", subtitle_style),
        Spacer(1, 14),
    ]

    headers = ["Grupo", "Integrantes", "Tema asignado", "Plataforma", "Protocolos", "Asignado por", "Fecha"]
    data = [[Paragraph(h, cell_bold) for h in headers]]

    for g in groups:
        members = "<br/>".join(m["name"].title() for m in g["members"]) or "Sin matriz"
        a = g["assignment"]
        if a:
            row = [
                Paragraph(str(g["group_no"]), cell_bold),
                Paragraph(members, cell),
                Paragraph(a["title"], cell_bold),
                Paragraph(a["platform"], cell),
                Paragraph(a["protocols"], cell),
                Paragraph(a["claimed_by_name"].title(), cell),
                Paragraph(_format_assignment_time(a["assigned_at"]), cell),
            ]
        else:
            row = [
                Paragraph(str(g["group_no"]), cell_bold),
                Paragraph(members, cell),
                Paragraph("PENDIENTE", pending),
                Paragraph("—", cell),
                Paragraph("—", cell),
                Paragraph("—", cell),
                Paragraph("—", cell),
            ]
        data.append(row)

    table = Table(data, colWidths=[36, 146, 154, 116, 91, 118, 92], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0D2949")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#00D9FF")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#174D72")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#071A2E"), colors.HexColor("#0A223B")]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "La asignación queda registrada cuando el primer integrante autorizado de cada grupo confirma su selección.",
        subtitle_style,
    ))

    doc.build(story, onFirstPage=_pdf_page, onLaterPages=_pdf_page)
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="PROYECTO_ORIGEN_Asignacion_Proyecto_Final.pdf",
    )
