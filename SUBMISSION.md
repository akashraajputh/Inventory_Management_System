StockFlow — Take-Home Submission
================================

This document contains responses and artifacts for the three parts of the take-home.

Part 1 — Code Review & Debugging
--------------------------------

Problem snippet (original):

app.route('/api/products', methods=['POST'])
def create_product():
    data = request.json
    product = Product(name=data['name'], sku=data['sku'], price=data['price'], warehouse_id=data['warehouse_id'])
    db.session.add(product)
    db.session.commit()
    inventory = Inventory(product_id=product.id, warehouse_id=data['warehouse_id'], quantity=data['initial_quantity'])
    db.session.add(inventory)
    db.session.commit()
    return {"message": "Product created", "product_id": product.id}

Issues found (technical & business) and impact:

- Missing input validation (KeyError/TypeError risk). Impact: 500 errors, malformed data.
- SKU uniqueness not enforced/handled. Impact: duplicates or IntegrityError -> 500.
- Price handled as float — should use Decimal/NUMERIC. Impact: rounding errors for money.
- Two separate commits (non-atomic). Impact: product created without inventory on partial failure.
- No authorization/ownership check for `warehouse_id`. Impact: cross-company corruption/security issue.
- Inventory uniqueness (product_id,warehouse_id) not handled/checked (duplicates). Impact: incorrect stock totals.
- `initial_quantity` assumed present. Impact: KeyError or null insertion.
- No negative-value checks (price, quantity). Impact: invalid business data.
- No error handling for DB exceptions. Impact: uncaught exceptions/500s.
- No inventory change audit/logging. Impact: cannot trace inventory history.
- No status codes or consistent JSON responses.
- Concurrency concerns when two requests create same SKU simultaneously.

Fix summary and rationale:

- Validate JSON body and required fields; check types and non-negative constraints.
- Use Decimal for price and database NUMERIC to avoid float errors.
- Create product and inventory in the same transaction (atomic commit) to avoid partial state.
- Handle IntegrityError for SKU uniqueness and return 409.
- Upsert inventory (or abort) to avoid duplicate inventory rows; create `InventoryChange` audit entry.
- Check that `warehouse_id` exists and belongs to requesting company (authorization placeholder included).
- Return JSON with proper HTTP status (201 on success, 400/409 on client errors).

Corrected endpoint (high-level):

- Validate inputs (name, sku, price -> Decimal, warehouse_id, initial_quantity default 0).
- Ensure warehouse exists and permission checks (placeholder).
- Add product, flush to get id, upsert inventory, insert InventoryChange, commit.
- Catch IntegrityError, rollback, return 409 for SKU conflicts, 400 for other integrity issues.

Part 1 — Files changed

- `stockflow/app.py` — corrected `create_product` (atomic handling, validation, Decimal), added `InventoryChange` model and logging.

Part 2 — Database Design
-------------------------

Requirements recap (provided):
- Companies have multiple warehouses
- Products stored in multiple warehouses with different quantities
- Track when inventory levels change
- Suppliers provide products
- Some products are bundles

Schema (core tables):

- companies (id PK, name, created_at)
- warehouses (id PK, company_id FK -> companies.id, name, address)
- products (id PK, sku VARCHAR UNIQUE, name, description, price NUMERIC(12,4), product_type, low_stock_threshold)
- suppliers (id PK, name, contact_email, phone)
- product_suppliers (id PK, product_id FK, supplier_id FK, lead_time_days, is_primary)
- inventories (id PK, product_id FK, warehouse_id FK, quantity INT, updated_at, UNIQUE(product_id,warehouse_id))
- inventory_changes (id PK, product_id, warehouse_id, delta INT, reason, source_id, created_at)
- sales (id PK, company_id FK, created_at, total_amount, status)
- sale_items (id PK, sale_id FK, product_id FK, warehouse_id, quantity, unit_price, created_at)
- product_bundles (bundle_id FK -> products.id, component_id FK -> products.id, qty, PK(bundle_id, component_id))

Design decisions & justification:

