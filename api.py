"""FastAPI service. The API key identifies the tenant, so a caller can never ask as someone else.
Run:  uvicorn api:app --reload   then open http://127.0.0.1:8000/docs"""
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

import app_state
from agent import run_agent

app = FastAPI(title="Texas Contract Finder")


class Turn(BaseModel):
    role: Literal["user", "assistant"]          # callers can't inject "system" or "tool" messages
    content: str = Field(max_length=4000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)   # caps cost and abuse per request
    history: list[Turn] = Field(default=[], max_length=10)


def _tenant_from_key(api_key: str) -> dict:
    con = app_state.connect()
    tenant = app_state.tenant_for_api_key(con, api_key)
    con.close()
    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return tenant


@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/me")
def me(x_api_key: str = Header(...)):
    """Who this key belongs to, for the UI's profile card. Never returns the key itself."""
    t = _tenant_from_key(x_api_key)
    return {k: t[k] for k in ("tenant_id", "name", "naics_codes", "state", "employees", "notes")}
@app.post("/ask")
def ask(req: AskRequest, x_api_key: str = Header(...)):
    tenant = _tenant_from_key(x_api_key)                       # lock 1: the key decides the tenant
    history = [t.model_dump() for t in req.history]
    return {"tenant": tenant["tenant_id"], **run_agent(tenant["tenant_id"], req.question, history)}


@app.get("/matches")
def matches(x_api_key: str = Header(...)):
    tenant = _tenant_from_key(x_api_key)
    con = app_state.connect()
    rows = app_state.list_matches(con, tenant["tenant_id"])
    con.close()
    return rows
