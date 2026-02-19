import os
from typing import Optional

# TODO: Remove this in production
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from database import get_db, engine, Base
import auth_service
import gmail_service
import calendar_service

load_dotenv()

# Create tables if not exist (mostly for dev, assuming alembic handles migrations in prod)
# Base.metadata.create_all(bind=engine) 

app = FastAPI()

class ManualCallbackRequest(BaseModel):
    user_id: str
    code: Optional[str] = None
    redirect_url: Optional[str] = None


@app.get("/auth/login")
def login(user_id: str):
    flow = auth_service.get_google_flow(state=user_id)
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

    return {"status": "connected", "user_id": state}


@app.post("/auth/callback/manual")
def manual_callback(body: ManualCallbackRequest, db: Session = Depends(get_db)):
    """Headless OAuth callback — accepts an authorization code or a full redirect URL."""
    if not body.code and not body.redirect_url:
        raise HTTPException(status_code=400, detail="Provide either 'code' or 'redirect_url'")

    try:
        if body.code:
            auth_service.exchange_code_with_code(db, body.user_id, body.code)
        else:
            auth_service.exchange_code_and_store(db, body.user_id, body.redirect_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "connected", "user_id": body.user_id}


@app.get("/email/list")
def list_emails(user_id: str, max_results: int = 5, db: Session = Depends(get_db)):
    try:
        messages = gmail_service.list_messages(db, user_id, max_results)
        if messages is None:
             raise HTTPException(status_code=401, detail="User not authenticated or token expired")
        return {"messages": messages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/email/read")
def read_email(user_id: str, message_id: str, db: Session = Depends(get_db)):
    try:
        email_data = gmail_service.get_message(db, user_id, message_id)
        if email_data is None:
             raise HTTPException(status_code=401, detail="User not authenticated or token expired")
        return email_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/email/send")
def send_email(user_id: str, to: str, subject: str, body: str, db: Session = Depends(get_db)):
    try:
        result = gmail_service.send_message(db, user_id, to, subject, body)
        if result is None:
             raise HTTPException(status_code=401, detail="User not authenticated or token expired")
        return {"status": "sent", "message_id": result["id"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Calendar Endpoints

class CreateEventRequest(BaseModel):
    summary: str
    start_time: str  # ISO format: 2024-01-15T10:00:00
    end_time: str
    description: Optional[str] = None
    location: Optional[str] = None
    attendees: Optional[list] = None


class UpdateEventRequest(BaseModel):
    summary: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None


@app.get("/calendar/events")
def list_calendar_events(user_id: str, max_results: int = 10, db: Session = Depends(get_db)):
    try:
        events = calendar_service.list_events(db, user_id, max_results)
        if events is None:
            raise HTTPException(status_code=401, detail="User not authenticated or token expired")
        return {"events": events}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/calendar/events/{event_id}")
def get_calendar_event(user_id: str, event_id: str, db: Session = Depends(get_db)):
    try:
        event = calendar_service.get_event(db, user_id, event_id)
        if event is None:
            raise HTTPException(status_code=401, detail="User not authenticated or token expired")
        return event
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/calendar/events")
def create_calendar_event(user_id: str, body: CreateEventRequest, db: Session = Depends(get_db)):
    try:
        event = calendar_service.create_event(
            db, user_id,
            summary=body.summary,
            start_time=body.start_time,
            end_time=body.end_time,
            description=body.description,
            location=body.location,
            attendees=body.attendees,
        )
        if event is None:
            raise HTTPException(status_code=401, detail="User not authenticated or token expired")
        return {"status": "created", "event": event}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/calendar/events/{event_id}")
def update_calendar_event(user_id: str, event_id: str, body: UpdateEventRequest, db: Session = Depends(get_db)):
    try:
        event = calendar_service.update_event(
            db, user_id, event_id,
            summary=body.summary,
            start_time=body.start_time,
            end_time=body.end_time,
            description=body.description,
            location=body.location,
        )
        if event is None:
            raise HTTPException(status_code=401, detail="User not authenticated or token expired")
        return {"status": "updated", "event": event}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/calendar/events/{event_id}")
def delete_calendar_event(user_id: str, event_id: str, db: Session = Depends(get_db)):
    try:
        result = calendar_service.delete_event(db, user_id, event_id)
        if result is None:
            raise HTTPException(status_code=401, detail="User not authenticated or token expired")
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
