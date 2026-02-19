from googleapiclient.discovery import build
from auth_service import get_valid_credentials
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional


def get_service(db: Session, user_id: str):
    creds = get_valid_credentials(db, user_id)
    if not creds:
        return None
    return build("calendar", "v3", credentials=creds)


def list_events(db: Session, user_id: str, max_results: int = 10, time_min: Optional[str] = None):
    """List upcoming calendar events."""
    service = get_service(db, user_id)
    if not service:
        return None

    if not time_min:
        time_min = datetime.utcnow().isoformat() + "Z"

    results = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    events = results.get("items", [])
    return [
        {
            "id": event["id"],
            "summary": event.get("summary", "No title"),
            "start": event["start"].get("dateTime", event["start"].get("date")),
            "end": event["end"].get("dateTime", event["end"].get("date")),
            "location": event.get("location"),
            "description": event.get("description"),
        }
        for event in events
    ]


def get_event(db: Session, user_id: str, event_id: str):
    """Get a specific calendar event."""
    service = get_service(db, user_id)
    if not service:
        return None

    event = service.events().get(calendarId="primary", eventId=event_id).execute()
    return {
        "id": event["id"],
        "summary": event.get("summary", "No title"),
        "start": event["start"].get("dateTime", event["start"].get("date")),
        "end": event["end"].get("dateTime", event["end"].get("date")),
        "location": event.get("location"),
        "description": event.get("description"),
        "attendees": event.get("attendees", []),
        "htmlLink": event.get("htmlLink"),
    }


def create_event(
    db: Session,
    user_id: str,
    summary: str,
    start_time: str,
    end_time: str,
    description: Optional[str] = None,
    location: Optional[str] = None,
    attendees: Optional[list] = None,
):
    """Create a new calendar event."""
    service = get_service(db, user_id)
    if not service:
        return None

    event_body = {
        "summary": summary,
        "start": {"dateTime": start_time, "timeZone": "UTC"},
        "end": {"dateTime": end_time, "timeZone": "UTC"},
    }

    if description:
        event_body["description"] = description
    if location:
        event_body["location"] = location
    if attendees:
        event_body["attendees"] = [{"email": email} for email in attendees]

    event = service.events().insert(calendarId="primary", body=event_body).execute()
    return {
        "id": event["id"],
        "summary": event.get("summary"),
        "htmlLink": event.get("htmlLink"),
    }


def update_event(
    db: Session,
    user_id: str,
    event_id: str,
    summary: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
):
    """Update an existing calendar event."""
    service = get_service(db, user_id)
    if not service:
        return None

    # Get existing event first
    event = service.events().get(calendarId="primary", eventId=event_id).execute()

    if summary:
        event["summary"] = summary
    if start_time:
        event["start"] = {"dateTime": start_time, "timeZone": "UTC"}
    if end_time:
        event["end"] = {"dateTime": end_time, "timeZone": "UTC"}
    if description is not None:
        event["description"] = description
    if location is not None:
        event["location"] = location

    updated_event = service.events().update(
        calendarId="primary", eventId=event_id, body=event
    ).execute()

    return {
        "id": updated_event["id"],
        "summary": updated_event.get("summary"),
        "htmlLink": updated_event.get("htmlLink"),
    }


def delete_event(db: Session, user_id: str, event_id: str):
    """Delete a calendar event."""
    service = get_service(db, user_id)
    if not service:
        return None

    service.events().delete(calendarId="primary", eventId=event_id).execute()
    return {"status": "deleted", "event_id": event_id}
