"""Offline demo catalog importer. CSV headers: sku,title,description,price_cents,stock.

Run with DATABASE_PATH=... python -m scripts.import_catalog catalog.csv demo
Only for private trusted operator use; not an API or real ERP connector.
"""
import csv
import sys
from app.main import conn, init_db


def import_csv(path, tenant):
    init_db()
    count = 0
    with open(path, newline="", encoding="utf-8-sig") as source, conn() as db:
        reader = csv.DictReader(source)
        required = {"sku", "title", "description", "price_cents", "stock"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("CSV must contain: " + ",".join(sorted(required)))
        db.execute("BEGIN IMMEDIATE")
        try:
            if not db.execute("SELECT 1 FROM tenants WHERE id=?", (tenant,)).fetchone():
                raise ValueError("Unknown tenant")
            for row in reader:
                sku, title = row["sku"].strip(), row["title"].strip()
                price, stock = int(row["price_cents"]), int(row["stock"])
                if not sku or not title or len(sku) > 120 or len(title) > 250 or price < 0 or stock < 0:
                    raise ValueError(f"Invalid data on row {reader.line_num}")
                db.execute("INSERT INTO products(tenant_id,sku,title,description,price_cents,stock) VALUES (?,?,?,?,?,?) "
                           "ON CONFLICT(tenant_id,sku) DO UPDATE SET title=excluded.title, description=excluded.description, "
                           "price_cents=excluded.price_cents, stock=excluded.stock",
                           (tenant, sku, title, row["description"], price, stock))
                count += 1
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
    return count


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python -m scripts.import_catalog <csv-file> <tenant-id>")
    print("Imported", import_csv(sys.argv[1], sys.argv[2]), "products")
