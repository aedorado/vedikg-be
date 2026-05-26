#!/usr/bin/env python3
"""Simple migration runner for PostgreSQL."""

import psycopg
import os
import sys
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("POSTGRES_URL")
if not DATABASE_URL:
    raise ValueError("POSTGRES_URL environment variable not set")


def get_conn():
    """Get PostgreSQL connection."""
    return psycopg.connect(DATABASE_URL)


def ensure_migrations_table():
    """Create migrations table if it doesn't exist."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    cursor.close()
    conn.close()


def get_applied_migrations():
    """Get list of applied migrations."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute('SELECT version FROM schema_migrations ORDER BY version')
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [row[0] for row in rows]


def get_available_migrations():
    """Get list of available migrations in migrations/ directory."""
    migration_dir = os.path.join(os.path.dirname(__file__), 'migrations')
    migrations = []
    for file in sorted(os.listdir(migration_dir)):
        if file.endswith('.py') and file[0].isdigit():
            # Extract version from filename (e.g., "001_initial_schema.py" -> "001")
            version = file.split('_')[0]
            migrations.append((version, file))
    return migrations


def run_migration(version, filename, direction='upgrade'):
    """Run a single migration."""
    migration_dir = os.path.join(os.path.dirname(__file__), 'migrations')
    filepath = os.path.join(migration_dir, filename)
    
    # Import the migration module
    import importlib.util
    spec = importlib.util.spec_from_file_location("migration", filepath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    conn = get_conn()
    try:
        if direction == 'upgrade':
            print(f"  Applying migration {version}: {filename}...")
            module.upgrade(conn)
            cursor = conn.cursor()
            cursor.execute('INSERT INTO schema_migrations (version) VALUES (%s)', (version,))
            conn.commit()
            print(f"  ✓ Applied {version}")
        elif direction == 'downgrade':
            print(f"  Reverting migration {version}: {filename}...")
            module.downgrade(conn)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM schema_migrations WHERE version = %s', (version,))
            conn.commit()
            print(f"  ✓ Reverted {version}")
    except Exception as e:
        conn.rollback()
        print(f"  ✗ Error in {version}: {e}")
        raise
    finally:
        conn.close()


def main():
    """Main migration runner."""
    ensure_migrations_table()
    
    applied = set(get_applied_migrations())
    available = get_available_migrations()
    
    pending = [(v, f) for v, f in available if v not in applied]
    
    if not pending:
        print("✓ All migrations applied")
        return
    
    print(f"Running {len(pending)} pending migration(s)...")
    for version, filename in pending:
        run_migration(version, filename, 'upgrade')
    
    print("✓ All migrations applied successfully")


if __name__ == "__main__":
    main()
