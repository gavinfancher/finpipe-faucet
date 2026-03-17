"""
Postgres helpers for per-user ticker persistence.
"""

import os

import asyncpg

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/finpipe")

_pool: asyncpg.Pool | None = None


async def init():
    global _pool
    _pool = await asyncpg.create_pool(DATABASE_URL)
    async with _pool.acquire() as conn:
        await conn.execute("""
            create table if not exists users (
                id      serial primary key,
                username varchar(32) unique not null
            )
        """)
        await conn.execute("""
            create table if not exists user_tickers (
                user_id integer not null references users(id) on delete cascade,
                ticker  varchar(10) not null,
                primary key (user_id, ticker)
            )
        """)


async def close():
    if _pool:
        await _pool.close()


async def get_user_tickers(username: str) -> list[str]:
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            select t.ticker
            from user_tickers t
            join users u on u.id = t.user_id
            where u.username = $1
            order by t.ticker
            """,
            username,
        )
    return [r["ticker"] for r in rows]


async def add_user_ticker(username: str, ticker: str) -> list[str]:
    async with _pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "insert into users (username) values ($1) on conflict (username) do nothing",
                username,
            )
            user_id = await conn.fetchval(
                "select id from users where username = $1", username
            )
            await conn.execute(
                "insert into user_tickers (user_id, ticker) values ($1, $2) on conflict do nothing",
                user_id,
                ticker,
            )
    return await get_user_tickers(username)


async def remove_user_ticker(username: str, ticker: str) -> list[str]:
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            delete from user_tickers t
            using users u
            where u.id = t.user_id and u.username = $1 and t.ticker = $2
            """,
            username,
            ticker,
        )
    return await get_user_tickers(username)


async def get_all_tickers() -> list[str]:
    """Union of every ticker across all users — used for warm startup."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "select distinct ticker from user_tickers order by ticker"
        )
    return [r["ticker"] for r in rows]
