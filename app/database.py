import sqlite3
import os
from datetime import datetime

DB_PATH = os.environ.get("DATABASE_URL", "sena.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Enable Write-Ahead Logging (WAL) for better concurrent read/write support
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Settings table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    # Users table (stores OAuth tokens and credentials)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        email TEXT PRIMARY KEY,
        access_token TEXT NOT NULL,
        refresh_token TEXT,
        token_uri TEXT NOT NULL,
        client_id TEXT NOT NULL,
        client_secret TEXT NOT NULL,
        scopes TEXT NOT NULL,
        expiry TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    # Rules table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_email TEXT NOT NULL,
        name TEXT NOT NULL,
        rule_type TEXT NOT NULL, -- 'from', 'to', 'from_subject', 'subject_keywords', 'verification_cleaner'
        condition_sender TEXT,
        condition_recipient TEXT,
        condition_subject TEXT, -- for subject_keywords, stored as comma-separated or single string
        target_label TEXT NOT NULL,
        remove_from_inbox INTEGER DEFAULT 1, -- 1 = True, 0 = False
        remove_from_important INTEGER DEFAULT 1,
        active INTEGER DEFAULT 1,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_email) REFERENCES users (email) ON DELETE CASCADE
    )
    """)

    # Super Wichtig contacts table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS super_wichtig_contacts (
        user_email TEXT NOT NULL,
        contact_email TEXT NOT NULL,
        source TEXT NOT NULL, -- 'auto' or 'manual'
        added_at TEXT NOT NULL,
        PRIMARY KEY (user_email, contact_email),
        FOREIGN KEY (user_email) REFERENCES users (email) ON DELETE CASCADE
    )
    """)

    # Deleted Super Wichtig contacts table (keeps track of contacts user explicitly removed)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS deleted_super_wichtig_contacts (
        user_email TEXT NOT NULL,
        contact_email TEXT NOT NULL,
        deleted_at TEXT NOT NULL,
        PRIMARY KEY (user_email, contact_email),
        FOREIGN KEY (user_email) REFERENCES users (email) ON DELETE CASCADE
    )
    """)

    # Processing logs table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS processing_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_email TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        message TEXT NOT NULL,
        status TEXT NOT NULL, -- 'success', 'warning', 'error', 'info'
        FOREIGN KEY (user_email) REFERENCES users (email) ON DELETE CASCADE
    )
    """)

    conn.commit()
    conn.close()

# --- Settings Helpers ---

def get_setting(key, default=None):
    conn = get_db_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key, value):
    conn = get_db_connection()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

# --- Users Helpers ---

def save_user(email, access_token, refresh_token, token_uri, client_id, client_secret, scopes, expiry):
    conn = get_db_connection()
    now_str = datetime.now().isoformat()
    
    # If refresh_token is not provided, try to preserve the existing one
    if not refresh_token:
        existing = conn.execute("SELECT refresh_token FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            refresh_token = existing["refresh_token"]

    conn.execute("""
    INSERT OR REPLACE INTO users (
        email, access_token, refresh_token, token_uri, client_id, client_secret, scopes, expiry, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (email, access_token, refresh_token, token_uri, client_id, client_secret, scopes, expiry, now_str))
    conn.commit()
    conn.close()

def get_user(email):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_users():
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM users").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_user(email):
    conn = get_db_connection()
    conn.execute("DELETE FROM users WHERE email = ?", (email,))
    conn.commit()
    conn.close()

# --- Rules Helpers ---

def add_rule(user_email, name, rule_type, condition_sender, condition_recipient, condition_subject, target_label, remove_from_inbox, remove_from_important):
    conn = get_db_connection()
    now_str = datetime.now().isoformat()
    conn.execute("""
    INSERT INTO rules (
        user_email, name, rule_type, condition_sender, condition_recipient, condition_subject, 
        target_label, remove_from_inbox, remove_from_important, active, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
    """, (user_email, name, rule_type, condition_sender, condition_recipient, condition_subject, 
          target_label, int(remove_from_inbox), int(remove_from_important), now_str))
    conn.commit()
    conn.close()

def get_rules(user_email):
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM rules WHERE user_email = ? ORDER BY id DESC", (user_email,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_rule(rule_id, user_email):
    conn = get_db_connection()
    conn.execute("DELETE FROM rules WHERE id = ? AND user_email = ?", (rule_id, user_email))
    conn.commit()
    conn.close()

def toggle_rule(rule_id, user_email, active):
    conn = get_db_connection()
    conn.execute("UPDATE rules SET active = ? WHERE id = ? AND user_email = ?", (int(active), rule_id, user_email))
    conn.commit()
    conn.close()

# --- Super Wichtig Helpers ---

def add_super_wichtig_contact(user_email, contact_email, source="auto"):
    conn = get_db_connection()
    now_str = datetime.now().isoformat()
    email_clean = contact_email.lower().strip()
    try:
        # If manually added or auto-added, remove from the deleted list in case they re-add it
        conn.execute("DELETE FROM deleted_super_wichtig_contacts WHERE user_email = ? AND contact_email = ?", (user_email, email_clean))
        conn.execute("""
        INSERT OR IGNORE INTO super_wichtig_contacts (user_email, contact_email, source, added_at)
        VALUES (?, ?, ?, ?)
        """, (user_email, email_clean, source, now_str))
        conn.commit()
    except sqlite3.Error:
        pass
    finally:
        conn.close()

def get_super_wichtig_contacts(user_email):
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM super_wichtig_contacts WHERE user_email = ? ORDER BY contact_email ASC", (user_email,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_super_wichtig_contact(user_email, contact_email):
    conn = get_db_connection()
    email_clean = contact_email.lower().strip()
    now_str = datetime.now().isoformat()
    # Delete from active contacts
    conn.execute("DELETE FROM super_wichtig_contacts WHERE user_email = ? AND contact_email = ?", (user_email, email_clean))
    # Insert or ignore into deleted contacts so it's not auto-added again
    conn.execute("""
    INSERT OR IGNORE INTO deleted_super_wichtig_contacts (user_email, contact_email, deleted_at)
    VALUES (?, ?, ?)
    """, (user_email, email_clean, now_str))
    conn.commit()
    conn.close()

def is_deleted_super_wichtig_contact(user_email, contact_email):
    conn = get_db_connection()
    email_clean = contact_email.lower().strip()
    row = conn.execute("SELECT 1 FROM deleted_super_wichtig_contacts WHERE user_email = ? AND contact_email = ?", (user_email, email_clean)).fetchone()
    conn.close()
    return row is not None

# --- Logs Helpers ---

def add_log(user_email, message, status="info"):
    conn = get_db_connection()
    now_str = datetime.now().isoformat()
    conn.execute("""
    INSERT INTO processing_logs (user_email, timestamp, message, status)
    VALUES (?, ?, ?, ?)
    """, (user_email, now_str, message, status))
    # Keep only the last 200 logs per user to prevent database bloat
    conn.execute("""
    DELETE FROM processing_logs WHERE id IN (
        SELECT id FROM processing_logs WHERE user_email = ? ORDER BY id DESC LIMIT -1 OFFSET 200
    )
    """, (user_email,))
    conn.commit()
    conn.close()

def get_logs(user_email, limit=50):
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM processing_logs WHERE user_email = ? ORDER BY id DESC LIMIT ?", (user_email, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
