import os
from typing import Optional, Dict, Any, List

# TODO: Remove this in production
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from database import get_db, engine, Base
from models import AgentSecret
from security import encrypt, decrypt
import auth_service
import gmail_service
import calendar_service

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


class SendEmailRequest(BaseModel):
    agent_id: str
    to: str
    subject: str
    body: str
    cc: Optional[str] = None
    bcc: Optional[str] = None
    html_body: Optional[str] = None


class ReplyRequest(BaseModel):
    agent_id: str
    message_id: str
    body: str
    cc: Optional[str] = None
    bcc: Optional[str] = None
    html_body: Optional[str] = None


class ModifyLabelsRequest(BaseModel):
    agent_id: str
    message_ids: List[str]
    add_labels: Optional[List[str]] = None
    remove_labels: Optional[List[str]] = None


class BatchReadRequest(BaseModel):
    agent_id: str
    message_ids: List[str]


class CreateEventRequest(BaseModel):
    agent_id: str
    summary: str
    start_time: str  # ISO format: 2024-01-15T10:00:00
    end_time: str
    description: Optional[str] = None
    location: Optional[str] = None
    attendees: Optional[List[str]] = None


class UpdateEventRequest(BaseModel):
    agent_id: str
    summary: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None


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

    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Authentication Successful</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            }
            .container {
                background: white;
                padding: 40px;
                border-radius: 8px;
                box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);
                text-align: center;
                max-width: 400px;
            }
            .checkmark {
                width: 80px;
                height: 80px;
                margin: 0 auto 20px;
                background: #4CAF50;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 50px;
                color: white;
            }
            h1 {
                color: #333;
                margin: 20px 0 10px 0;
                font-size: 28px;
            }
            p {
                color: #666;
                font-size: 16px;
                line-height: 1.6;
                margin: 10px 0;
            }
            .agent-id {
                background: #f5f5f5;
                padding: 10px;
                border-radius: 4px;
                margin: 20px 0;
                font-family: monospace;
                font-size: 14px;
                color: #333;
                word-break: break-all;
            }
            .instruction {
                color: #999;
                font-size: 14px;
                margin-top: 30px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="checkmark">✓</div>
            <h1>You are Authenticated!</h1>
            <p>Your Gmail account has been successfully connected.</p>
            <div class="agent-id">Agent ID: """ + state + """</div>
            <p class="instruction">You can now close this window and access your account.</p>
        </div>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content)


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
def list_emails(
    agent_id: str,
    max_results: int = 10,
    query: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List emails with optional Gmail search query.

    The `query` param supports full Gmail search syntax, e.g.:
    - `is:unread in:inbox`
    - `from:someone@example.com`
    - `subject:invoice newer_than:7d`
    - `category:primary is:unread`
    - `has:attachment`

    Returns enriched summaries (subject, from, to, date, snippet, labels).
    """
    try:
        result = gmail_service.list_messages(db, agent_id, max_results, query=query)
        if result is None:
            raise HTTPException(status_code=401, detail="Agent not authenticated or token expired")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/email/search")
def search_emails(
    agent_id: str,
    query: str,
    max_results: int = 10,
    db: Session = Depends(get_db),
):
    """Search emails using Gmail query syntax.

    Examples:
    - `is:unread category:primary` — unread primary emails
    - `from:boss@company.com newer_than:3d` — recent emails from boss
    - `in:sent to:client@example.com` — sent emails to a client
    - `subject:meeting after:2026/02/01` — meetings since Feb 1
    """
    try:
        result = gmail_service.search_messages(db, agent_id, query, max_results)
        if result is None:
            raise HTTPException(status_code=401, detail="Agent not authenticated or token expired")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/email/read")
def read_email(agent_id: str, message_id: str, db: Session = Depends(get_db)):
    """Read a full email — complete body (no truncation), all headers, labels,
    thread_id, and attachment metadata."""
    try:
        email_data = gmail_service.get_message(db, agent_id, message_id)
        if email_data is None:
            raise HTTPException(status_code=401, detail="Agent not authenticated or token expired")
        return email_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/email/batch_read")
def batch_read_emails(body: BatchReadRequest, db: Session = Depends(get_db)):
    """Read multiple emails by ID in a single call."""
    try:
        results = gmail_service.batch_get_messages(db, body.agent_id, body.message_ids)
        if results is None:
            raise HTTPException(status_code=401, detail="Agent not authenticated or token expired")
        return {"messages": results, "count": len(results)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/email/thread")
def get_thread(agent_id: str, thread_id: str, db: Session = Depends(get_db)):
    """Get all messages in a conversation thread."""
    try:
        thread = gmail_service.get_thread(db, agent_id, thread_id)
        if thread is None:
            raise HTTPException(status_code=401, detail="Agent not authenticated or token expired")
        return thread
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/email/send")
def send_email(body: SendEmailRequest, db: Session = Depends(get_db)):
    """Send an email with optional cc, bcc, and HTML body."""
    try:
        result = gmail_service.send_message(
            db, body.agent_id, body.to, body.subject, body.body,
            cc=body.cc, bcc=body.bcc, html_body=body.html_body,
        )
        if result is None:
            raise HTTPException(status_code=401, detail="Agent not authenticated or token expired")
        return {"status": "sent", "message_id": result["id"], "thread_id": result.get("threadId")}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/email/reply")
def reply_to_email(body: ReplyRequest, db: Session = Depends(get_db)):
    """Reply to an email in its thread with proper In-Reply-To/References headers."""
    try:
        result = gmail_service.reply_to_message(
            db, body.agent_id, body.message_id, body.body,
            cc=body.cc, bcc=body.bcc, html_body=body.html_body,
        )
        if result is None:
            raise HTTPException(status_code=401, detail="Agent not authenticated or token expired")
        return {"status": "sent", "message_id": result["id"], "thread_id": result.get("threadId")}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/email/modify")
def modify_email_labels(body: ModifyLabelsRequest, db: Session = Depends(get_db)):
    """Add/remove labels on messages.

    Common patterns:
    - Archive:     remove_labels=["INBOX"]
    - Mark read:   remove_labels=["UNREAD"]
    - Mark unread: add_labels=["UNREAD"]
    - Star:        add_labels=["STARRED"]
    - Trash:       add_labels=["TRASH"]
    """
    try:
        result = gmail_service.modify_labels(
            db, body.agent_id, body.message_ids,
            add_labels=body.add_labels, remove_labels=body.remove_labels,
        )
        if result is None:
            raise HTTPException(status_code=401, detail="Agent not authenticated or token expired")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/email/attachment")
def get_attachment(
    agent_id: str,
    message_id: str,
    attachment_id: str,
    db: Session = Depends(get_db),
):
    """Download an attachment by its attachment_id (returned in email read results)."""
    try:
        result = gmail_service.get_attachment(db, agent_id, message_id, attachment_id)
        if result is None:
            raise HTTPException(status_code=401, detail="Agent not authenticated or token expired")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Calendar endpoints ───────────────────────────────────────────────────────

@app.get("/calendar/events")
def list_calendar_events(agent_id: str, max_results: int = 10, db: Session = Depends(get_db)):
    """List upcoming calendar events."""
    try:
        events = calendar_service.list_events(db, agent_id, max_results)
        if events is None:
            raise HTTPException(status_code=401, detail="Agent not authenticated or token expired")
        return {"events": events}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/calendar/events/{event_id}")
def get_calendar_event(agent_id: str, event_id: str, db: Session = Depends(get_db)):
    """Get a specific calendar event."""
    try:
        event = calendar_service.get_event(db, agent_id, event_id)
        if event is None:
            raise HTTPException(status_code=401, detail="Agent not authenticated or token expired")
        return event
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/calendar/events")
def create_calendar_event(body: CreateEventRequest, db: Session = Depends(get_db)):
    """Create a new calendar event."""
    try:
        event = calendar_service.create_event(
            db, body.agent_id,
            summary=body.summary,
            start_time=body.start_time,
            end_time=body.end_time,
            description=body.description,
            location=body.location,
            attendees=body.attendees,
        )
        if event is None:
            raise HTTPException(status_code=401, detail="Agent not authenticated or token expired")
        return {"status": "created", "event": event}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/calendar/events/{event_id}")
def update_calendar_event(event_id: str, body: UpdateEventRequest, db: Session = Depends(get_db)):
    """Update an existing calendar event."""
    try:
        event = calendar_service.update_event(
            db, body.agent_id, event_id,
            summary=body.summary,
            start_time=body.start_time,
            end_time=body.end_time,
            description=body.description,
            location=body.location,
        )
        if event is None:
            raise HTTPException(status_code=401, detail="Agent not authenticated or token expired")
        return {"status": "updated", "event": event}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/calendar/events/{event_id}")
def delete_calendar_event(agent_id: str, event_id: str, db: Session = Depends(get_db)):
    """Delete a calendar event."""
    try:
        result = calendar_service.delete_event(db, agent_id, event_id)
        if result is None:
            raise HTTPException(status_code=401, detail="Agent not authenticated or token expired")
        return result
    except HTTPException:
        raise
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
