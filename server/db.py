"""
Postgres helpers for per-user ticker persistence.
"""

import asyncpg

from server.config import DATABASE_URL

_pool: asyncpg.Pool | None = None


async def init():
    global _pool
    _pool = await asyncpg.create_pool(DATABASE_URL)
    async with _pool.acquire() as conn:
        await conn.execute("""
            create table if not exists users (
                id       serial primary key,
                username varchar(32) unique not null
            )
        """)
        await conn.execute("""
            alter table users add column if not exists password_hash text
        """)
        await conn.execute("""
            alter table users add column if not exists api_key_hash text
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




# --- auth ---

async def create_user(username: str, password_hash: str) -> bool:
    """Returns True if created, False if username already taken."""
    async with _pool.acquire() as conn:
        result = await conn.execute(
            "insert into users (username, password_hash) values ($1, $2) on conflict (username) do nothing",
            username,
            password_hash,
        )
    return result == "INSERT 0 1"


async def get_or_create_user(username: str):
    async with _pool.acquire() as conn:
        await conn.execute(
            "insert into users (username) values ($1) on conflict (username) do nothing",
            username,
        )


async def store_api_key(username: str, key_hash: str):
    async with _pool.acquire() as conn:
        await conn.execute(
            "update users set api_key_hash = $1 where username = $2",
            key_hash,
            username,
        )


async def get_username_by_api_key(key_hash: str) -> str | None:
    async with _pool.acquire() as conn:
        return await conn.fetchval(
            "select username from users where api_key_hash = $1", key_hash
        )


async def get_password_hash(username: str) -> str | None:
    async with _pool.acquire() as conn:
        return await conn.fetchval(
            "select password_hash from users where username = $1", username
        )


# --- tickers ---

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
        user_id = await conn.fetchval(
            "select id from users where username = $1", username
        )
        if user_id is None:
            raise ValueError(f"user not found: {username}")
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


async def patch_user_tickers(username: str, add: list[str], remove: list[str]) -> list[str]:
    async with _pool.acquire() as conn:
        user_id = await conn.fetchval(
            "select id from users where username = $1", username
        )
        if add:
            await conn.executemany(
                "insert into user_tickers (user_id, ticker) values ($1, $2) on conflict do nothing",
                [(user_id, t) for t in add],
            )
        if remove:
            await conn.execute(
                "delete from user_tickers where user_id = $1 and ticker = any($2::varchar[])",
                user_id,
                remove,
            )
    return await get_user_tickers(username)


async def get_all_tickers() -> list[str]:
    """Union of every ticker across all users — used for warm startup."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "select distinct ticker from user_tickers order by ticker"
        )
    return [r["ticker"] for r in rows]
