import csv
import pytest
from app import main
from scripts.import_catalog import import_csv


def test_csv_import_idempotent(client, tmp_path):
    csv_path=tmp_path / "good.csv"
    csv_path.write_text("sku,title,description,price_cents,stock\nABC,Good,Desc,201,3\n")
    assert import_csv(csv_path,"demo") == 1
    assert import_csv(csv_path,"demo") == 1
    with main.conn() as db:
        assert db.execute("SELECT COUNT(*) FROM products WHERE tenant_id='demo' AND sku='ABC'").fetchone()[0] == 1


def test_csv_import_rolls_back(client, tmp_path):
    csv_path=tmp_path / "bad.csv"
    csv_path.write_text("sku,title,description,price_cents,stock\nGOOD,Good,Desc,201,3\nBAD,Bad,Desc,-9,2\n")
    with pytest.raises(ValueError):
        import_csv(csv_path, "demo")
    with main.conn() as db:
        assert db.execute("SELECT 1 FROM products WHERE tenant_id='demo' AND sku='GOOD'").fetchone() is None
