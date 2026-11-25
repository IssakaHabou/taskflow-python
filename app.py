"""
TaskFlow (version Python / Flask) - TP Cloud Computing INP-HB.

- Base par défaut : SQLite (fichier taskflow.db), aucune installation.
- PostgreSQL / MySQL : définir DATABASE_URL, ou les variables DB_HOST, DB_PORT,
  DB_NAME, DB_USERNAME, DB_PASSWORD (+ DB_ENGINE=postgresql|mysql).
- Compatible Python 3.8+ (PythonClusters propose 3.8 / 3.10).
"""
import os
import platform
import socket
import sys
import time
from datetime import date, datetime, timedelta
from importlib.metadata import version as pkg_version
from urllib.parse import quote_plus

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text


# ---------------------------------------------------------------- configuration
def load_env_file(path):
    """Charge un fichier .env simple (CLE=valeur) sans dépendance externe."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_env_file(os.path.join(BASE_DIR, ".env"))


def database_url():
    url = os.environ.get("DATABASE_URL")
    if url:
        # Certains hébergeurs fournissent "postgres://", SQLAlchemy attend "postgresql://"
        return url.replace("postgres://", "postgresql://", 1)
    host = os.environ.get("DB_HOST")
    if host:
        engine = os.environ.get("DB_ENGINE", "postgresql")
        driver = {"postgresql": "postgresql+psycopg2", "mysql": "mysql+pymysql"}[engine]
        default_port = "5432" if engine == "postgresql" else "3306"
        return "{}://{}:{}@{}:{}/{}".format(
            driver,
            quote_plus(os.environ.get("DB_USERNAME", "postgres")),
            quote_plus(os.environ.get("DB_PASSWORD", "")),
            host,
            os.environ.get("DB_PORT", default_port),
            os.environ.get("DB_NAME", "postgres"),
        )
    return "sqlite:///" + os.path.join(BASE_DIR, "taskflow.db")


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "taskflow-dev-key-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = database_url()
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True, "pool_recycle": 280}
app.config["JSON_AS_ASCII"] = False
db = SQLAlchemy(app)
START_TIME = time.time()

STATUSES = [("A_FAIRE", "À faire"), ("EN_COURS", "En cours"), ("TERMINEE", "Terminée")]
PRIORITIES = [("BASSE", "Basse"), ("MOYENNE", "Moyenne"), ("HAUTE", "Haute")]
STATUS_LABELS = dict(STATUSES)
PRIORITY_LABELS = dict(PRIORITIES)


# ---------------------------------------------------------------- modèle
class Task(db.Model):
    __tablename__ = "tasks_py"  # table distincte de la version Java si même base

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(1000))
    status = db.Column(db.String(20), nullable=False, default="A_FAIRE")
    priority = db.Column(db.String(20), nullable=False, default="MOYENNE")
    due_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def overdue(self):
        return self.due_date is not None and self.status != "TERMINEE" and self.due_date < date.today()

    @property
    def status_label(self):
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def priority_label(self):
        return PRIORITY_LABELS.get(self.priority, self.priority)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "priority": self.priority,
            "dueDate": self.due_date.isoformat() if self.due_date else None,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
            "overdue": self.overdue,
        }


# ---------------------------------------------------------------- utilitaires
def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def validate(data):
    """Valide un dictionnaire de champs ; renvoie (valeurs_propres, erreurs)."""
    errors = {}
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip() or None
    status = data.get("status") or "A_FAIRE"
    priority = data.get("priority") or "MOYENNE"
    if not title:
        errors["title"] = "Le titre est obligatoire"
    elif len(title) > 120:
        errors["title"] = "120 caractères maximum"
    if description and len(description) > 1000:
        errors["description"] = "1000 caractères maximum"
    if status not in STATUS_LABELS:
        errors["status"] = "Statut invalide"
    if priority not in PRIORITY_LABELS:
        errors["priority"] = "Priorité invalide"
    raw_due = data.get("dueDate", data.get("due_date"))
    due = parse_date(raw_due)
    if raw_due and due is None:
        errors["dueDate"] = "Date invalide (AAAA-MM-JJ)"
    clean = {"title": title, "description": description, "status": status,
             "priority": priority, "due_date": due}
    return clean, errors


def stats():
    result = {"total": Task.query.count()}
    for code, _ in STATUSES:
        result[code] = Task.query.filter_by(status=code).count()
    return result


def seed_demo_data():
    if os.environ.get("DEMO_DATA", "true").lower() != "true" or Task.query.count() > 0:
        return
    today = date.today()
    demo = [
        ("Créer le service web Render", "Blueprint render.yaml, plan Free, Python 3.10.", "TERMINEE", "HAUTE", 0),
        ("Déployer TaskFlow Flask", "Pousser le code sur GitHub, Render construit et lance Gunicorn.", "EN_COURS", "HAUTE", 1),
        ("Connecter PostgreSQL", "Renseigner DB_HOST, DB_PORT, DB_NAME, DB_USERNAME, DB_PASSWORD.", "A_FAIRE", "MOYENNE", 2),
        ("Comparer Java et Python en PaaS", "Temps de démarrage, mémoire, simplicité du déploiement.", "A_FAIRE", "BASSE", 7),
    ]
    for title, desc, status, prio, days in demo:
        db.session.add(Task(title=title, description=desc, status=status, priority=prio,
                            due_date=today + timedelta(days=days)))
    db.session.commit()


with app.app_context():
    db.create_all()
    seed_demo_data()


@app.context_processor
def inject_globals():
    return {"statuses": STATUSES, "priorities": PRIORITIES}


# ---------------------------------------------------------------- pages web
@app.route("/")
def index():
    current = request.args.get("status")
    if current not in STATUS_LABELS:
        current = None
    query = Task.query
    if current:
        query = query.filter_by(status=current)
    tasks = query.order_by(Task.created_at.desc(), Task.id.desc()).all()
    return render_template("index.html", tasks=tasks, stats=stats(), current=current,
                           current_label=STATUS_LABELS.get(current))


@app.route("/tasks/new")
def new_task():
    return render_template("form.html", task=None, values={}, errors={})


@app.route("/tasks/<int:task_id>/edit")
def edit_task(task_id):
    task = db.session.get(Task, task_id) or abort(404)
    values = {"title": task.title, "description": task.description or "", "status": task.status,
              "priority": task.priority, "dueDate": task.due_date.isoformat() if task.due_date else ""}
    return render_template("form.html", task=task, values=values, errors={})


@app.route("/tasks", methods=["POST"])
def save_task():
    task_id = request.form.get("id")
    clean, errors = validate(request.form)
    task = db.session.get(Task, int(task_id)) if task_id else None
    if task_id and task is None:
        abort(404)
    if errors:
        return render_template("form.html", task=task, values=request.form, errors=errors), 400
    if task is None:
        db.session.add(Task(**clean))
        flash("Tâche créée.")
    else:
        for key, value in clean.items():
            setattr(task, key, value)
        flash("Tâche mise à jour.")
    db.session.commit()
    return redirect(url_for("index"))


@app.route("/tasks/<int:task_id>/status", methods=["POST"])
def change_status(task_id):
    task = db.session.get(Task, task_id) or abort(404)
    value = request.form.get("value")
    if value in STATUS_LABELS:
        task.status = value
        db.session.commit()
    return redirect(url_for("index"))


@app.route("/tasks/<int:task_id>/delete", methods=["POST"])
def delete_task(task_id):
    task = db.session.get(Task, task_id) or abort(404)
    db.session.delete(task)
    db.session.commit()
    flash("Tâche supprimée.")
    return redirect(url_for("index"))


def database_info():
    try:
        dialect = db.engine.dialect.name
        if dialect == "postgresql":
            version = db.session.execute(text("SHOW server_version")).scalar()
            return "PostgreSQL " + str(version)
        if dialect == "mysql":
            return "MySQL " + str(db.session.execute(text("SELECT VERSION()")).scalar())
        if dialect == "sqlite":
            return "SQLite " + str(db.session.execute(text("SELECT sqlite_version()")).scalar())
        return dialect
    except Exception as exc:  # noqa: BLE001
        return "indisponible ({})".format(exc.__class__.__name__)


@app.route("/plateforme")
def platform_page():
    uptime = int(time.time() - START_TIME)
    info = [
        ("Version Python", "{} ({})".format(platform.python_version(), platform.python_implementation())),
        ("Framework", "Flask " + pkg_version("flask")),
        ("Serveur WSGI", os.environ.get("SERVER_SOFTWARE") or request.environ.get("SERVER_SOFTWARE", "uWSGI / Gunicorn")),
        ("Système d'exploitation", "{} {} / {}".format(platform.system(), platform.release(), platform.machine())),
        ("Nom d'hôte (conteneur)", socket.gethostname()),
        ("Processeurs disponibles", str(os.cpu_count())),
        ("PID du processus", str(os.getpid())),
        ("Base de données", database_info()),
        ("Moteur SQLAlchemy", db.engine.dialect.name),
        ("Temps de fonctionnement", "{} h {:02d} min {:02d} s".format(uptime // 3600, uptime % 3600 // 60, uptime % 60)),
    ]
    return render_template("plateforme.html", info=info)


# ---------------------------------------------------------------- API REST
@app.route("/api/tasks", methods=["GET"])
def api_list():
    status = request.args.get("status")
    query = Task.query
    if status:
        if status not in STATUS_LABELS:
            return jsonify({"error": "Statut invalide"}), 400
        query = query.filter_by(status=status)
    return jsonify([t.to_dict() for t in query.order_by(Task.created_at.desc(), Task.id.desc()).all()])


@app.route("/api/tasks/stats", methods=["GET"])
def api_stats():
    return jsonify(stats())


@app.route("/api/tasks/<int:task_id>", methods=["GET"])
def api_get(task_id):
    task = db.session.get(Task, task_id)
    if task is None:
        return jsonify({"error": "Tâche introuvable : {}".format(task_id)}), 404
    return jsonify(task.to_dict())


@app.route("/api/tasks", methods=["POST"])
def api_create():
    clean, errors = validate(request.get_json(silent=True) or {})
    if errors:
        return jsonify(errors), 400
    task = Task(**clean)
    db.session.add(task)
    db.session.commit()
    return jsonify(task.to_dict()), 201, {"Location": "/api/tasks/{}".format(task.id)}


@app.route("/api/tasks/<int:task_id>", methods=["PUT"])
def api_update(task_id):
    task = db.session.get(Task, task_id)
    if task is None:
        return jsonify({"error": "Tâche introuvable : {}".format(task_id)}), 404
    clean, errors = validate(request.get_json(silent=True) or {})
    if errors:
        return jsonify(errors), 400
    for key, value in clean.items():
        setattr(task, key, value)
    db.session.commit()
    return jsonify(task.to_dict())


@app.route("/api/tasks/<int:task_id>/status", methods=["PATCH"])
def api_status(task_id):
    task = db.session.get(Task, task_id)
    if task is None:
        return jsonify({"error": "Tâche introuvable : {}".format(task_id)}), 404
    value = request.args.get("value")
    if value not in STATUS_LABELS:
        return jsonify({"error": "Statut invalide"}), 400
    task.status = value
    db.session.commit()
    return jsonify(task.to_dict())


@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
def api_delete(task_id):
    task = db.session.get(Task, task_id)
    if task is None:
        return jsonify({"error": "Tâche introuvable : {}".format(task_id)}), 404
    db.session.delete(task)
    db.session.commit()
    return "", 204


@app.route("/health")
def health():
    try:
        db.session.execute(text("SELECT 1"))
        db_status = {"status": "UP", "database": db.engine.dialect.name}
        code = 200
    except Exception as exc:  # noqa: BLE001
        db_status = {"status": "DOWN", "error": exc.__class__.__name__}
        code = 503
    return jsonify({"status": "UP" if code == 200 else "DOWN", "components": {"db": db_status},
                    "python": sys.version.split()[0]}), code


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
