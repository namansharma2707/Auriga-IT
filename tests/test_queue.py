from datetime import datetime, timedelta, timezone
import pytest
from freezegun import freeze_time
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Ticket
from app.queue_engine import fetch_ordered_queue


@pytest.fixture
def db_session():
    """In-memory SQLite session isolated for every test run."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


# Scenario 1: Breached response SLA vs already responded ticket
def test_breached_vs_responded_ticket(db_session):
    """
    Ticket A: Normal, response deadline past, NOT responded -> OVERDUE (Jumps to top).
    Ticket B: Urgent, created earlier, but agent responded 10m ago -> NOT OVERDUE.
    Expected: Ticket A must be on top despite Ticket B being Urgent.
    """
    with freeze_time("2026-09-16 11:00:00"):
        now = datetime.now(timezone.utc)

        # Ticket A: Created at 08:00, Normal SLA (+24h), but artificially set due at 09:00 (Breached)
        ticket_a = Ticket(
            id="T-A",
            customer_id="C-1",
            customer_name="Alice",
            customer_email="alice@example.com",
            title="Normal Breached",
            priority="normal",
            status="open",
            created_at=now - timedelta(hours=3),
            first_response_due_at=now - timedelta(hours=2),  # 09:00 UTC (breached)
            first_responded_at=None
        )

        # Ticket B: Urgent SLA breached, but agent responded at 10:50 UTC
        ticket_b = Ticket(
            id="T-B",
            customer_id="C-2",
            customer_name="Bob",
            customer_email="bob@example.com",
            title="Urgent Responded",
            priority="urgent",
            status="open",
            created_at=now - timedelta(hours=3),
            first_response_due_at=now - timedelta(hours=1),  # 10:00 UTC
            first_responded_at=now - timedelta(minutes=10)   # Responded! Clock stopped.
        )

        db_session.add_all([ticket_a, ticket_b])
        db_session.commit()

        items, total = fetch_ordered_queue(db=db_session, as_of=now, page=1, limit=10)

        assert total == 2
        assert items[0].id == "T-A"
        assert items[0].is_overdue is True
        assert items[1].id == "T-B"
        assert items[1].is_overdue is False


# Scenario 2: Overdue Urgent vs Overdue Normal
def test_overdue_urgent_vs_overdue_normal(db_session):
    """
    Both tickets have breached response deadlines.
    Ticket A: Normal, breached at 09:00.
    Ticket B: Urgent, breached at 10:00.
    Expected: Ticket B wins because inside the overdue bucket, Urgent rank > Normal rank.
    """
    with freeze_time("2026-09-16 10:30:00"):
        now = datetime.now(timezone.utc)

        ticket_a = Ticket(
            id="T-A",
            customer_id="C-1",
            customer_name="Alice",
            customer_email="alice@example.com",
            title="Overdue Normal",
            priority="normal",
            status="open",
            created_at=now - timedelta(hours=4),
            first_response_due_at=now - timedelta(hours=1, minutes=30),  # 09:00 UTC
            first_responded_at=None
        )

        ticket_b = Ticket(
            id="T-B",
            customer_id="C-2",
            customer_name="Bob",
            customer_email="bob@example.com",
            title="Overdue Urgent",
            priority="urgent",
            status="open",
            created_at=now - timedelta(hours=2),
            first_response_due_at=now - timedelta(minutes=30),          # 10:00 UTC
            first_responded_at=None
        )

        db_session.add_all([ticket_a, ticket_b])
        db_session.commit()

        items, _ = fetch_ordered_queue(db=db_session, as_of=now, page=1, limit=10)

        assert items[0].id == "T-B"
        assert items[1].id == "T-A"


# Scenario 3: On-track Urgent vs On-track Normal
def test_on_track_priority_precedence(db_session):
    """
    Neither ticket is overdue.
    Ticket A: Normal, due at 12:00.
    Ticket B: Urgent, due at 14:00.
    Expected: Ticket B wins because Urgent priority outranks Normal priority in on-track bucket.
    """
    with freeze_time("2026-09-16 10:00:00"):
        now = datetime.now(timezone.utc)

        ticket_a = Ticket(
            id="T-A",
            customer_id="C-1",
            customer_name="Alice",
            customer_email="alice@example.com",
            title="Normal On-track",
            priority="normal",
            status="open",
            created_at=now - timedelta(hours=1),
            first_response_due_at=now + timedelta(hours=2),  # 12:00 UTC
            first_responded_at=None
        )

        ticket_b = Ticket(
            id="T-B",
            customer_id="C-2",
            customer_name="Bob",
            customer_email="bob@example.com",
            title="Urgent On-track",
            priority="urgent",
            status="open",
            created_at=now - timedelta(minutes=30),
            first_response_due_at=now + timedelta(hours=4),  # 14:00 UTC
            first_responded_at=None
        )

        db_session.add_all([ticket_a, ticket_b])
        db_session.commit()

        items, _ = fetch_ordered_queue(db=db_session, as_of=now, page=1, limit=10)

        assert items[0].id == "T-B"
        assert items[1].id == "T-A"


# Scenario 4: Exact Tie-Break via ID Determinism
def test_exact_tie_break_determinism(db_session):
    """
    Both tickets have exact same priority, deadline, and creation timestamp.
    Expected: Must deterministically sort by alphanumeric Ticket ID (T-01 before T-02).
    """
    with freeze_time("2026-09-16 10:00:00"):
        now = datetime.now(timezone.utc)
        target_due = now + timedelta(hours=2)

        ticket_2 = Ticket(
            id="T-02",
            customer_id="C-2",
            customer_name="Bob",
            customer_email="bob@example.com",
            title="Same Params 2",
            priority="normal",
            status="open",
            created_at=now,
            first_response_due_at=target_due,
            first_responded_at=None
        )

        ticket_1 = Ticket(
            id="T-01",
            customer_id="C-1",
            customer_name="Alice",
            customer_email="alice@example.com",
            title="Same Params 1",
            priority="normal",
            status="open",
            created_at=now,
            first_response_due_at=target_due,
            first_responded_at=None
        )

        db_session.add_all([ticket_2, ticket_1])
        db_session.commit()

        items, _ = fetch_ordered_queue(db=db_session, as_of=now, page=1, limit=10)

        assert items[0].id == "T-01"
        assert items[1].id == "T-02"


# Scenario 5: Resolved Tickets Ingestion (Must be excluded from active queue)
def test_resolved_tickets_excluded(db_session):
    """
    Ticket A: Open Normal.
    Ticket B: Urgent created weeks ago with SLA long breached, but status='resolved'.
    Expected: Resolved ticket must NOT appear in the active queue or skew counts.
    """
    with freeze_time("2026-09-16 10:00:00"):
        now = datetime.now(timezone.utc)

        open_ticket = Ticket(
            id="T-OPEN",
            customer_id="C-1",
            customer_name="Alice",
            customer_email="alice@example.com",
            title="Open Ticket",
            priority="normal",
            status="open",
            created_at=now,
            first_response_due_at=now + timedelta(hours=4),
            first_responded_at=None
        )

        resolved_ticket = Ticket(
            id="T-RESOLVED",
            customer_id="C-2",
            customer_name="Bob",
            customer_email="bob@example.com",
            title="Resolved Old Ticket",
            priority="urgent",
            status="resolved",
            created_at=now - timedelta(days=14),
            first_response_due_at=now - timedelta(days=13),
            first_responded_at=now - timedelta(days=14),
            resolved_at=now - timedelta(days=10)
        )

        db_session.add_all([open_ticket, resolved_ticket])
        db_session.commit()

        items, total = fetch_ordered_queue(db=db_session, as_of=now, page=1, limit=10)

        assert total == 1
        assert len(items) == 1
        assert items[0].id == "T-OPEN"