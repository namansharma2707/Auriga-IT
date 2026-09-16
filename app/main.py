import os
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.database import engine, Base, get_db
from app.models import Ticket
from app.schemas import (
    TicketCreate,
    TicketResponse,
    PaginatedQueueResponse,
    ClaimTicketRequest,
    ClaimTicketResponse,
    RespondTicketResponse
)
from app.queue_engine import fetch_ordered_queue, escalate_breached_tickets

# Database table initialize
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Helpdesk Priority Queue Engine",
    description="Deterministic Overdue-First Helpdesk API with Response SLA, Optimistic Locking, and Auto-Escalation",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Frontend folder paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ---------------- Frontend HTML Routes ----------------

@app.get("/", include_in_schema=False)
@app.get("/portal", include_in_schema=False)
def serve_portal():
    """Customer Ticket Submission Portal + Simulator."""
    portal_path = os.path.join(FRONTEND_DIR, "submit_ticket.html")
    if not os.path.exists(portal_path):
        raise HTTPException(status_code=404, detail="submit_ticket.html not found in frontend folder")
    return FileResponse(portal_path)


@app.get("/dashboard", include_in_schema=False)
def serve_dashboard():
    """Agent Queue Dashboard (Priya's View)."""
    dashboard_path = os.path.join(FRONTEND_DIR, "index.html")
    if not os.path.exists(dashboard_path):
        raise HTTPException(status_code=404, detail="index.html not found in frontend folder")
    return FileResponse(dashboard_path)


@app.get("/success", include_in_schema=False)
def serve_success():
    """Ticket Confirmation & SLA Countdown View."""
    success_path = os.path.join(FRONTEND_DIR, "success.html")
    if not os.path.exists(success_path):
        raise HTTPException(status_code=404, detail="success.html not found in frontend folder")
    return FileResponse(success_path)


# ---------------- Core API Routes ----------------

@app.post("/api/tickets", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
def create_ticket(payload: TicketCreate, db: Session = Depends(get_db)):
    """Create a new ticket and calculate strict first-response deadline."""
    now = datetime.now(timezone.utc)
    sla_delta = payload.get_sla_timedelta()
    due_at = now + sla_delta

    ticket = Ticket(
        customer_id=payload.customer_id,
        customer_name=payload.customer_name,
        customer_email=payload.customer_email,
        title=payload.title,
        priority=payload.priority,
        status="open",
        created_at=now,
        first_response_due_at=due_at,
        first_responded_at=None,
        version=1
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


@app.get("/api/tickets/queue", response_model=PaginatedQueueResponse)
def get_priority_queue(
    page: int = Query(1, ge=1, description="Page index"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    as_of: Optional[datetime] = Query(None, description="Frozen timestamp to prevent pagination drift"),
    search: Optional[str] = Query(None, description="Search by customer name, email, or ticket ID"),
    assigned_to: Optional[str] = Query(None, description="Filter by assigned agent"),
    overdue_only: bool = Query(False, description="Filter strictly overdue tickets"),
    db: Session = Depends(get_db)
):
    """Fetch deterministic paginated queue with frozen reference time."""
    reference_time = as_of or datetime.now(timezone.utc)

    items, total = fetch_ordered_queue(
        db=db,
        as_of=reference_time,
        page=page,
        limit=limit,
        search=search,
        assigned_to=assigned_to,
        overdue_only=overdue_only
    )

    return PaginatedQueueResponse(
        items=items,
        page=page,
        limit=limit,
        total=total,
        as_of=reference_time
    )


@app.post("/api/tickets/{ticket_id}/claim", response_model=ClaimTicketResponse)
def claim_ticket(
    ticket_id: str,
    payload: ClaimTicketRequest,
    db: Session = Depends(get_db)
):
    """Atomic claim using optimistic locking (version check)."""
    rows_affected = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.version == payload.version,
        Ticket.status != "resolved"
    ).update(
        {
            Ticket.assigned_to: payload.agent_id,
            Ticket.version: Ticket.version + 1
        },
        synchronize_session=False
    )
    db.commit()

    if rows_affected == 0:
        existing = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not existing:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
        if existing.status == "resolved":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ticket is already resolved")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conflict: Ticket was claimed/modified by {existing.assigned_to or 'another process'}"
        )

    return ClaimTicketResponse(
        ticket_id=ticket_id,
        assigned_to=payload.agent_id,
        new_version=payload.version + 1,
        message="Ticket claimed successfully."
    )


@app.post("/api/tickets/{ticket_id}/respond", response_model=RespondTicketResponse)
def mark_first_response(ticket_id: str, db: Session = Depends(get_db)):
    """Records first agent reply and stops the response SLA clock."""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    
    if ticket.first_responded_at is not None:
        return RespondTicketResponse(
            ticket_id=ticket.id,
            first_responded_at=ticket.first_responded_at,
            message="Response was already recorded previously."
        )

    now = datetime.now(timezone.utc)
    ticket.first_responded_at = now
    ticket.version += 1
    db.commit()
    db.refresh(ticket)

    return RespondTicketResponse(
        ticket_id=ticket.id,
        first_responded_at=ticket.first_responded_at,
        message="First response recorded. SLA clock stopped."
    )


# ---------------- The Twist & Resolution Endpoints ----------------

@app.post("/api/tickets/escalate-check")
def trigger_escalation_check(
    as_of: Optional[datetime] = Query(None, description="Reference time for checking SLA breach"),
    db: Session = Depends(get_db)
):
    """
    The Twist: Automated check that escalates any ticket which has breached
    its agreed response time — raising priority by one level:
    normal -> high -> urgent (at most one level per run).
    """
    reference_time = as_of or datetime.now(timezone.utc)
    count = escalate_breached_tickets(db=db, as_of=reference_time)
    return {
        "status": "success",
        "escalated_count": count,
        "message": f"{count} ticket(s) escalated by 1 priority level."
    }


@app.post("/api/tickets/{ticket_id}/resolve")
def resolve_ticket(ticket_id: str, db: Session = Depends(get_db)):
    """Marks ticket as resolved and permanently removes it from the active queue."""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    
    if ticket.status == "resolved":
        return {"status": "already_resolved", "message": "Ticket is already resolved."}

    ticket.status = "resolved"
    ticket.resolved_at = datetime.now(timezone.utc)
    ticket.version += 1
    db.commit()

    return {
        "status": "success",
        "ticket_id": ticket.id,
        "message": "Ticket resolved and permanently removed from active queue."
    }