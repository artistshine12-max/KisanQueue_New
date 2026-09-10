import asyncio
import os
import sys

# Support psycopg async on Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:password@127.0.0.1:5432/kisanqueue"
)

async def main():
    engine = create_async_engine(
        DATABASE_URL,
        poolclass=NullPool,
    )
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
            await conn.execute(text("SELECT 2"))
        print(f"Database connectivity verified successfully!")
    except Exception as e:
        print(f"Connection test failed: {e}")
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
