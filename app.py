from flask import Flask, request, jsonify, send_from_directory
import os
import random
import sqlite3

app = Flask(__name__, static_folder='static')

# Sur Railway, on utilise /data pour la persistance, sinon local
DB_PATH = os.environ.get('DB_PATH', 'mood.db')

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id   TEXT PRIMARY KEY,
                name TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                user_id TEXT NOT NULL,
                day     TEXT NOT NULL,
                feeling TEXT NOT NULL,
                PRIMARY KEY (user_id, day),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        conn.commit()

VALID_FEELINGS = {'triste', 'neutre', 'joyeux'}
VALID_DAYS     = {'Lundi','Mardi','Mercredi','Jeudi','Vendredi','Samedi','Dimanche'}

def generate_unique_id(conn):
    for _ in range(100):
        new_id = str(random.randint(1000, 9999))
        row = conn.execute("SELECT 1 FROM users WHERE id = ?", (new_id,)).fetchone()
        if not row:
            return new_id
    raise RuntimeError("Impossible de générer un ID unique.")

def get_entries_dict(conn, user_id):
    rows = conn.execute("SELECT day, feeling FROM entries WHERE user_id = ?", (user_id,)).fetchall()
    return {row['day']: row['feeling'] for row in rows}

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
            user_id = generate_unique_id(conn)
            conn.execute("INSERT INTO users (id, name) VALUES (?, ?)", (user_id, name))
            conn.commit()
        return jsonify({'id': user_id, 'name': name, 'is_new': True})

    elif mode == 'existing':
        user_id = str(body.get('id', '')).strip()
        with get_conn() as conn:
            row = conn.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row:
                return jsonify({'error': 'ID introuvable'}), 404
            entries = get_entries_dict(conn, user_id)
        return jsonify({'id': user_id, 'name': row['name'], 'entries': entries, 'is_new': False})

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
        row = conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return jsonify({'error': 'Utilisateur introuvable'}), 404
        conn.execute("""
            INSERT INTO entries (user_id, day, feeling) VALUES (?, ?, ?)
            ON CONFLICT(user_id, day) DO UPDATE SET feeling = excluded.feeling
        """, (user_id, day, feeling))
        conn.commit()
        entries = get_entries_dict(conn, user_id)
    return jsonify({'success': True, 'entries': entries})

@app.route('/api/entry', methods=['DELETE'])
def delete_entry():
    body    = request.json
    user_id = str(body.get('id', ''))
    day     = body.get('day')

    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return jsonify({'error': 'Utilisateur introuvable'}), 404
        conn.execute("DELETE FROM entries WHERE user_id = ? AND day = ?", (user_id, day))
        conn.commit()
        entries = get_entries_dict(conn, user_id)
    return jsonify({'success': True, 'entries': entries})

@app.route('/api/entries/<user_id>', methods=['GET'])
def get_entries(user_id):
    with get_conn() as conn:
        row = conn.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return jsonify({'error': 'Utilisateur introuvable'}), 404
        entries = get_entries_dict(conn, user_id)
    return jsonify({'entries': entries, 'name': row['name']})

init_db()

if __name__ == '__main__':
    os.makedirs('static', exist_ok=True)
    app.run(debug=True, port=5000)    
