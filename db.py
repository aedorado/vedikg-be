"""PostgreSQL database connection management using psycopg3."""

import psycopg
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("POSTGRES_URL")
if not DATABASE_URL:
    raise ValueError("POSTGRES_URL environment variable not set")


def get_conn():
    """Get a new PostgreSQL connection."""
    return psycopg.connect(DATABASE_URL)


def execute_query(query: str, params: dict | tuple | None = None, fetch: bool = False) -> list | None:
    """Execute a query and optionally fetch results."""
    conn = get_conn()
    cursor = conn.cursor()
    try:
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        
        if fetch:
            result = cursor.fetchall()
            conn.commit()
            return result
        else:
            conn.commit()
            return None
    finally:
        cursor.close()
        conn.close()


def execute_many(query: str, params_list: list[dict | tuple]) -> None:
    """Execute multiple queries with different parameters."""
    conn = get_conn()
    cursor = conn.cursor()
    try:
        for params in params_list:
            if isinstance(params, dict):
                cursor.execute(query, params)
            else:
                cursor.execute(query, params)
        conn.commit()
    finally:
        cursor.close()
        conn.close()
