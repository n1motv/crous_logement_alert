#!/usr/bin/env python3
"""
Crous-logement_alert – version « 65 places, 4 h, 8-20 »
"""

import os
import re
import smtplib
import sqlite3
import textwrap
from contextlib import closing
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path
from typing import List

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    redirect,
    render_template_string,
    request,
    url_for,
)
from zoneinfo import ZoneInfo           # Python ≥3.9

# --------------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------------
load_dotenv()
TZ = ZoneInfo("Europe/Paris")

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "subscriptions.db"

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USER or "alert@example.com")

MAX_SUBSCRIBERS = 65
ALERT_COOLDOWN = timedelta(hours=12)

# --------------------------------------------------------------------------
# FLASK
# --------------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-me")

HTML_FORM = """
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Veille Logement CROUS</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body{
      background:linear-gradient(120deg,#b40404 0%,#c63030 30%,#f2f2f2 100%);
      min-height:100vh;
      display:flex;
      align-items:center;
      justify-content:center;
    }
    .card{
      max-width:420px;
      width:100%;
      border:0;
      border-radius:1rem;
    }
    h1{font-size:1.6rem;font-weight:700;color:#b40404;}
  </style>
  <link rel="stylesheet"
      href="https://cdn.jsdelivr.net/npm/choices.js/public/assets/styles/choices.min.css">
  <script defer
        src="https://cdn.jsdelivr.net/npm/choices.js/public/assets/scripts/choices.min.js"></script>

</head>
<body>
  <div class="card shadow-lg p-4">
    <h1 class="text-center mb-4">Alertes logements CROUS</h1>
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        <div class="alert alert-info">{{ messages[0] }}</div>
      {% endif %}
    {% endwith %}
    <form method="post" novalidate>
      <div class="mb-3">
        <label for="city" class="form-label">Ville</label>

        <!-- Notre select traditionnel — Choices lui injectera la barre de recherche -->
        <select id="city" name="city" class="form-select" required>
          <option value="" selected disabled>Choisissez une ville…</option>
        </select>
      </div>

      <div class="mb-3">
        <label for="email" class="form-label">Votre e-mail</label>
        <input type="email" id="email" name="email" class="form-control" placeholder="prenom.nom@example.com" required>
      </div>
      <button class="btn btn-danger w-100">M'abonner</button>
      <p class="text-center mt-3 mb-0 small text-muted">65 places au total · 1 inscription par e-mail</p>
    </form>
  </div>

<script>
fetch("/static/cities.json")
  .then(r => r.json())
  .then(data => {
    const sel = document.getElementById("city");

    // 1) On injecte les <option>
    data.cities
        .sort((a, b) => a.label.localeCompare(b.label, "fr"))
        .forEach(c => {
          const opt = document.createElement("option");
          opt.value = c.label;
          opt.textContent = c.label;
          sel.appendChild(opt);
        });

    // 2) On active Choices.js (recherche + tri alpha déjà faits)
    new Choices(sel, {
      searchPlaceholderValue: "Tapez pour filtrer…",
      shouldSort: false,            // déjà trié
      itemSelectText: "",           // enlève le petit texte « Press to select »
      allowHTML: false
    });
  })
  .catch(console.error);
</script>

</body>
</html>
"""

# --------------------------------------------------------------------------
# DATABASE
# --------------------------------------------------------------------------
def init_db():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                city  TEXT NOT NULL,
                last_alert TEXT
            )
            """
        )
        conn.commit()

def add_subscription(email: str, city: str) -> int | None:
    """Retourne l’ID de la souscription créée, None si refus (doublon ou quota)."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        if conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0] >= MAX_SUBSCRIBERS:
            return None
        try:
            cur = conn.execute(
                "INSERT INTO subscriptions (email, city) VALUES (?,?)",
                (email, city),
            )
            conn.commit()
            return cur.lastrowid            # ← ID SQL
        except sqlite3.IntegrityError:
            return None

