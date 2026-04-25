from flask import Flask, request, jsonify, send_from_directory
import os
import random
import sqlite3
import hashlib
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

app = Flask(__name__, static_folder='static')
DB_PATH = os.environ.get('DB_PATH', 'mood.db')

MAIL_FROM    = os.environ.get('MAIL_FROM', '')
MAIL_PASS    = os.environ.get('MAIL_PASS', '')
MAIL_SMTP    = os.environ.get('MAIL_SMTP', 'smtp.gmail.com')
MAIL_PORT    = int(os.environ.get('MAIL_PORT', '587'))

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id       TEXT PRIMARY KEY,
                nom      TEXT NOT NULL,
                prenom   TEXT NOT NULL,
                email    TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                user_id    TEXT NOT NULL,
                week_start TEXT NOT NULL,
                day        TEXT NOT NULL,
                feeling    TEXT NOT NULL,
                PRIMARY KEY (user_id, week_start, day),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        conn.commit()

VALID_FEELINGS = {'triste', 'neutre', 'joyeux'}
VALID_DAYS     = {'Lundi','Mardi','Mercredi','Jeudi','Vendredi','Samedi','Dimanche'}

def generate_unique_id(conn):
    for _ in range(100):
        new_id = str(random.randint(1000, 9999))
        if not conn.execute("SELECT 1 FROM users WHERE id=?", (new_id,)).fetchone():
            return new_id
    raise RuntimeError("ID unique impossible")

def get_entries_dict(conn, user_id, week_start):
    rows = conn.execute(
        "SELECT day, feeling FROM entries WHERE user_id=? AND week_start=?",
        (user_id, week_start)
    ).fetchall()
    return {r['day']: r['feeling'] for r in rows}

def get_all_weeks(conn, user_id):
    rows = conn.execute(
        "SELECT DISTINCT week_start FROM entries WHERE user_id=? ORDER BY week_start DESC",
        (user_id,)
    ).fetchall()
    return [r['week_start'] for r in rows]

def send_email(to, subject, body):
    if not MAIL_FROM or not MAIL_PASS:
        print(f"[EMAIL] To:{to} Subject:{subject} Body:{body}")
        return True
    try:
        msg = MIMEText(body, 'plain', 'utf-8')
        msg['Subject'] = subject
        msg['From']    = MAIL_FROM
        msg['To']      = to
        with smtplib.SMTP(MAIL_SMTP, MAIL_PORT) as s:
            s.starttls()
            s.login(MAIL_FROM, MAIL_PASS)
            s.sendmail(MAIL_FROM, to, msg.as_string())
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/register', methods=['POST'])
def register():
    b = request.json
    nom    = b.get('nom','').strip()
    prenom = b.get('prenom','').strip()
    email  = b.get('email','').strip().lower()
    pw     = b.get('password','').strip()

    if not all([nom, prenom, email, pw]):
        return jsonify({'error': 'Tous les champs sont obligatoires'}), 400
    if len(pw) < 6:
        return jsonify({'error': 'Mot de passe trop court (6 caractères min)'}), 400
    if '@' not in email:
        return jsonify({'error': 'Adresse email invalide'}), 400

    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            return jsonify({'error': 'Email déjà utilisé'}), 409
        user_id = generate_unique_id(conn)
        conn.execute(
            "INSERT INTO users (id,nom,prenom,email,password) VALUES (?,?,?,?,?)",
            (user_id, nom, prenom, email, hash_pw(pw))
        )
        conn.commit()

    send_email(email,
        "Bienvenue sur Mood Tracker",
        f"Bonjour {prenom} {nom},\n\nVotre compte Mood Tracker a été créé.\nVotre identifiant : {user_id}\n\nBonne utilisation !")
    return jsonify({'id': user_id, 'nom': nom, 'prenom': prenom, 'email': email})

