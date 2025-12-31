from app import create_app, seed_sample_data


def main():
    app = create_app('sqlite:///stockflow_dev.db')
    # Seed sample data if DB is empty
    with app.app_context():
        seed_sample_data(app)
    app.run(debug=True)


if __name__ == '__main__':
    main()
