from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from math import ceil

from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError

# Minimal Flask app with SQLAlchemy models and the required endpoints.

db = SQLAlchemy()


def create_app(db_uri=None):
    app = Flask(__name__)
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_DATABASE_URI'] = db_uri or 'sqlite:///stockflow_example.db'
    db.init_app(app)

    with app.app_context():
        db.create_all()

    register_routes(app)
    return app


### Models

class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)


class Warehouse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(128), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Numeric(12, 4), nullable=True)
    product_type = db.Column(db.String(50), default='standard')
    low_stock_threshold = db.Column(db.Integer, nullable=True)


class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    contact_email = db.Column(db.String(255))


class ProductSupplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    lead_time_days = db.Column(db.Integer)
    is_primary = db.Column(db.Boolean, default=False)


class Inventory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('product_id', 'warehouse_id', name='uq_inventory_product_warehouse'),)


class InventoryChange(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, nullable=False)
    warehouse_id = db.Column(db.Integer, nullable=False)
    delta = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SaleItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'))
    quantity = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


### Routes

def register_routes(app):

    @app.route('/api/products', methods=['POST'])
    def create_product():
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'error': 'invalid_json'}), 400

        name = data.get('name')
        sku = data.get('sku')
        price_raw = data.get('price')
        warehouse_id = data.get('warehouse_id')
        initial_quantity = data.get('initial_quantity', 0)

        if not name or not sku:
            return jsonify({'error': 'name_and_sku_required'}), 400
        if warehouse_id is None:
            return jsonify({'error': 'warehouse_id_required'}), 400

        # Validate price as Decimal
        price = None
        if price_raw is not None:
            try:
                price = Decimal(str(price_raw))
            except (InvalidOperation, TypeError):
                return jsonify({'error': 'invalid_price'}), 400
            if price < 0:
                return jsonify({'error': 'price_must_be_non_negative'}), 400

        # Validate quantity
        try:
            qty = int(initial_quantity)
        except (TypeError, ValueError):
            return jsonify({'error': 'invalid_initial_quantity'}), 400
        if qty < 0:
            return jsonify({'error': 'initial_quantity_non_negative'}), 400

        # Ensure warehouse exists
        warehouse = db.session.get(Warehouse, warehouse_id)
        if not warehouse:
            return jsonify({'error': 'warehouse_not_found'}), 404

        try:
            # create product and inventory in the same logical flow
            product = Product(name=name, sku=sku, price=price)
            db.session.add(product)
            db.session.flush()  # get product.id

            existing = db.session.query(Inventory).filter_by(product_id=product.id, warehouse_id=warehouse_id).one_or_none()
            if existing:
                existing.quantity = existing.quantity + qty
                existing.updated_at = datetime.utcnow()
                inventory = existing
            else:
                inventory = Inventory(product_id=product.id, warehouse_id=warehouse_id, quantity=qty)
                db.session.add(inventory)

            change = InventoryChange(product_id=product.id, warehouse_id=warehouse_id, delta=qty, reason='initial_stock')
            db.session.add(change)

            db.session.commit()
            return jsonify({'message': 'Product created', 'product_id': product.id}), 201

        except IntegrityError as e:
            db.session.rollback()
            txt = str(e.orig) if getattr(e, 'orig', None) else str(e)
            if 'UNIQUE constraint' in txt or 'unique' in txt.lower():
                return jsonify({'error': 'sku_conflict'}), 409
            return jsonify({'error': 'db_integrity_error'}), 400
        except Exception:
            db.session.rollback()
            return jsonify({'error': 'internal_error'}), 500


    @app.route('/api/companies/<int:company_id>/alerts/low-stock', methods=['GET'])
    def low_stock_alerts(company_id):
        # Business rules (assumptions):
        # - Only products with sales in last RECENT_SALES_DAYS are considered
        # - Threshold uses product.low_stock_threshold if set, otherwise DEFAULT_THRESHOLD
        RECENT_SALES_DAYS = 90
        AVG_SALES_WINDOW_DAYS = 30
        DEFAULT_THRESHOLD = 10

        # Fetch warehouses for the company
        warehouses = db.session.query(Warehouse).filter_by(company_id=company_id).all()
        if not warehouses:
            return jsonify({'alerts': [], 'total_alerts': 0}), 200
        warehouse_ids = [w.id for w in warehouses]
        warehouse_map = {w.id: w.name for w in warehouses}

        now = datetime.utcnow()
        recent_cutoff = now - timedelta(days=RECENT_SALES_DAYS)
        avg_cutoff = now - timedelta(days=AVG_SALES_WINDOW_DAYS)

        # Join inventories with products and threshold
        inv_q = db.session.query(
            Inventory.product_id,
            Inventory.warehouse_id,
            Inventory.quantity,
            Product.name.label('product_name'),
            Product.sku.label('sku'),
            db.func.coalesce(Product.low_stock_threshold, DEFAULT_THRESHOLD).label('threshold')
        ).join(Product, Product.id == Inventory.product_id).filter(Inventory.warehouse_id.in_(warehouse_ids)).subquery()

        # Products with recent sales
        recent_products_q = db.session.query(SaleItem.product_id).filter(SaleItem.created_at >= recent_cutoff).distinct().subquery()

        candidates = db.session.query(inv_q).join(recent_products_q, recent_products_q.c.product_id == inv_q.c.product_id).filter(inv_q.c.quantity < inv_q.c.threshold).all()

        product_ids = list({c.product_id for c in candidates})

        # Avg sales per product over AVG_SALES_WINDOW_DAYS
        avg_sales = {}
        if product_ids:
            sales_agg = db.session.query(
                SaleItem.product_id,
                db.func.sum(SaleItem.quantity).label('sum_qty')
            ).filter(SaleItem.product_id.in_(product_ids), SaleItem.created_at >= avg_cutoff).group_by(SaleItem.product_id).all()
            for row in sales_agg:
                avg_daily = float(row.sum_qty) / float(AVG_SALES_WINDOW_DAYS)
                avg_sales[row.product_id] = avg_daily

        # Supplier map (pick primary if available)
        suppliers_map = {}
        if product_ids:
            ps = db.session.query(ProductSupplier, Supplier).join(Supplier, Supplier.id == ProductSupplier.supplier_id).filter(ProductSupplier.product_id.in_(product_ids)).order_by(ProductSupplier.product_id, db.desc(ProductSupplier.is_primary)).all()
            for ps_row, supplier in ps:
                pid = ps_row.product_id
                if pid not in suppliers_map:
                    suppliers_map[pid] = {'id': supplier.id, 'name': supplier.name, 'contact_email': supplier.contact_email}

        alerts = []
        for c in candidates:
            pid = c.product_id
            avg_daily = avg_sales.get(pid, 0)
            days_until = None
            if avg_daily and avg_daily > 0:
                days_until = int(ceil(c.quantity / avg_daily))

            alerts.append({
                'product_id': pid,
                'product_name': c.product_name,
                'sku': c.sku,
                'warehouse_id': c.warehouse_id,
                'warehouse_name': warehouse_map.get(c.warehouse_id),
                'current_stock': int(c.quantity),
                'threshold': int(c.threshold),
                'days_until_stockout': days_until,
                'supplier': suppliers_map.get(pid)
            })

        return jsonify({'alerts': alerts, 'total_alerts': len(alerts)}), 200


