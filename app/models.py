import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, Index, CheckConstraint
from app.database import Base


def generate_ticket_id() -> str:
    """Generate a clean, deterministic, sorted ticket ID like T-1A2B3C4D."""
    return f"T-{uuid.uuid4().hex[:8].upper()}"


class Ticket(Base):
    __tablename__ = "tickets"

    # Deterministic tie-breaker ID
    id = Column(String(32), primary_key=True, default=generate_ticket_id, index=True)

    # Customer Information
    customer_id = Column(String(64), nullable=False, index=True)
    customer_name = Column(String(150), nullable=False, index=True)
    customer_email = Column(String(150), nullable=False)

    # Ticket Metadata (Supports Twist: normal -> high -> urgent)
    title = Column(String(255), nullable=False)
    priority = Column(String(20), nullable=False, default="normal")  # 'normal' | 'high' | 'urgent'
    status = Column(String(20), nullable=False, default="open")      # 'open' | 'resolved'
    assigned_to = Column(String(100), nullable=True, index=True)      # Agent ID or Name

    # SLA and Timestamps (Always stored in UTC)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    first_response_due_at = Column(DateTime(timezone=True), nullable=False, index=True)
    first_responded_at = Column(DateTime(timezone=True), nullable=True)  # Response SLA clock stops here
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    # Optimistic locking counter for concurrent claims
    version = Column(Integer, nullable=False, default=1)

    __table_args__ = (
        # Performance index for active queue lookups
        Index("ix_tickets_active_queue", "status", "first_response_due_at"),
        # Compound index for agent assignment lookups
        Index("ix_tickets_assigned_status", "assigned_to", "status"),
        # Priority and Status domain constraints
        CheckConstraint("priority IN ('normal', 'high', 'urgent')", name="valid_priority_check"),
        CheckConstraint("status IN ('open', 'resolved')", name="valid_status_check"),
    )

    def is_breached(self, as_of: datetime) -> bool:
        """
        Check if the first response SLA has been breached.
        A ticket is breached only if:
        1. It is not resolved.
        2. First response hasn't been recorded yet.
        3. Reference time (as_of) exceeds first_response_due_at.
        """
        if self.status == "resolved" or self.first_responded_at is not None:
            return False
        
        # Ensure timezone-aware comparison
        due = self.first_response_due_at
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)

        return as_of > due