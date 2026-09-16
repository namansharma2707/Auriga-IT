from datetime import datetime, timedelta
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, EmailStr, field_validator, ConfigDict


# Configurable Response SLAs
SLA_POLICY = {
    "urgent": timedelta(hours=2),
    "normal": timedelta(hours=24)
}


class TicketBase(BaseModel):
    customer_id: str = Field(..., min_length=1, max_length=64, description="Unique customer ID")
    customer_name: str = Field(..., min_length=1, max_length=150, description="Full customer name")
    customer_email: EmailStr = Field(..., description="Customer email address")
    title: str = Field(..., min_length=3, max_length=255, description="Issue summary")
    priority: Literal["urgent", "normal"] = Field("normal", description="Ticket priority level")

    @field_validator("title", "customer_name")
    @classmethod
    def prevent_empty_strings(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("Field cannot be empty or pure whitespace.")
        return clean


class TicketCreate(TicketBase):
    """Payload for ticket creation."""

    def get_sla_timedelta(self) -> timedelta:
        """Returns the response SLA window based on ticket priority."""
        return SLA_POLICY.get(self.priority, timedelta(hours=24))


class TicketResponse(TicketBase):
    """Full ticket representation."""
    id: str
    status: str
    assigned_to: Optional[str] = None
    created_at: datetime
    first_response_due_at: datetime
    first_responded_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    version: int

    model_config = ConfigDict(from_attributes=True)

class QueueTicketItem(TicketResponse):
    """Decorated ticket returned in the priority queue with live SLA metadata."""
    is_overdue: bool
    seconds_until_due: int  # Negative value means overdue by that many seconds


class PaginatedQueueResponse(BaseModel):
    """Paginated response with frozen reference timestamp."""
    items: List[QueueTicketItem]
    page: int
    limit: int
    total: int
    as_of: datetime


class ClaimTicketRequest(BaseModel):
    """Payload for atomic agent assignment."""
    agent_id: str = Field(..., min_length=1, max_length=100)
    version: int = Field(..., description="Current ticket version for optimistic locking")


class ClaimTicketResponse(BaseModel):
    ticket_id: str
    assigned_to: str
    new_version: int
    message: str


class RespondTicketResponse(BaseModel):
    ticket_id: str
    first_responded_at: datetime
    message: str