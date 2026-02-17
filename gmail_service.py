from googleapiclient.discovery import build
from auth_service import get_valid_credentials
from sqlalchemy.orm import Session
import base64
from email.mime.text import MIMEText

def get_service(db: Session, user_id: str):
    creds = get_valid_credentials(db, user_id)
    if not creds:
        return None
    return build("gmail", "v1", credentials=creds)

def list_messages(db: Session, user_id: str, max_results: int = 5):
    service = get_service(db, user_id)
    if not service:
        return None 
    
    results = service.users().messages().list(userId="me", maxResults=max_results).execute()
    return results.get("messages", [])

def get_message(db: Session, user_id: str, message_id: str):
    service = get_service(db, user_id)
    if not service:
        return None

    message = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    
    headers = message["payload"]["headers"]
    subject = next((h["value"] for h in headers if h["name"] == "Subject"), None)
    sender = next((h["value"] for h in headers if h["name"] == "From"), None)

    body = ""
    def extract_body(payload):
        if payload.get("parts"):
            for part in payload["parts"]:
                if part["mimeType"] == "text/plain":
                    data = part["body"].get("data")
                    if data:
                        return base64.urlsafe_b64decode(data).decode()
        else:
            data = payload["body"].get("data")
            if data:
                return base64.urlsafe_b64decode(data).decode()
        return ""

    body = extract_body(message["payload"])

    return {
        "subject": subject,
        "from": sender,
        "body": body[:500] if body else ""
    }

def send_message(db: Session, user_id: str, to: str, subject: str, body: str):
    service = get_service(db, user_id)
    if not service:
        return None

    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    send_message_payload = {"raw": raw_message}

    sent = service.users().messages().send(userId="me", body=send_message_payload).execute()
    return sent
