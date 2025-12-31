import pytest

from app import create_app, db, seed_sample_data


@pytest.fixture
def client():
    app = create_app('sqlite:///:memory:')
    app.config['TESTING'] = True
    with app.app_context():
        db.create_all()
        seed_sample_data(app)

    with app.test_client() as client:
        yield client


def test_create_product_missing_fields(client):
    r = client.post('/api/products', json={'price': '1.00'})
    assert r.status_code == 400


def test_create_product_negative_price(client):
    payload = {'name': 'BadPrice', 'sku': 'BAD-001', 'price': '-5', 'warehouse_id': 1, 'initial_quantity': 1}
    r = client.post('/api/products', json=payload)
    assert r.status_code == 400


def test_create_product_negative_quantity(client):
    payload = {'name': 'BadQty', 'sku': 'BAD-002', 'price': '1.00', 'warehouse_id': 1, 'initial_quantity': -3}
    r = client.post('/api/products', json=payload)
    assert r.status_code == 400


def test_low_stock_no_recent_sales_excluded(client):
    # Create a product with low stock but no recent sales
    payload = {'name': 'NoSales', 'sku': 'NOSALE-001', 'price': '2.00', 'warehouse_id': 1, 'initial_quantity': 1}
    r = client.post('/api/products', json=payload)
    assert r.status_code == 201

    r2 = client.get('/api/companies/1/alerts/low-stock')
    body = r2.get_json()
    # product without recent sales should not create an alert
    assert all(alert['sku'] != 'NOSALE-001' for alert in body['alerts'])
