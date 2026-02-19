import os
from typing import Optional, Dict, Any

# TODO: Remove this in production
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from database import get_db, engine, Base
from models import AgentSecret
from security import encrypt, decrypt
import auth_service
import gmail_service

load_dotenv()

# Create tables if not exist (mostly for dev, assuming alembic handles migrations in prod)
# Base.metadata.create_all(bind=engine) 

app = FastAPI()


# ── Request models ───────────────────────────────────────────────────────────

class ManualCallbackRequest(BaseModel):
    agent_id: str
    code: Optional[str] = None
    redirect_url: Optional[str] = None


class SecretUpsertRequest(BaseModel):
    agent_id: str
    service_name: str
    secret_data: Dict[str, Any]


# ── Auth endpoints ───────────────────────────────────────────────────────────

@app.get("/auth/login")
def login(agent_id: str):
    flow = auth_service.get_google_flow(state=agent_id)
    auth_url, _ = flow.authorization_url(prompt="consent")
    return {"auth_url": auth_url}


@app.get("/auth/callback")
def callback(request: Request, db: Session = Depends(get_db)):
    state = request.query_params.get("state")
    if not state:
        raise HTTPException(status_code=400, detail="State not found")
        
    try:
        auth_service.exchange_code_and_store(db, state, str(request.url))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "connected", "agent_id": state}


@app.post("/auth/callback/manual")
def manual_callback(body: ManualCallbackRequest, db: Session = Depends(get_db)):
    """Headless OAuth callback — accepts an authorization code or a full redirect URL."""
    if not body.code and not body.redirect_url:
        raise HTTPException(status_code=400, detail="Provide either 'code' or 'redirect_url'")

    try:
        if body.code:
            auth_service.exchange_code_with_code(db, body.agent_id, body.code)
        else:
            auth_service.exchange_code_and_store(db, body.agent_id, body.redirect_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "connected", "agent_id": body.agent_id}


# ── Email endpoints ──────────────────────────────────────────────────────────

@app.get("/email/list")
def list_emails(agent_id: str, max_results: int = 5, db: Session = Depends(get_db)):
    try:
        messages = gmail_service.list_messages(db, agent_id, max_results)
        if messages is None:
             raise HTTPException(status_code=401, detail="Agent not authenticated or token expired")
        return {"messages": messages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/email/read")
def read_email(agent_id: str, message_id: str, db: Session = Depends(get_db)):
    try:
        email_data = gmail_service.get_message(db, agent_id, message_id)
        if email_data is None:
             raise HTTPException(status_code=401, detail="Agent not authenticated or token expired")
        return email_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/email/send")
def send_email(agent_id: str, to: str, subject: str, body: str, db: Session = Depends(get_db)):
    try:
        result = gmail_service.send_message(db, agent_id, to, subject, body)
        if result is None:
             raise HTTPException(status_code=401, detail="Agent not authenticated or token expired")
        return {"status": "sent", "message_id": result["id"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Secrets helpers ──────────────────────────────────────────────────────────

def _encrypt_secret_data(data: Dict[str, Any]) -> Dict[str, str]:
    """Encrypt every value in the dict with Fernet."""
    return {k: encrypt(str(v)) for k, v in data.items()}


def _decrypt_secret_data(data: Dict[str, Any]) -> Dict[str, str]:
    """Decrypt every value in the dict with Fernet."""
    return {k: decrypt(str(v)) for k, v in data.items()}


# ── Secrets CRUD endpoints ──────────────────────────────────────────────────

@app.post("/secrets")
def upsert_secret(body: SecretUpsertRequest, db: Session = Depends(get_db)):
    """Create or update a secret for an agent + service combination."""
    encrypted = _encrypt_secret_data(body.secret_data)

    secret = (
        db.query(AgentSecret)
        .filter(AgentSecret.agent_id == body.agent_id, AgentSecret.service_name == body.service_name)
        .first()
    )
    if secret:
        secret.secret_data = encrypted
    else:
        secret = AgentSecret(
            agent_id=body.agent_id,
            service_name=body.service_name,
            secret_data=encrypted,
        )
        db.add(secret)

    db.commit()
    db.refresh(secret)
    return {
        "id": secret.id,
        "agent_id": secret.agent_id,
        "service_name": secret.service_name,
        "updated_at": secret.updated_at,
    }


@app.get("/secrets/{agent_id}")
def list_secrets(agent_id: str, db: Session = Depends(get_db)):
    """List all secrets for a given agent (returns service names only, not the data)."""
    secrets = db.query(AgentSecret).filter(AgentSecret.agent_id == agent_id).all()
    return [
        {
            "id": s.id,
            "service_name": s.service_name,
            "updated_at": s.updated_at,
        }
        for s in secrets
    ]


@app.get("/secrets/{agent_id}/{service_name}")
def get_secret(agent_id: str, service_name: str, db: Session = Depends(get_db)):
    """Get the full secret data for an agent + service."""
    secret = (
        db.query(AgentSecret)
        .filter(AgentSecret.agent_id == agent_id, AgentSecret.service_name == service_name)
        .first()
    )
    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")
    return {
        "id": secret.id,
        "agent_id": secret.agent_id,
        "service_name": secret.service_name,
        "secret_data": _decrypt_secret_data(secret.secret_data),
        "updated_at": secret.updated_at,
    }


@app.delete("/secrets/{agent_id}/{service_name}")
def delete_secret(agent_id: str, service_name: str, db: Session = Depends(get_db)):
    """Delete a secret for an agent + service."""
    secret = (
        db.query(AgentSecret)
        .filter(AgentSecret.agent_id == agent_id, AgentSecret.service_name == service_name)
        .first()
    )
    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")
    db.delete(secret)
    db.commit()
    return {"status": "deleted"}
