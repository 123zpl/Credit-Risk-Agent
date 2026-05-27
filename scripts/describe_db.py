"""Print all tables and columns in the database."""
from src.database import get_db
from sqlalchemy import text

with get_db() as session:
    tables = [r[0] for r in session.execute(text("SHOW TABLES")).fetchall()]
    print("=== TABLES ===")
    for t in tables:
        print(" ", t)
    print()
    for t in tables:
        desc = session.execute(text(f"DESCRIBE `{t}`")).fetchall()
        print(f"=== {t} ({len(desc)} cols) ===")
        for c in desc:
            print(f"  {c[0]:35} {c[1]}")
        # Row count
        cnt = session.execute(text(f"SELECT COUNT(*) FROM `{t}`")).scalar()
        print(f"  -> {cnt} rows")
        print()
