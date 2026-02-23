import sqlite3
from datetime import datetime

DB_NAME = "students.db"

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY,
            name TEXT,
            weight REAL DEFAULT 1.0,
            active INTEGER DEFAULT 1
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS current_queue (
            position INTEGER PRIMARY KEY,
            student_id INTEGER,
            is_priority INTEGER,
            is_late INTEGER,
            weight_at_generation REAL, -- Храним вес, который был ДО генерации
            FOREIGN KEY(student_id) REFERENCES students(id)
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS queue_metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)
        conn.commit()

def get_active_students():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, weight FROM students WHERE active=1")
        return cursor.fetchall()

def update_weight(student_id, new_weight):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE students SET weight=? WHERE id=?", (new_weight, student_id))
        conn.commit()

def reset_all_weights():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE students SET weight = 1.0")
        conn.commit()

def get_all_weights():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, weight FROM students ORDER BY weight DESC")
        return cursor.fetchall()

def get_full_list():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, active FROM students")
        return cursor.fetchall()

def toggle_student_status(student_id, status):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE students SET active=? WHERE id=?", (status, student_id))
        conn.commit()

def enable_all_students():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE students SET active = 1")
        conn.commit()

def save_queue_to_db(queue_with_meta):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM current_queue")
        for pos, item in enumerate(queue_with_meta, start=1):
            cursor.execute(
                """INSERT INTO current_queue 
                   (position, student_id, is_priority, is_late, weight_at_generation) 
                   VALUES (?, ?, ?, ?, ?)""",
                (pos, item['id'], item['is_priority'], item['is_late'], item['weight_before'])
            )
        conn.commit()
    update_queue_time()

def load_queue_from_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
         
        cursor.execute("""
            SELECT q.position, q.student_id, s.name, q.is_priority, q.is_late, q.weight_at_generation
            FROM current_queue q
            JOIN students s ON q.student_id = s.id
            ORDER BY q.position
        """)
        return cursor.fetchall()

def swap_queue_items(pos1, pos2):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT student_id, is_priority, is_late, weight_at_generation FROM current_queue WHERE position=?", (pos1,))
        s1 = cursor.fetchone()
        cursor.execute("SELECT student_id, is_priority, is_late, weight_at_generation FROM current_queue WHERE position=?", (pos2,))
        s2 = cursor.fetchone()
        
        if s1 and s2:
         
            cursor.execute("UPDATE current_queue SET student_id=?, is_priority=?, is_late=?, weight_at_generation=? WHERE position=?", 
                           (s2[0], s2[1], s2[2], s2[3], pos1))
            cursor.execute("UPDATE current_queue SET student_id=?, is_priority=?, is_late=?, weight_at_generation=? WHERE position=?", 
                           (s1[0], s1[1], s1[2], s1[3], pos2))
            conn.commit()
    update_queue_time()

def update_queue_time():
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO queue_metadata (key, value) VALUES ('last_update', ?)", (now,))
        conn.commit()

def get_queue_time():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM queue_metadata WHERE key='last_update'")
        result = cursor.fetchone()
        return result[0] if result else "неизвестно"