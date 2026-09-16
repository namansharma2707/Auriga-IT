from datetime import datetime, timezone
from typing import List, Optional, Tuple
from sqlalchemy import case, or_
from sqlalchemy.orm import Session

from app.models import Ticket
from app.schemas import QueueTicketItem


def escalate_breached_tickets(db: Session, as_of: Optional[datetime] = None) -> int:
    """
    The Twist: Automated check that escalates tickets which have breached
    their response SLA without receiving a first response.
    
    Transition rules:
    - normal -> high
    - high -> urgent
    - urgent remains urgent (capped)
    - At most ONE level escalation per run.
    """
    ref_time = as_of or datetime.now(timezone.utc)
    if ref_time.tzinfo is None:
        ref_time = ref_time.replace(tzinfo=timezone.utc)

    breached_tickets = db.query(Ticket).filter(
        Ticket.status != "resolved",
        Ticket.first_responded_at.is_(None),
        Ticket.first_response_due_at < ref_time,
        Ticket.priority.in_(["normal", "high"])
    ).all()

    escalated_count = 0
    for ticket in breached_tickets:
        if ticket.priority == "normal":
            ticket.priority = "high"
            ticket.version += 1
            escalated_count += 1
        elif ticket.priority == "high":
            ticket.priority = "urgent"
            ticket.version += 1
            escalated_count += 1

    if escalated_count > 0:
        db.commit()

    return escalated_count


def fetch_ordered_queue(
    db: Session,
    as_of: datetime,
    page: int = 1,
    limit: int = 10,
    search: Optional[str] = None,
    assigned_to: Optional[str] = None,
    overdue_only: bool = False
) -> Tuple[List[QueueTicketItem], int]:
    """
    Fetches the priority queue with deterministic 4-tier ordering and frozen timestamp.
    
    Ordering Logic:
    1. Overdue Status: Breached response SLA tickets jump directly to the top.
    2. Priority Weight: Urgent (0) > High (1) > Normal (2).
    3. Deadline: Earliest response due date first.
    4. Stable Tie-breaker: Created timestamp, then Ticket ID.
    """
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    # Base Query: Exclude resolved tickets
    query = db.query(Ticket).filter(Ticket.status != "resolved")

    # SLA Overdue Expression
    is_overdue_condition = (Ticket.first_responded_at.is_(None)) & (Ticket.first_response_due_at < as_of)

    if overdue_only:
        query = query.filter(is_overdue_condition)

    if assigned_to:
        query = query.filter(Ticket.assigned_to == assigned_to)

    if search:
        search_pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Ticket.customer_name.ilike(search_pattern),
                Ticket.customer_email.ilike(search_pattern),
                Ticket.customer_id.ilike(search_pattern),
                Ticket.id.ilike(search_pattern),
                Ticket.title.ilike(search_pattern)
            )
        )

    total_count = query.count()

    # Deterministic Sort Expressions
    overdue_rank = case((is_overdue_condition, 0), else_=1)

    priority_rank = case(
        (Ticket.priority == "urgent", 0),
        (Ticket.priority == "high", 1),
        else_=2
    )

    ordered_query = query.order_by(
        overdue_rank.asc(),
        priority_rank.asc(),
        Ticket.first_response_due_at.asc(),
        Ticket.created_at.asc(),
        Ticket.id.asc()
    )

    offset = (page - 1) * limit
    tickets = ordered_query.offset(offset).limit(limit).all()

    items: List[QueueTicketItem] = []
    for t in tickets:
        due_ts = t.first_response_due_at
        if due_ts.tzinfo is None:
            due_ts = due_ts.replace(tzinfo=timezone.utc)

        delta_seconds = int((due_ts - as_of).total_seconds())
        breached = t.is_breached(as_of)

        items.append(
            QueueTicketItem(
                id=t.id,
                customer_id=t.customer_id,
                customer_name=t.customer_name,
                customer_email=t.customer_email,
                title=t.title,
                priority=t.priority,
                status=t.status,
                assigned_to=t.assigned_to,
                created_at=t.created_at,
                first_response_due_at=t.first_response_due_at,
                first_responded_at=t.first_responded_at,
                version=t.version,
                is_overdue=breached,
                seconds_until_due=delta_seconds
            )
        )

    return items, total_count