@app.route('/api/login', methods=['POST'])
def login():
    b = request.json
    nom    = b.get('nom','').strip()
    prenom = b.get('prenom','').strip()
    pw     = b.get('password','').strip()

    if not all([nom, prenom, pw]):
        return jsonify({'error': 'Tous les champs sont obligatoires'}), 400

    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE LOWER(nom)=LOWER(?) AND LOWER(prenom)=LOWER(?) AND password=?",
            (nom, prenom, hash_pw(pw))
        ).fetchone()
        if not row:
            return jsonify({'error': 'Nom, prénom ou mot de passe incorrect'}), 401
        weeks = get_all_weeks(conn, row['id'])
        week_start = current_week_start()
        entries = get_entries_dict(conn, row['id'], week_start)

    return jsonify({
        'id': row['id'], 'nom': row['nom'], 'prenom': row['prenom'],
        'email': row['email'], 'entries': entries, 'weeks': weeks,
        'week_start': week_start
    })

@app.route('/api/forgot', methods=['POST'])
def forgot():
    b = request.json
    email = b.get('email','').strip().lower()
    if not email:
        return jsonify({'error': 'Email requis'}), 400
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not row:
            return jsonify({'message': 'Si cet email existe, un message a été envoyé.'})
        send_email(email,
            "Récupération de mot de passe – Mood Tracker",
            f"Bonjour {row['prenom']} {row['nom']},\n\nVotre identifiant Mood Tracker est : {row['id']}\n\nPour des raisons de sécurité, nous ne pouvons pas vous renvoyer votre mot de passe. Veuillez contacter l'administrateur pour le réinitialiser.")
    return jsonify({'message': 'Si cet email existe, un message a été envoyé.'})

def current_week_start():
    today = datetime.now()
    monday = today - __import__('datetime').timedelta(days=today.weekday())
    return monday.strftime('%Y-%m-%d')

@app.route('/api/entry', methods=['POST'])
def add_entry():
    b       = request.json
    user_id = str(b.get('id',''))
    day     = b.get('day')
    feeling = b.get('feeling')
    week_start = b.get('week_start', current_week_start())

    if feeling not in VALID_FEELINGS or day not in VALID_DAYS:
        return jsonify({'error': 'Données invalides'}), 400

    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
            return jsonify({'error': 'Utilisateur introuvable'}), 404
        conn.execute("""
            INSERT INTO entries (user_id, week_start, day, feeling) VALUES (?,?,?,?)
            ON CONFLICT(user_id, week_start, day) DO UPDATE SET feeling=excluded.feeling
        """, (user_id, week_start, day, feeling))
        conn.commit()
        entries = get_entries_dict(conn, user_id, week_start)
        weeks   = get_all_weeks(conn, user_id)
    return jsonify({'success': True, 'entries': entries, 'weeks': weeks})

@app.route('/api/entry', methods=['DELETE'])
def delete_entry():
    b       = request.json
    user_id = str(b.get('id',''))
    day     = b.get('day')
    week_start = b.get('week_start', current_week_start())

    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
            return jsonify({'error': 'Utilisateur introuvable'}), 404
        conn.execute("DELETE FROM entries WHERE user_id=? AND week_start=? AND day=?",
                     (user_id, week_start, day))
        conn.commit()
        entries = get_entries_dict(conn, user_id, week_start)
        weeks   = get_all_weeks(conn, user_id)
    return jsonify({'success': True, 'entries': entries, 'weeks': weeks})

@app.route('/api/allweeks/<user_id>', methods=['GET'])
def get_all_weeks_route(user_id):
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
            return jsonify({'error': 'Utilisateur introuvable'}), 404
        weeks = get_all_weeks(conn, user_id)
    return jsonify({'weeks': weeks})

@app.route('/api/week/<user_id>/<week_start>', methods=['GET'])
def get_week(user_id, week_start):
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
            return jsonify({'error': 'Utilisateur introuvable'}), 404
        entries = get_entries_dict(conn, user_id, week_start)
    return jsonify({'entries': entries, 'week_start': week_start})

init_db()

if __name__ == '__main__':
    os.makedirs('static', exist_ok=True)
    app.run(debug=True, port=5000)
