"""
scripts/spikes/redshift_connect.py  — P0.7
--------------------------------------------
Spike: connect to Redshift, list permitted schemas, inspect order tables.
Decides: COPY vs INSERT load method; creates our schemas ONLY with user approval.

Run: python scripts/spikes/redshift_connect.py

IMPORTANT: This script is READ-ONLY. It does NOT create schemas or tables.
Schema creation happens in a separate task (P1.1) after user approval.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ingestion.common.config import get_settings
from ingestion.common.logging_utils import setup_logging
from ingestion.common.redshift import get_connection

setup_logging("INFO")


def main() -> None:
    cfg = get_settings()
    rs = cfg.redshift

    if not rs.is_configured():
        print("❌ REDSHIFT_* credentials not set in .env")
        sys.exit(1)

    print(f"\n⏳ Connecting to Redshift: {rs.host}:{rs.port}/{rs.db} as {rs.user} ...")

    try:
        conn = get_connection(rs.host, rs.port, rs.db, rs.user, rs.password)
    except Exception as exc:
        print(f"🔴 Connection FAILED: {exc}")
        sys.exit(1)

    print("✅ Connected!")

    with conn.cursor() as cur:
        # 1. List schemas we can see
        cur.execute("""
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_owner = current_user OR has_schema_privilege(current_user, schema_name, 'USAGE')
            ORDER BY schema_name
        """)
        schemas = [r[0] for r in cur.fetchall()]
        print(f"\n📂 Accessible schemas: {schemas}")

        # 2. Check if our schemas already exist
        our_schemas = ["raw_meta", "raw_mixpanel", "stg", "int", "mart", "ops"]
        existing = [s for s in our_schemas if s in schemas]
        missing = [s for s in our_schemas if s not in schemas]
        print(f"\n   Already exists: {existing}")
        print(f"   To create (needs approval): {missing}")

        # 3. Test S3 COPY capability
        if rs.iam_role_arn:
            print(f"\n✅ IAM role for COPY: {rs.iam_role_arn}")
            print("   → Load method: S3 COPY (preferred)")
        else:
            print("\n⚠️  REDSHIFT_IAM_ROLE_ARN not set → Load method: batched INSERT (slower)")
            print("   → Set IAM_ROLE_ARN for production use")

        # 4. Inspect candidate order tables
        # NOTE: table names are placeholders — user must provide actual names (Q7)
        candidate_tables = [
            ("public", "orders"),
            ("public", "order_items"),
            ("analytics", "orders"),
            ("analytics", "order_items"),
        ]
        print("\n📋 Checking candidate order tables (Q7 — update names as needed):")
        for schema, table in candidate_tables:
            try:
                cur.execute("""
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s
                    ORDER BY ordinal_position
                    LIMIT 20
                """, (schema, table))
                cols = cur.fetchall()
                if cols:
                    print(f"\n   ✅ {schema}.{table}:")
                    for col, dtype in cols:
                        print(f"      {col}: {dtype}")
                else:
                    print(f"   — {schema}.{table}: not found")
            except Exception:
                print(f"   — {schema}.{table}: not found or no access")

    conn.close()
    print("""
┌──────────────────────────────────────────────────────────────────────────────┐
│  P0.7 SPIKE COMPLETE — record the following in 03_CONTEXT.md:                │
│  • Accessible schemas                                                         │
│  • Load method chosen (COPY or INSERT)                                        │
│  • Actual order/order_items table names and key columns (answer to Q7)       │
│  • DO NOT run schema creation until user approves (separate P1.1 task)       │
└──────────────────────────────────────────────────────────────────────────────┘
""")


if __name__ == "__main__":
    main()
