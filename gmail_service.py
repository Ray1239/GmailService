from googleapiclient.discovery import build
from auth_service import get_valid_credentials
from sqlalchemy.orm import Session
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List, Dict, Any


def get_service(db: Session, agent_id: str):
    creds = get_valid_credentials(db, agent_id)
    if not creds:
        return None
    return build("gmail", "v1", credentials=creds)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_header(headers: list, name: str) -> Optional[str]:
    """Extract a header value by name (case-insensitive)."""
    name_lower = name.lower()
    return next((h["value"] for h in headers if h["name"].lower() == name_lower), None)


def _extract_body(payload: dict) -> dict:
    """Recursively extract plain text and HTML body from a message payload."""
    plain = ""
    html = ""

    def _walk(part):
        nonlocal plain, html
        mime = part.get("mimeType", "")
        if mime == "text/plain" and not plain:
            data = part.get("body", {}).get("data")
            if data:
                plain = base64.urlsafe_b64decode(data).decode(errors="replace")
        elif mime == "text/html" and not html:
            data = part.get("body", {}).get("data")
            if data:
                html = base64.urlsafe_b64decode(data).decode(errors="replace")
        for sub in part.get("parts", []):
            _walk(sub)

    _walk(payload)
    return {"plain": plain, "html": html}


def _extract_attachments(payload: dict) -> list:
    """Extract attachment metadata from a message payload."""
    attachments = []

    def _walk(part):
        filename = part.get("filename")
        if filename:
            attachments.append({
                "filename": filename,
                "mime_type": part.get("mimeType"),
                "size": part.get("body", {}).get("size", 0),
                "attachment_id": part.get("body", {}).get("attachmentId"),
            })
        for sub in part.get("parts", []):
            _walk(sub)

    _walk(payload)
    return attachments


def _parse_message(message: dict) -> dict:
    """Parse a raw Gmail API message into a rich, agent-friendly dict."""
    headers = message.get("payload", {}).get("headers", [])
    body = _extract_body(message["payload"])
    attachments = _extract_attachments(message["payload"])

    return {
        "message_id": message["id"],
        "thread_id": message.get("threadId"),
        "label_ids": message.get("labelIds", []),
        "snippet": message.get("snippet", ""),
        "subject": _get_header(headers, "Subject"),
        "from": _get_header(headers, "From"),
        "to": _get_header(headers, "To"),
        "cc": _get_header(headers, "Cc"),
        "date": _get_header(headers, "Date"),
        "in_reply_to": _get_header(headers, "In-Reply-To"),
        "references": _get_header(headers, "References"),
        "body": body,
        "attachments": attachments,
        "size_estimate": message.get("sizeEstimate"),
    }


def _parse_message_summary(message: dict) -> dict:
    """Parse a message into a lightweight summary (for list/search results)."""
    headers = message.get("payload", {}).get("headers", [])
    return {
        "message_id": message["id"],
        "thread_id": message.get("threadId"),
        "label_ids": message.get("labelIds", []),
        "snippet": message.get("snippet", ""),
        "subject": _get_header(headers, "Subject"),
        "from": _get_header(headers, "From"),
        "to": _get_header(headers, "To"),
        "date": _get_header(headers, "Date"),
    }


# ── Core functions ───────────────────────────────────────────────────────────

def list_messages(
    db: Session,
    agent_id: str,
    max_results: int = 10,
    query: Optional[str] = None,
    label_ids: Optional[List[str]] = None,
):
    """List messages with optional Gmail search query and label filter.

    Returns enriched summaries (subject, from, to, date, snippet) so the
    agent can decide which messages to read in full without extra calls.
    """
    service = get_service(db, agent_id)
    if not service:
        return None

    kwargs: Dict[str, Any] = {"userId": "me", "maxResults": max_results}
    if query:
        kwargs["q"] = query
    if label_ids:
        kwargs["labelIds"] = label_ids

    results = service.users().messages().list(**kwargs).execute()
    message_ids = results.get("messages", [])

    if not message_ids:
        return {"messages": [], "result_count": 0}

    # Fetch metadata for each message in the list
    summaries = []
    for msg_ref in message_ids:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_ref["id"], format="metadata",
                 metadataHeaders=["Subject", "From", "To", "Date"])
            .execute()
        )
        summaries.append(_parse_message_summary(msg))

    return {
        "messages": summaries,
        "result_count": len(summaries),
        "next_page_token": results.get("nextPageToken"),
    }


