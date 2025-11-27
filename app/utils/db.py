import pymysql
from pymysql.cursors import DictCursor
import os
from dotenv import load_dotenv

load_dotenv()

class DatabaseConnection:
    """讓你可以用 with get_db() as db 取得自動關閉的 MySQL 連線"""

    def __init__(self):
        self.conn = pymysql.connect(
            host=os.getenv("DB_HOST", "127.0.0.1"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USERNAME", "root"),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", "strade"),
            cursorclass=DictCursor,
            autocommit=True,
        )

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.conn.close()
        except:
            pass


def get_db():
    """用 with 自動 close connection"""
    return DatabaseConnection()


def query_one(db, sql, params=None):
    """查一筆"""
    with db.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()


def query_all(db, sql, params=None):
    """查多筆"""
    with db.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def execute(db, sql, params=None):
    """執行 INSERT/UPDATE/DELETE，不回傳 ID"""
    with db.cursor() as cursor:
        cursor.execute(sql, params)


def insert_and_get_id(db, sql, params=None):
    """執行 INSERT 並取回 lastrowid"""
    with db.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.lastrowid
