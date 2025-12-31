StockFlow Example
=================

This is a minimal example of the StockFlow API used for a take-home assignment. It includes:

- a small Flask app with corrected `create_product` endpoint and a `low-stock` alerts endpoint
- SQLAlchemy models using SQLite for local testing
- pytest-based tests in `tests/`

Quick start (Windows PowerShell):

```powershell
cd e:/Bckden_eng/stockflow
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest -q
```

Files:
- `app.py` — Flask app, models, endpoints, and seed helpers
- `tests/test_api.py` — tests that exercise endpoints

Dev & CURL examples
--------------------

Run the dev server (will create the SQLite DB in the project folder):

```powershell
python run_server.py
```

Seed data is created by the server on startup (sample company, warehouse, supplier, product, sale).

Example curl requests:

Create product:

```powershell
curl -X POST http://127.0.0.1:5000/api/products -H "Content-Type: application/json" -d "{
	\"name\": \"NewProd\",\n  \"sku\": \"NEW-001\",\n  \"price\": \"9.99\",\n  \"warehouse_id\": 1,\n  \"initial_quantity\": 10
}"
```

Get low-stock alerts for company 1:

```powershell
curl http://127.0.0.1:5000/api/companies/1/alerts/low-stock
```

Notes:
- This is intentionally minimal and designed to be runnable locally to validate the endpoints and example dataset.