### Helpers to seed sample data for tests/demo

def seed_sample_data(app):
    with app.app_context():
        db.session.query(InventoryChange).delete()
        db.session.query(Inventory).delete()
        db.session.query(SaleItem).delete()
        db.session.query(ProductSupplier).delete()
        db.session.query(Supplier).delete()
        db.session.query(Product).delete()
        db.session.query(Warehouse).delete()
        db.session.query(Company).delete()
        db.session.commit()

        company = Company(name='ACME Corp')
        db.session.add(company)
        db.session.flush()

        wh = Warehouse(company_id=company.id, name='Main Warehouse')
        db.session.add(wh)
        db.session.flush()

        # Supplier
        sup = Supplier(name='Supplier Corp', contact_email='orders@supplier.com')
        db.session.add(sup)
        db.session.flush()

        # Product with low stock
        p1 = Product(sku='WID-001', name='Widget A', price=Decimal('12.50'), low_stock_threshold=20)
        db.session.add(p1)
        db.session.flush()

        ps = ProductSupplier(product_id=p1.id, supplier_id=sup.id, lead_time_days=7, is_primary=True)
        db.session.add(ps)

        inv = Inventory(product_id=p1.id, warehouse_id=wh.id, quantity=5)
        db.session.add(inv)

        # Recent sale to qualify for alert
        sale = SaleItem(product_id=p1.id, warehouse_id=wh.id, quantity=30, created_at=datetime.utcnow() - timedelta(days=5))
        db.session.add(sale)

        db.session.commit()


if __name__ == '__main__':
    app = create_app()
    print('Created app with DB at', app.config['SQLALCHEMY_DATABASE_URI'])
