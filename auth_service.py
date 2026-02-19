from sqlalchemy.orm import Session
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from models import GmailAccount
from security import encrypt, decrypt
import os
import json
import datetime

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]
CLIENT_SECRETS_FILE = "credentials_for_local.json"
REDIRECT_URI = "http://localhost/auth/callback"

def get_google_flow(state=None):
    return Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
        state=state,
    )

def exchange_code_and_store(db: Session, agent_id: str, authorization_response: str):
    flow = get_google_flow(state=agent_id)
    flow.fetch_token(authorization_response=authorization_response)
    credentials = flow.credentials
    store_credentials(db, agent_id, credentials)
    return credentials


def exchange_code_with_code(db: Session, agent_id: str, code: str):
    """Exchange a raw authorization code for tokens (headless flow)."""
    flow = get_google_flow(state=agent_id)
    flow.fetch_token(code=code)
    credentials = flow.credentials
    store_credentials(db, agent_id, credentials)
    return credentials


def store_credentials(db: Session, agent_id: str, credentials):
    access_token = credentials.token
    refresh_token = credentials.refresh_token
    expiry = credentials.expiry

    encrypted_access = encrypt(access_token)
    encrypted_refresh = encrypt(refresh_token) if refresh_token else None

    account = db.query(GmailAccount).filter(GmailAccount.agent_id == agent_id).first()
    if not account:
        account = GmailAccount(
            agent_id=agent_id,
            access_token=encrypted_access,
            refresh_token=encrypted_refresh,
            expiry=expiry
        )
        db.add(account)
    else:
        account.access_token = encrypted_access
        if refresh_token: # Only update refresh token if present (sometimes it's not returned on refresh)
            account.refresh_token = encrypted_refresh
        account.expiry = expiry
    
    db.commit()
    db.refresh(account)
    return account

def get_valid_credentials(db: Session, agent_id: str):
    account = db.query(GmailAccount).filter(GmailAccount.agent_id == agent_id).first()
    if not account:
        return None

    access_token = decrypt(account.access_token)
    refresh_token = decrypt(account.refresh_token) if account.refresh_token else None

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=get_client_id_from_file(),
        client_secret=get_client_secret_from_file(),
        scopes=SCOPES,
        expiry=account.expiry
    )

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Update DB with new token
            store_credentials(db, agent_id, creds)
        except Exception as e:
            print(f"Error refreshing token: {e}")
            return None

    return creds

def get_client_id_from_file():
    with open(CLIENT_SECRETS_FILE, 'r') as f:
        data = json.load(f)
        return data['web']['client_id']

def get_client_secret_from_file():
    with open(CLIENT_SECRETS_FILE, 'r') as f:
        data = json.load(f)
        return data['web']['client_secret']
