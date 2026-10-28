from sqlalchemy import text

from incidentiq.database import engine


def main() -> None:
    with engine.connect() as connection:
        result = connection.execute(text("SELECT current_database(), version()"))
        database_name, version = result.one()

    print(f"Connected to database: {database_name}")
    print(f"PostgreSQL: {version}")


if __name__ == "__main__":
    main()