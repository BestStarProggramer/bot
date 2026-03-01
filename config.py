import os
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()
ADMINS = {1607498152, 5174581416}


TOKEN = os.getenv("BOT_TOKEN")
# TOKEN = os.getenv("DEV_TOKEN")

K_FACTOR = float(os.getenv("K_FACTOR", "1.0"))
RECENT_QUEUE_LIMIT = int(os.getenv("RECENT_QUEUE_LIMIT", "5"))  # для каскадных пересчётов
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "10"))  # хранить последние N очередей
WEIGHT_HISTORY_LIMIT_PER_STUDENT = int(os.getenv("WEIGHT_HISTORY_LIMIT_PER_STUDENT", "10"))

DB_NAME = os.getenv("DB_NAME", "students.db")