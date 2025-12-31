import pytest

from app import create_app, db, seed_sample_data


@pytest.fixture
def client():
    # Use in-memory SQLite to avoid creating files in temporary directories
    db_uri = 'sqlite:///:memory:'
    app = create_app(db_uri)
    app.config['TESTING'] = True

    with app.app_context():
        db.create_all()
        seed_sample_data(app)

    with app.test_client() as client:
        yield client


def test_create_product_success(client):
    # Create a new product via endpoint
    payload = {
        'name': 'NewProd',
        'sku': 'NEW-001',
        'price': '9.99',
        'warehouse_id': 1,
        'initial_quantity': 10
    }
    r = client.post('/api/products', json=payload)
    assert r.status_code == 201
    body = r.get_json()
    assert 'product_id' in body


def test_create_product_duplicate_sku(client):
    # Attempt to create another product with existing SKU 'WID-001' seeded earlier
    payload = {'name': 'Dup', 'sku': 'WID-001', 'price': '5.00', 'warehouse_id': 1, 'initial_quantity': 1}
    r = client.post('/api/products', json=payload)
    assert r.status_code in (400, 409)


def test_low_stock_alerts(client):
    r = client.get('/api/companies/1/alerts/low-stock')
    assert r.status_code == 200
    body = r.get_json()
    assert 'alerts' in body
    assert body['total_alerts'] >= 1
    # Validate keys for first alert
    first = body['alerts'][0]
    expected_keys = {'product_id', 'product_name', 'sku', 'warehouse_id', 'warehouse_name', 'current_stock', 'threshold', 'days_until_stockout', 'supplier'}
    assert expected_keys.issubset(set(first.keys()))
