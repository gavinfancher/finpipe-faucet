from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import server.auth as auth
import server.db as db

router = APIRouter()


class AuthRequest(BaseModel):
    username: str
    password: str


@router.post("/auth/register")
async def register(body: AuthRequest):
    pw_hash = auth.hash_password(body.password)
    created = await db.create_user(body.username, pw_hash)
    if not created:
        raise HTTPException(status_code=400, detail="username already taken")
    token = auth.create_token(body.username)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/auth/login")
async def login(body: AuthRequest):
    pw_hash = await db.get_password_hash(body.username)
    if not pw_hash or not auth.verify_password(body.password, pw_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = auth.create_token(body.username)
    return {"access_token": token, "token_type": "bearer"}