def alert_now_if_needed(sub_id: int, email: str, city: str):
    """Envoie un e-mail et met à jour last_alert si un logement est dispo maintenant."""
    if has_crous_offer(city):
        send_email(email, city)
        update_last_alert(sub_id)


def get_subscriptions() -> List[tuple]:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.execute(
            "SELECT id, email, city, last_alert FROM subscriptions"
        )
        return cur.fetchall()

def update_last_alert(sub_id: int):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            "UPDATE subscriptions SET last_alert=? WHERE id=?",
            (datetime.now(TZ).isoformat(), sub_id),
        )
        conn.commit()
# --------------------------------------------------------------------------
# CROUS scraping (simplifié)
# --------------------------------------------------------------------------
SEARCH_URL_TEMPLATE = (
    "https://trouverunlogement.lescrous.fr/tools/{academy}/search"
)
CITY_REGEX = re.compile(r"\b({city})\b", re.IGNORECASE)
ACADEMIES = {
    "Grenoble": 41,
    "Lyon": 39,
    "Paris": 1,
    # compléter…
}
def city_to_academy(city: str) -> int:
    return ACADEMIES.get(city, 41)

def has_crous_offer(city: str) -> bool:
    url = SEARCH_URL_TEMPLATE.format(academy=city_to_academy(city))
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        app.logger.error("Réseau %s: %s", city, e)
        return False
    regex = CITY_REGEX.pattern.format(city=re.escape(city))
    return bool(re.search(regex, r.text, re.IGNORECASE))

# --------------------------------------------------------------------------
# EMAIL
# --------------------------------------------------------------------------
def send_email(to_addr: str, city: str):
    subject = f"Logements CROUS disponibles à {city} !"
    body = textwrap.dedent(f"""
        Bonjour,

        Bonne nouvelle ! Au moins un logement CROUS vient d'être repéré
        pour la ville de {city}.

        Détails : https://trouverunlogement.lescrous.fr/

        — Service d’alerte pour trouvé un logement CROUS
    """)
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = to_addr

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(msg)
    except Exception as exc:
        app.logger.error("Mail %s → %s", to_addr, exc)
    else:
        app.logger.info("Alerte envoyée à %s (%s)", to_addr, city)

# --------------------------------------------------------------------------
# SCHEDULER : 08 h, 12 h, 16 h, 20 h (Europe/Paris)
# --------------------------------------------------------------------------
def run_checks():
    now = datetime.now(TZ)
    for sub_id, email, city, last_alert in get_subscriptions():
        if last_alert:
            last = datetime.fromisoformat(last_alert)
            if now - last < ALERT_COOLDOWN:
                continue
        if has_crous_offer(city):
            send_email(email, city)
            update_last_alert(sub_id)

scheduler = BackgroundScheduler(timezone=TZ, daemon=True)
scheduler.add_job(
    run_checks,
    trigger="cron",
    hour="8,12,16,20",
    id="crous",
    max_instances=1,
)

# --------------------------------------------------------------------------
# ROUTES
# --------------------------------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        city  = request.form.get("city")
        email = request.form.get("email")

        if not city or not email:
            flash("Ville et e-mail obligatoires.")
            return redirect(url_for("index"))

        sub_id = add_subscription(email, city)
        if sub_id is None:
            flash("Inscription impossible : adresse déjà inscrite ou quota de 65 atteint.")
            return redirect(url_for("index"))

        # ⇒ nouvelle alerte immédiate si besoin
        alert_now_if_needed(sub_id, email, city)

        flash("Inscription validée ! Vous recevrez vos alertes (immédiatement si une offre existe, puis 08 h/12 h/16 h/20 h).")
        return redirect(url_for("index"))

    return render_template_string(HTML_FORM)

# --------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    scheduler.start()
    app.run(host="0.0.0.0", port=5000, debug=True)
