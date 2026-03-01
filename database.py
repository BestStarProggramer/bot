import sqlite3
from datetime import datetime
from config import DB_NAME, HISTORY_LIMIT, WEIGHT_HISTORY_LIMIT_PER_STUDENT

def _connect():
    return sqlite3.connect(DB_NAME)

def init_db():
    with _connect() as conn:
        cur = conn.cursor()
        # students: текущий вес хранится в students.weight
        cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 1.0,
            active INTEGER NOT NULL DEFAULT 1
        )""")

        # queues: каждая сохранённая версия очереди (history)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS queues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            created_at TEXT,
            updated_at TEXT,
            change_log TEXT
        )""")

        # items внутри очереди: позиции начинаются с 1
        cur.execute("""
        CREATE TABLE IF NOT EXISTS queue_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            queue_id INTEGER NOT NULL,
            position INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            is_priority INTEGER NOT NULL DEFAULT 0,
            is_late INTEGER NOT NULL DEFAULT 0,
            weight_before REAL,
            weight_after REAL,
            FOREIGN KEY(queue_id) REFERENCES queues(id),
            FOREIGN KEY(student_id) REFERENCES students(id)
        )""")

        # история весов
        cur.execute("""
        CREATE TABLE IF NOT EXISTS weight_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            weight REAL NOT NULL,
            timestamp TEXT NOT NULL,
            place_info TEXT,
            FOREIGN KEY(student_id) REFERENCES students(id)
        )""")

        # простой key/value meta
        cur.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )""")
        conn.commit()
        # ensure legacy DBs get the new column
        _ensure_queue_items_has_is_added(cur)

def add_student(name, initial_weight=1.0, active=1):
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO students (name, weight, active) VALUES (?, ?, ?)", (name, initial_weight, active))
        conn.commit()
        return cur.lastrowid

def get_student_name(student_id):
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT name FROM students WHERE id=?", (student_id,))
        r = cur.fetchone()
        return r[0] if r else str(student_id)

def get_active_students():
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name, weight FROM students WHERE active=1")
        return cur.fetchall()  # list of tuples

def get_full_list():
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name, active FROM students ORDER BY id")
        return cur.fetchall()

def get_all_weights():
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT name, weight FROM students ORDER BY weight DESC")
        return cur.fetchall()

def update_weight(student_id, new_weight, place_info=None):
    ts = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE students SET weight=? WHERE id=?", (new_weight, student_id))
        cur.execute("INSERT INTO weight_history (student_id, weight, timestamp, place_info) VALUES (?, ?, ?, ?)",
                    (student_id, new_weight, ts, place_info))
        # keep only last WEIGHT_HISTORY_LIMIT_PER_STUDENT records per student
        cur.execute("""
            DELETE FROM weight_history WHERE id IN (
                SELECT id FROM weight_history WHERE student_id=? ORDER BY id DESC LIMIT -1 OFFSET ?
            )
        """, (student_id, WEIGHT_HISTORY_LIMIT_PER_STUDENT))
        conn.commit()

def get_weight_history(student_id, limit=10):
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT weight, timestamp, place_info FROM weight_history WHERE student_id=? ORDER BY id DESC LIMIT ?",
                    (student_id, limit))
        return cur.fetchall()

def enable_all_students():
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE students SET active=1")
        conn.commit()

def toggle_student_status(student_id, status):
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE students SET active=? WHERE id=?", (status, student_id))
        conn.commit()

# --- Queue CRUD and helpers ---

def create_queue_record(subject):
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO queues (subject, created_at, updated_at, change_log) VALUES (?, ?, ?, ?)",
                    (subject, now, now, f"Создана очередь '{subject}'"))
        conn.commit()
        qid = cur.lastrowid
        _enforce_queue_history_limit(cur)
        conn.commit()
        return qid

def _enforce_queue_history_limit(cur):
    # keep only last HISTORY_LIMIT queues (by id)
    cur.execute("SELECT COUNT(*) FROM queues")
    total = cur.fetchone()[0]
    if total > HISTORY_LIMIT:
        to_delete = total - HISTORY_LIMIT
        cur.execute("DELETE FROM queue_items WHERE queue_id IN (SELECT id FROM queues ORDER BY id ASC LIMIT ?)", (to_delete,))
        cur.execute("DELETE FROM queues WHERE id IN (SELECT id FROM queues ORDER BY id ASC LIMIT ?)", (to_delete,))

def add_queue_item(queue_id, position, student_id, is_priority, is_late, weight_before, weight_after=None):
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO queue_items
            (queue_id, position, student_id, is_priority, is_late, weight_before, weight_after, is_added)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
                    (queue_id, position, student_id, is_priority, is_late, weight_before, weight_after))
        conn.commit()
        return cur.lastrowid
    
def _ensure_queue_items_has_is_added(cur):
    cur.execute("PRAGMA table_info(queue_items)")
    cols = [r[1] for r in cur.fetchall()]
    if 'is_added' not in cols:
        cur.execute("ALTER TABLE queue_items ADD COLUMN is_added INTEGER NOT NULL DEFAULT 0")
        # no commit here; caller should commit

def get_recent_queues(limit=None):
    limit = limit or HISTORY_LIMIT
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, subject, created_at, updated_at, change_log FROM queues ORDER BY id DESC LIMIT ?", (limit,))
        return cur.fetchall()

def get_queue(queue_id):
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, subject, created_at, updated_at, change_log FROM queues WHERE id=?", (queue_id,))
        qmeta = cur.fetchone()
        if not qmeta:
            return None
        cur.execute("""
            SELECT position, student_id, is_priority, is_late, weight_before, weight_after, is_added
            FROM queue_items WHERE queue_id=? ORDER BY position
        """, (queue_id,))
        items = cur.fetchall()
        return {"meta": qmeta, "items": items}

def update_queue_timestamp_and_log(queue_id, log_text):
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE queues SET updated_at=?, change_log=? WHERE id=?", (now, log_text, queue_id))
        conn.commit()

def swap_queue_positions(queue_id, pos1, pos2):
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, student_id, is_priority, is_late, weight_before, weight_after FROM queue_items WHERE queue_id=? AND position=?",
                    (queue_id, pos1))
        r1 = cur.fetchone()
        cur.execute("SELECT id, student_id, is_priority, is_late, weight_before, weight_after, is_added FROM queue_items WHERE queue_id=? AND position=?",
                    (queue_id, pos2))
        r2 = cur.fetchone()
        if not r1 or not r2:
            raise ValueError("Invalid positions to swap")
        # swap student_id,is_priority,is_late,weight_before,weight_after,is_added between positions
        # r1 may have 6 or 7 columns depending on schema, normalize
        # fetch r1 with is_added as well
        cur.execute("SELECT id, student_id, is_priority, is_late, weight_before, weight_after, is_added FROM queue_items WHERE queue_id=? AND position=?", (queue_id, pos1))
        r1 = cur.fetchone()
        r2 = r2
        cur.execute("""
            UPDATE queue_items SET student_id=?, is_priority=?, is_late=?, weight_before=?, weight_after=?, is_added=? WHERE queue_id=? AND position=?
        """, (r2[1], r2[2], r2[3], r2[4], r2[5], r2[6] if len(r2) > 6 else 0, queue_id, pos1))
        cur.execute("""
            UPDATE queue_items SET student_id=?, is_priority=?, is_late=?, weight_before=?, weight_after=?, is_added=? WHERE queue_id=? AND position=?
        """, (r1[1], r1[2], r1[3], r1[4], r1[5], r1[6] if len(r1) > 6 else 0, queue_id, pos2))
        conn.commit()

def delete_queue_item(queue_id, position):
    with _connect() as conn:
        cur = conn.cursor()
        # remove the item
        cur.execute("SELECT student_id, weight_before, weight_after FROM queue_items WHERE queue_id=? AND position=?", (queue_id, position))
        row = cur.fetchone()
        if not row:
            raise ValueError("No such position")
        student_id, weight_before, weight_after = row
        cur.execute("DELETE FROM queue_items WHERE queue_id=? AND position=?", (queue_id, position))
        # shift up positions greater than deleted
        cur.execute("UPDATE queue_items SET position = position - 1 WHERE queue_id=? AND position > ?", (queue_id, position))
        conn.commit()
        return student_id, weight_before, weight_after

def add_student_to_existing_queue(queue_id, student_id, is_priority=0, is_late=0):
    with _connect() as conn:
        cur = conn.cursor()
        # find last position
        cur.execute("SELECT MAX(position) FROM queue_items WHERE queue_id=?", (queue_id,))
        last = cur.fetchone()[0] or 0
        # get student's current weight
        cur.execute("SELECT weight FROM students WHERE id=?", (student_id,))
        student_row = cur.fetchone()
        if not student_row:
            raise ValueError(f"Student {student_id} not found")
        w = student_row[0]
        cur.execute("""
            INSERT INTO queue_items (queue_id, position, student_id, is_priority, is_late, weight_before, weight_after, is_added)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """, (queue_id, last+1, student_id, is_priority, is_late, w, None))
        conn.commit()
        return last+1, w

def set_queue_item_weights(queue_id, pos, weight_before, weight_after):
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE queue_items SET weight_before=?, weight_after=? WHERE queue_id=? AND position=?
        """, (weight_before, weight_after, queue_id, pos))
        conn.commit()

def get_following_queue_ids(start_queue_id):
    with _connect() as conn:
        cur = conn.cursor()
        # queues with id greater than start_queue_id are considered "later"
        cur.execute("SELECT id FROM queues WHERE id > ? ORDER BY id ASC LIMIT ?", (start_queue_id, HISTORY_LIMIT))
        return [r[0] for r in cur.fetchall()]

def get_student_current_weight(student_id):
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT weight FROM students WHERE id=?", (student_id,))
        r = cur.fetchone()
        return r[0] if r else None

def set_student_weight_direct(student_id, new_weight):
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE students SET weight=? WHERE id=?", (new_weight, student_id))
        conn.commit()

def get_queue_by_index_from_latest(offset=0):
    # offset 0 = latest, 1 = previous, etc.
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM queues ORDER BY id DESC LIMIT 1 OFFSET ?", (offset,))
        r = cur.fetchone()
        return r[0] if r else None