- `products.sku` unique across platform to meet requirement.
- Price stored as NUMERIC(12,4) to avoid floating errors.
- `inventories` unique(product_id,warehouse_id) prevents duplicate rows and simplifies stock calculation.
- `inventory_changes` stores an immutable audit log of every inventory delta.
- `sale_items` indexed by (product_id, created_at) to efficiently query recent sales activity for alerts.
- `product_suppliers` supports multiple suppliers with `is_primary` and `lead_time_days` to aid reorder logic.

Gaps & questions for product team (assumptions to confirm):

- Are SKUs global across the platform? (Assumed: yes.)
- Are products global or per-company? (Assumed: platform-level catalog with company warehouses referencing products.)
- How should bundles behave on sale? Consume component stocks? (Assumed: bundles are virtual and selling a bundle reduces component stock.)
- Thresholds: per-product or per-warehouse? (Assumed: per-product with ability to override per warehouse later.)
- Definition of "recent sales activity" (days window) and rolling average window for consumption rate (used 90 and 30 days respectively).
- Should we track reserved vs available stock for unshipped orders? (Not implemented; recommended.)
- Should timestamps be timezone-aware? (Recommend UTC.)

Part 3 — Low-stock Alerts API
-----------------------------

Endpoint implemented: `GET /api/companies/{company_id}/alerts/low-stock`

Business rules implemented (assumptions documented):

- Low stock threshold varies by product: uses product.low_stock_threshold (fallback DEFAULT_THRESHOLD = 10).
- Only alert for products with recent sales activity: defined as at least one `SaleItem` in last `RECENT_SALES_DAYS` (assumed 90 days).
- Must handle multiple warehouses per company: inventories are per-warehouse and return alerts per warehouse.
- Include primary supplier info for reordering where available.
- Compute `days_until_stockout` = ceil(current_stock / avg_daily_sales) using average sales over last `AVG_SALES_WINDOW_DAYS` (assumed 30 days). If avg_daily_sales == 0 then `days_until_stockout` is null.

Important implementation notes:

- The endpoint joins `inventories` and `products`, filters for warehouses belonging to the target `company_id`.
- Filters out products with no recent sales (business rule).
- Computes average daily sales per product using `sale_items` over last 30 days when available.
- Picks the `ProductSupplier` marked `is_primary` if present; otherwise uses the first supplier found.

Edge cases handled:

- No recent sales => product excluded from alerts.
- avg_daily_sales == 0 => days_until_stockout = null.
- Missing supplier => supplier field null.
- Multiple warehouses => separate alert per (product, warehouse) row.

Part 3 — Files changed / added

- `stockflow/app.py` — `low_stock_alerts` route implementation; sample seed data added.
- `stockflow/tests/test_api.py` and `stockflow/tests/test_api_edgecases.py` — tests that exercise alert logic, happy path and edge cases.

How to run (local dev)
-----------------------

1. Create venv and install deps:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Run tests:

```powershell
python -m pytest -q
```

3. Run dev server (seeds sample data on startup):

```powershell
python run_server.py
```

4. Example endpoints:

GET alerts:
`GET http://127.0.0.1:5000/api/companies/1/alerts/low-stock`

Create product (example):
`POST http://127.0.0.1:5000/api/products` with JSON body {name, sku, price, warehouse_id, initial_quantity}

Assumptions summary
-------------------

- SKUs are unique globally across the platform.
- Products are global (catalog) and warehouses belong to companies.
- Recent sales window = 90 days; average sales window = 30 days (used to estimate days_until_stockout).
- Bundles are represented in `product_bundles` and consuming bundles reduces component stock (not fully implemented in example).
- No reserved stock tracking implemented; available stock equals inventory.quantity.

Deliverables in repository (path: `stockflow/`)

- `app.py` — main Flask app and models
- `run_server.py` — run & seed helper
- `run_dev.ps1` — PowerShell helper
- `requirements.txt` — dependencies
- `tests/` — pytest tests
- `README.md` — quick start and curl examples
- `SUBMISSION.md` — this document

If you want:
- I can add GitHub Actions CI to run tests automatically on PRs/pushes.
- I can expand bundle handling, reserved inventory, or add authentication/authorization.

End of submission.
