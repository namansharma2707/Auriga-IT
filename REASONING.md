# Reasoning & Design Decisions

## 1. Problem Understanding

The helpdesk receives tickets with different priorities and response-time commitments.

The main requirement is to make sure that the agent always sees the most pressing ticket first.

The system therefore needs to solve two main problems:

1. Determine the correct queue order.
2. Automatically escalate tickets that breach their response deadline.

Other features such as filtering, assignment, search, and pagination are built around this core queue.

---

## 2. Priority Model

The system uses three priority levels:

```text
Normal < High < Urgent
```

Each level represents a different degree of urgency.

Using a fixed ordered priority model makes queue comparison and automatic escalation simple.

---

## 3. SLA / Response Deadline

Every ticket has an agreed response deadline.

For example:

* Urgent → response within 2 hours
* Normal → response within 1 day

The deadline is stored with the ticket rather than recalculated every time.

This allows the system to directly determine whether the ticket has breached its SLA.

---

## 4. Overdue Detection

A ticket is considered overdue when its response deadline has passed and it has not been resolved or closed.

Conceptually:

```text
Current Time > Response Deadline
AND
Ticket is still active
```

Overdue status should be calculated from the actual deadline rather than manually maintained, because time continuously changes.

---

## 5. Queue Ordering

The queue is the most important part of the system.

The ordering is:

```text
1. Overdue tickets first
2. Higher priority first
3. Earlier response deadline first
4. Stable tie-breaker
```

### Why overdue comes first

A ticket that has already breached its promised response time requires immediate attention, even if another ticket has a higher normal priority.

Therefore, overdue tickets must jump ahead of tickets that are still within their SLA.

### Why priority comes next

Among tickets with the same overdue status, higher-priority tickets should be handled first.

```text
Urgent > High > Normal
```

### Why deadline comes next

If two tickets have the same priority, the ticket with the earlier response deadline should be handled first.

This helps prevent upcoming SLA breaches.

### Why a tie-breaker is needed

Two tickets can have the same priority and deadline.

A stable field such as creation time or ticket ID can be used to make the ordering deterministic.

---

## 6. Automatic Escalation

The system periodically checks active tickets for SLA breaches.

When a ticket is overdue, its priority is increased by exactly one level.

```text
Normal → High
High → Urgent
Urgent → Urgent
```

### Why only one level per run?

The requirement explicitly limits escalation to one level per automated run.

For example, a Normal ticket that has been overdue for a long time should not immediately become Urgent during a single run.

Instead:

```text
First run:
Normal → High

Next run:
High → Urgent
```

This preserves the escalation rule and makes each automated run predictable.

---

## 7. Already Urgent Tickets

An Urgent ticket cannot be escalated further.

Therefore:

```text
Urgent → Urgent
```

The ticket can still remain overdue and appear at the front of the queue.

---

## 8. Resolved and Closed Tickets

Escalation should only apply to tickets that still require action.

Therefore, resolved or closed tickets are excluded from automatic escalation.

This prevents completed tickets from being modified by the escalation process.

---

## 9. Assignment

Tickets can be assigned to helpdesk agents.

Assignment is kept separate from queue priority because:

* Priority determines how urgent the ticket is.
* Assignment determines who is responsible for handling it.

This allows the same queue logic to work regardless of which agent receives the ticket.

---

## 10. Filtering

The system provides filters such as:

* All tickets
* Overdue tickets
* Tickets assigned to the current agent

Filtering should not change the underlying priority rules.

The same queue ordering is applied to the filtered results.

---

## 11. Customer Search

Customers may have multiple tickets.

Searching by customer name allows an agent to quickly find all tickets belonging to a particular customer.

Search is treated as a separate concern from queue ordering so that the queue logic remains reusable.

---

## 12. Pagination

A helpdesk may contain a very large number of tickets.

Returning every ticket at once is inefficient and difficult to use.

Therefore, results are paginated.

The important rule is that pagination happens **after ordering and filtering**.

```text
All Tickets
    ↓
Order
    ↓
Filter / Search
    ↓
Paginate
    ↓
Return Results
```

This ensures that page 1 contains the most relevant tickets rather than simply the first records stored in the database.

---

## 13. Separation of Responsibilities

The system should keep different responsibilities separate.

Conceptually:

```text
Ticket Model
    ↓
Stores ticket data

Queue Logic
    ↓
Determines ticket order

Escalation Logic
    ↓
Updates priority after SLA breach

Assignment Logic
    ↓
Manages responsible agents

Filter / Search Logic
    ↓
Finds relevant tickets

Pagination
    ↓
Controls result size
```

This makes the system easier to test, modify, and reuse.

---

## 14. Generic Design

The system should not contain logic specific to Priya or a particular helpdesk.

Instead, users, agents, customers, SLA rules, and tickets are represented as general entities.

This makes the same queue logic applicable to different helpdesk environments.

---

## 15. Important Edge Cases

The implementation should handle cases such as:

* An overdue Normal ticket becomes High.
* An overdue High ticket becomes Urgent.
* An overdue Urgent ticket remains Urgent.
* A resolved ticket does not get escalated.
* Multiple tickets have the same priority and deadline.
* No tickets match a filter or search.
* A page number is outside the available range.
* A ticket has no assigned agent.
* Multiple escalation runs happen at different times.

---

## 16. Main Design Principle

The project should be developed in this order:

```text
Ticket Data
     ↓
Queue Ordering
     ↓
SLA / Overdue Detection
     ↓
Automatic Escalation
     ↓
Filters & Search
     ↓
Assignment
     ↓
Pagination
```

The reason is that **correct queue behavior is the heart of the system**.

If the queue does not consistently identify the most pressing ticket, the other features do not solve the main helpdesk problem.
