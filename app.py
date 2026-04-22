from flask import Flask, request, jsonify, send_from_directory
import os
import random
import psycopg2
import psycopg2.extras
from urllib.parse import urlparse

app = Flask(__name__, static_folder='static')

# ─── DB CONNECTION ──────────────────────────────────────────────────────────────

def get_conn():
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise RuntimeError("DATABASE_URL non défini.")
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id      VARCHAR(4) PRIMARY KEY,
                    name    VARCHAR(100) NOT NULL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS entries (
                    user_id VARCHAR(4)   NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    day     VARCHAR(10)  NOT NULL,
                    feeling VARCHAR(10)  NOT NULL,
                    PRIMARY KEY (user_id, day)
                );
            """)
        conn.commit()

# ─── HELPERS ────────────────────────────────────────────────────────────────────

VALID_FEELINGS = {'triste', 'neutre', 'joyeux'}
VALID_DAYS     = {'Lundi','Mardi','Mercredi','Jeudi','Vendredi','Samedi','Dimanche'}

def generate_unique_id(cur):
    for _ in range(100):
        new_id = str(random.randint(1000, 9999))
        cur.execute("SELECT 1 FROM users WHERE id = %s", (new_id,))
        if not cur.fetchone():
            return new_id
    raise RuntimeError("Impossible de générer un ID unique.")

def get_entries_dict(cur, user_id):
    cur.execute("SELECT day, feeling FROM entries WHERE user_id = %s", (user_id,))
    return {row[0]: row[1] for row in cur.fetchall()}

# ─── ROUTES ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/auth', methods=['POST'])
def auth():
    body = request.json
    mode = body.get('mode')

    if mode == 'new':
        name = body.get('name', '').strip()
        if not name:
            return jsonify({'error': 'Nom invalide'}), 400
        with get_conn() as conn:
            with conn.cursor() as cur:
                user_id = generate_unique_id(cur)
                cur.execute("INSERT INTO users (id, name) VALUES (%s, %s)", (user_id, name))
            conn.commit()
        return jsonify({'id': user_id, 'name': name, 'is_new': True})

    elif mode == 'existing':
        user_id = str(body.get('id', '')).strip()
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name FROM users WHERE id = %s", (user_id,))
                row = cur.fetchone()
                if not row:
                    return jsonify({'error': 'ID introuvable'}), 404
                entries = get_entries_dict(cur, user_id)
        return jsonify({'id': user_id, 'name': row[0], 'entries': entries, 'is_new': False})

    return jsonify({'error': 'Mode invalide'}), 400

@app.route('/api/entry', methods=['POST'])
def add_entry():
    body    = request.json
    user_id = str(body.get('id', ''))
    day     = body.get('day')
    feeling = body.get('feeling')

    if feeling not in VALID_FEELINGS or day not in VALID_DAYS:
        return jsonify({'error': 'Données invalides'}), 400

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE id = %s", (user_id,))
            if not cur.fetchone():
                return jsonify({'error': 'Utilisateur introuvable'}), 404
            cur.execute("""
                INSERT INTO entries (user_id, day, feeling)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, day) DO UPDATE SET feeling = EXCLUDED.feeling
            """, (user_id, day, feeling))
            entries = get_entries_dict(cur, user_id)
        conn.commit()
    return jsonify({'success': True, 'entries': entries})

@app.route('/api/entry', methods=['DELETE'])
def delete_entry():
    body    = request.json
    user_id = str(body.get('id', ''))
    day     = body.get('day')

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE id = %s", (user_id,))
            if not cur.fetchone():
                return jsonify({'error': 'Utilisateur introuvable'}), 404
            cur.execute("DELETE FROM entries WHERE user_id = %s AND day = %s", (user_id, day))
            entries = get_entries_dict(cur, user_id)
        conn.commit()
    return jsonify({'success': True, 'entries': entries})

@app.route('/api/entries/<user_id>', methods=['GET'])
def get_entries(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({'error': 'Utilisateur introuvable'}), 404
            entries = get_entries_dict(cur, user_id)
    return jsonify({'entries': entries, 'name': row[0]})

# ─── INIT ───────────────────────────────────────────────────────────────────────

# Appelé au démarrage Gunicorn ET en dev
try:
    init_db()
except Exception as e:
    print(f"[init_db] Skipped: {e}")

if __name__ == '__main__':
    os.makedirs('static', exist_ok=True)
    app.run(debug=True, port=5000)
