import os
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()
ADMINS = {1607498152, 5174581416}

TOKEN = os.getenv("DEV_TOKEN")

K_FACTOR = float(os.getenv("K_FACTOR", "1.0"))
RECENT_QUEUE_LIMIT = int(os.getenv("RECENT_QUEUE_LIMIT", "5"))
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "10"))
WEIGHT_HISTORY_LIMIT_PER_STUDENT = int(os.getenv("WEIGHT_HISTORY_LIMIT_PER_STUDENT", "10"))

DB_NAME = os.getenv("DB_NAME", "students.db")

MIN_WEIGHT_THRESHOLD = float(os.getenv("MIN_WEIGHT_THRESHOLD", "0.0001"))
WEIGHT_MIN_LIMIT = float(os.getenv("WEIGHT_MIN_LIMIT", "0.1"))
WEIGHT_MAX_LIMIT = float(os.getenv("WEIGHT_MAX_LIMIT", "10.0"))