import json
import pickle
import sqlite3

from config import DB_NAME

known_face_encodings = []
known_face_names = []


def setup_database():
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                encoding BLOB NOT NULL,
                role TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                user_id INTEGER PRIMARY KEY,
                history TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.commit()
        print("Database setup complete.")
    except sqlite3.Error as e:
        print(f"Database setup error: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def load_known_faces():
    global known_face_encodings, known_face_names
    known_face_encodings = []
    known_face_names = []
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT name, encoding FROM users")
        rows = cur.fetchall()
        for name, enc_blob in rows:
            known_face_names.append(name)
            known_face_encodings.append(pickle.loads(enc_blob))
        print(f"Loaded {len(known_face_names)} known faces from the database.")
    except sqlite3.Error as e:
        print(f"Database load error: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def add_new_user(name, encoding, role):
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        enc_blob = pickle.dumps(encoding)
        cur.execute(
            "INSERT INTO users (name, encoding, role) VALUES (?, ?, ?)",
            (name, enc_blob, role),
        )
        user_id = cur.lastrowid
        conn.commit()
        print(f"[DB] New user added (id={user_id})")
        print(f"[DB] Role stored: '{role}'")
        load_known_faces()
        return user_id
    except sqlite3.Error as e:
        print(f"Database insert error: {e}")
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_user_id_by_name(name):
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT id, role FROM users WHERE name = ?", (name,))
        row = cur.fetchone()
        return (row[0], row[1]) if row else (None, None)
    except sqlite3.Error as e:
        print(f"DB lookup error: {e}")
        return (None, None)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def load_conversation_history(user_id):
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT history FROM conversations WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row and row[0]:
            return json.loads(row[0])
        return []
    except sqlite3.Error as e:
        print(f"DB load convo error: {e}")
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def save_conversation_history(user_id, history):
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        hx = json.dumps(history)
        cur.execute(
            "INSERT OR REPLACE INTO conversations (user_id, history) VALUES (?, ?)",
            (user_id, hx),
        )
        conn.commit()
        print(f"[DB] Conversation saved for user ID {user_id}.")
    except sqlite3.Error as e:
        print(f"DB save convo error: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass
