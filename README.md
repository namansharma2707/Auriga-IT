# Helpdesk Ticket Queue

A generic helpdesk ticket management system that automatically keeps the most pressing ticket at the top of the queue.

The system manages ticket priority, SLA response deadlines, overdue tickets, automatic escalation, assignment, filtering, customer search, and pagination.

## Features

* Create and manage helpdesk tickets
* Three priority levels:

  * Normal
  * High
  * Urgent
* SLA-based response deadlines
* Automatic overdue detection
* Automatic priority escalation:

  * Normal → High
  * High → Urgent
  * Urgent → Urgent
* Maximum one priority-level escalation per automated run
* Queue ordering based on urgency
* Filter overdue tickets
* Filter tickets assigned to the current agent
* Assign and reassign tickets
* Search tickets by customer name
* Pagination for large ticket queues

## Queue Ordering

The queue is designed to always surface the most pressing tickets first.

The ordering follows:

```text
Overdue Status
      ↓
Priority
      ↓
Response Deadline
      ↓
Stable Tie-Breaker
```

Overdue tickets are placed ahead of tickets that are still within their agreed response time.

## Automatic Escalation

A scheduled process checks for tickets that have breached their response deadline.

When a ticket is overdue, its priority is increased by **one level per run**:

```text
Normal → High → Urgent
```

A single run must never escalate a ticket by more than one level.

Example:

```text
Run 1: Normal → High
Run 2: High → Urgent
```

An already Urgent ticket remains Urgent.

Resolved or closed tickets are not escalated.

## Ticket Information

A ticket contains information such as:

```text
ID
Customer
Title
Description
Priority
Status
Created At
Response Deadline
Assigned To
```

## Filtering & Search

The system supports:

* All tickets
* Overdue tickets
* Tickets assigned to the current agent
* Customer-name search

Filtering and searching preserve the queue's ordering rules.

## Pagination

Large ticket queues are paginated to avoid displaying all tickets at once.

The general processing order is:

```text
Tickets
   ↓
Ordering
   ↓
Filtering / Search
   ↓
Pagination
   ↓
Results
```

## Generic Helpdesk

The system is not tied to a specific person or organization.

It is designed to support:

* Multiple agents
* Multiple customers
* Multiple tickets
* Configurable SLA rules
* Configurable priorities
* Different helpdesk environments

## Project Structure

```text
helpdesk-ticket-queue/
│
├── README.md
├── REASONING.md
├── requirements.txt
├── app/
│   ├── models/
│   ├── services/
│   ├── routes/
│   └── main.py
│
└── tests/
```

The exact structure may vary depending on the implementation.

## Getting Started

### 1. Clone the repository

```bash
git clone <repository-url>
cd helpdesk-ticket-queue
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure the application

Set the required database, SLA, and application configuration.

### 4. Run the application

```bash
python app/main.py
```

## Testing

Run the test suite using the project's configured test command.

The tests should cover:

* Queue ordering
* Overdue detection
* Priority escalation
* One-level-per-run escalation
* Assignment
* Filtering
* Search
* Pagination

## Core Requirement

The primary goal of the system is:

> **Keep the most pressing helpdesk ticket at the top of the queue while automatically escalating tickets that breach their agreed response time.**

For the detailed design decisions and reasoning behind the queue and escalation logic, see [`REASONING.md`](REASONING.md).
