import os

# TODO: Remove this in production
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from database import get_db, engine, Base
import auth_service
import gmail_service

load_dotenv()

# Create tables if not exist (mostly for dev, assuming alembic handles migrations in prod)
# Base.metadata.create_all(bind=engine) 

app = FastAPI()

@app.get("/auth/login")
def login(user_id: str):
    flow = auth_service.get_google_flow(state=user_id)
    auth_url, _ = flow.authorization_url(prompt="consent")
    return RedirectResponse(auth_url)


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
