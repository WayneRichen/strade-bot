import logging
from logging.handlers import TimedRotatingFileHandler
import os
from dotenv import load_dotenv
import builtins

load_dotenv()

# Log 目錄
LOG_DIR = os.getenv("LOG_DIR", "./logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Log 檔案路徑
LOG_FILE = os.path.join(LOG_DIR, "app.log")

# 建立 logger（全域使用）
logger = logging.getLogger("app_logger")
logger.setLevel(logging.INFO)

# ---- Handler 1：輸出到終端（讓你看到 print 類似效果） ----
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# ---- Handler 2：每天自動切割 log 檔案 ----
file_handler = TimedRotatingFileHandler(
    LOG_FILE, when="midnight", interval=1, encoding="utf-8"
)
file_handler.setLevel(logging.INFO)
file_handler.suffix = "%Y-%m-%d"  # 會變成 app.log.2025-11-27

env = os.getenv("APP_ENV", "local")

# Log 格式
formatter = logging.Formatter(
    f"[%(asctime)s] {env}.%(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

# 確保不重複加入 handler
if not logger.handlers:
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)


def log(msg):
    """你可用 log('xxx')，或直接 print('xxx') 都會被上面捕捉"""
    logger.info(msg)


# 備份原本的 print
original_print = print

def print(*args, **kwargs):
    message = " ".join(str(x) for x in args)
    logger.info(message)
    original_print(*args, **kwargs)  # 還是要照樣印到 console

builtins.print = print
