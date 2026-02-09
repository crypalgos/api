
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.config.settings import settings

async def check_tables():
    print(f"Connecting to: {settings.database_url}")
    engine = create_async_engine(settings.database_url)
    
    async with engine.connect() as conn:
        print("\n--- Checking for 'users' table ---")
        try:
            result = await conn.execute(text("SELECT count(*) FROM users"))
            print(f"Users table exists. Count: {result.scalar()}")
        except Exception as e:
            print(f"Error querying users table: {e}")
            
        print("\n--- Checking for 'alembic_version' table ---")
        try:
            result = await conn.execute(text("SELECT * FROM alembic_version"))
            version = result.scalar()
            print(f"Alembic version: {version}")
        except Exception as e:
            print(f"Error querying alembic_version: {e}")

        print("\n--- Listing all tables ---")
        try:
            result = await conn.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            ))
            tables = result.fetchall()
            print("Tables found:")
            for table in tables:
                print(f" - {table[0]}")
        except Exception as e:
            print(f"Error listing tables: {e}")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(check_tables())