def search_messages(
    db: Session,
    agent_id: str,
    query: str,
    max_results: int = 10,
):
    """Search messages using Gmail query syntax. Convenience wrapper."""
    return list_messages(db, agent_id, max_results=max_results, query=query)


def get_message(db: Session, agent_id: str, message_id: str):
    """Get full message with complete body, headers, labels, and attachments."""
    service = get_service(db, agent_id)
    if not service:
        return None

    message = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    return _parse_message(message)


def batch_get_messages(db: Session, agent_id: str, message_ids: List[str]):
    """Get multiple messages by ID in one logical call."""
    service = get_service(db, agent_id)
    if not service:
        return None

    results = []
    for mid in message_ids:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=mid, format="full")
            .execute()
        )
        results.append(_parse_message(msg))
    return results


def get_thread(db: Session, agent_id: str, thread_id: str):
    """Get all messages in a thread, each with full metadata."""
    service = get_service(db, agent_id)
    if not service:
        return None

    thread = (
        service.users()
        .threads()
        .get(userId="me", id=thread_id, format="full")
        .execute()
    )

    messages = [_parse_message(msg) for msg in thread.get("messages", [])]
    return {
        "thread_id": thread["id"],
        "message_count": len(messages),
        "messages": messages,
    }


def send_message(
    db: Session,
    agent_id: str,
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    html_body: Optional[str] = None,
):
    """Send an email with optional cc, bcc, and HTML body."""
    service = get_service(db, agent_id)
    if not service:
        return None

    if html_body:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain"))
        msg.attach(MIMEText(html_body, "html"))
    else:
        msg = MIMEText(body)

    msg["to"] = to
    msg["subject"] = subject
    if cc:
        msg["cc"] = cc
    if bcc:
        msg["bcc"] = bcc

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return sent


def reply_to_message(
    db: Session,
    agent_id: str,
    message_id: str,
    body: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    html_body: Optional[str] = None,
):
    """Reply to a message in its thread with proper headers."""
    service = get_service(db, agent_id)
    if not service:
        return None

    # Fetch the original message to get thread context
    original = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="metadata",
             metadataHeaders=["Subject", "From", "Message-ID", "References"])
        .execute()
    )
    orig_headers = original.get("payload", {}).get("headers", [])
    orig_subject = _get_header(orig_headers, "Subject") or ""
    orig_from = _get_header(orig_headers, "From") or ""
    orig_msg_id = _get_header(orig_headers, "Message-ID") or ""
    orig_refs = _get_header(orig_headers, "References") or ""
    thread_id = original.get("threadId")

    # Build references chain
    references = f"{orig_refs} {orig_msg_id}".strip()

    if html_body:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain"))
        msg.attach(MIMEText(html_body, "html"))
    else:
        msg = MIMEText(body)

    msg["to"] = orig_from
    msg["subject"] = f"Re: {orig_subject}" if not orig_subject.startswith("Re:") else orig_subject
    msg["In-Reply-To"] = orig_msg_id
    msg["References"] = references
    if cc:
        msg["cc"] = cc
    if bcc:
        msg["bcc"] = bcc

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = (
        service.users()
        .messages()
        .send(userId="me", body={"raw": raw, "threadId": thread_id})
        .execute()
    )
    return sent


def modify_labels(
    db: Session,
    agent_id: str,
    message_ids: List[str],
    add_labels: Optional[List[str]] = None,
    remove_labels: Optional[List[str]] = None,
):
    """Add/remove labels on one or more messages.

    Common patterns for agents:
      - Archive:     remove_labels=["INBOX"]
      - Mark read:   remove_labels=["UNREAD"]
      - Mark unread: add_labels=["UNREAD"]
      - Star:        add_labels=["STARRED"]
      - Trash:       add_labels=["TRASH"]
    """
    service = get_service(db, agent_id)
    if not service:
        return None

    body: Dict[str, Any] = {
        "ids": message_ids,
        "addLabelIds": add_labels or [],
        "removeLabelIds": remove_labels or [],
    }

    service.users().messages().batchModify(userId="me", body=body).execute()
    return {"modified_count": len(message_ids)}


def get_attachment(db: Session, agent_id: str, message_id: str, attachment_id: str):
    """Download an attachment by ID and return its base64 data."""
    service = get_service(db, agent_id)
    if not service:
        return None

    attachment = (
        service.users()
        .messages()
        .attachments()
        .get(userId="me", messageId=message_id, id=attachment_id)
        .execute()
    )
    return {
        "data": attachment.get("data"),
        "size": attachment.get("size"),
    }
