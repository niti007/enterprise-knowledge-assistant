"""
ingestion/generate_fake_data.py
================================
Generates a coherent fake enterprise corpus so multi-hop RAG queries have real answers.

Strategy
--------
1. Define a stable entity universe (teams, people, systems, SOPs) via Faker — no LLM needed.
2. Write 15-20 documents (policies as PDF, SOPs/manuals/incidents/FAQ as Markdown) whose
   prose weaves the entities together.
3. Write 4 CSVs (products, users, transactions, doc_metadata).

All entity names are consistent across every doc so the graph extractor (T3) will find
real connections and vector search will surface coherent multi-hop chains.

Run:
    python -m app.ingestion.generate_fake_data
    # or
    python app/ingestion/generate_fake_data.py
"""
from __future__ import annotations

import csv
import json
import os
import random
import sys
import textwrap
from datetime import date, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Bootstrap path so we can import app.config
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from faker import Faker  # noqa: E402

fake = Faker()
random.seed(42)
Faker.seed(42)

RAW_DIR = ROOT / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Entity Universe (stable — woven through every doc)
# ---------------------------------------------------------------------------
TEAMS = [
    "Billing",
    "Infrastructure",
    "Security",
    "Data Engineering",
    "Customer Success",
    "Product",
]

PEOPLE = {
    "Billing": "Priya Sharma",
    "Infrastructure": "Marcus Lee",
    "Security": "Natalia Voss",
    "Data Engineering": "Chen Wei",
    "Customer Success": "Amara Okafor",
    "Product": "Diego Reyes",
}
# Reverse map person -> team
PERSON_TEAM = {v: k for k, v in PEOPLE.items()}

SYSTEMS = [
    "Payment-Service",
    "Auth-DB",
    "UserProfile-API",
    "DataWarehouse",
    "Notification-Service",
    "InventoryEngine",
    "ReportingPortal",
    "APIGateway",
]

SOPS = {
    "SOP-01": "Incident Response Procedure",
    "SOP-02": "Data Backup and Recovery",
    "SOP-03": "Access Provisioning",
    "SOP-04": "Change Management",
    "SOP-05": "On-Call Escalation",
    "SOP-17": "Payment Service Restoration",
    "SOP-22": "Security Breach Containment",
}

POLICIES = {
    "POL-001": "Acceptable Use Policy",
    "POL-002": "Data Retention Policy",
    "POL-003": "Information Security Policy",
    "POL-004": "Remote Work Policy",
}

INCIDENTS = [
    {
        "id": "INC-201",
        "date": "2026-01-15",
        "system": "Auth-DB",
        "cause": "connection pool exhaustion",
        "team": "Infrastructure",
        "lead": "Marcus Lee",
        "sop": "SOP-01",
        "linked_system": "UserProfile-API",
        "severity": "P2",
    },
    {
        "id": "INC-202",
        "date": "2026-02-03",
        "system": "Notification-Service",
        "cause": "message queue backlog",
        "team": "Data Engineering",
        "lead": "Chen Wei",
        "sop": "SOP-05",
        "linked_system": "Payment-Service",
        "severity": "P3",
    },
    {
        "id": "INC-203",
        "date": "2026-02-28",
        "system": "ReportingPortal",
        "cause": "DataWarehouse schema drift",
        "team": "Data Engineering",
        "lead": "Chen Wei",
        "sop": "SOP-02",
        "linked_system": "DataWarehouse",
        "severity": "P2",
    },
    {
        "id": "INC-204",
        "date": "2026-03-12",
        "system": "Payment-Service",
        "cause": "Auth-DB hitting connection limits",
        "team": "Billing",
        "lead": "Priya Sharma",
        "sop": "SOP-17",
        "linked_system": "Auth-DB",
        "severity": "P1",
    },
    {
        "id": "INC-205",
        "date": "2026-04-07",
        "system": "APIGateway",
        "cause": "TLS certificate expiry",
        "team": "Security",
        "lead": "Natalia Voss",
        "sop": "SOP-22",
        "linked_system": "Auth-DB",
        "severity": "P1",
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    print(f"  [wrote] {path.relative_to(ROOT)}")


def _write_pdf(path: Path, title: str, body_paragraphs: list[str]) -> None:
    """Write a simple PDF using reportlab."""
    try:
        from reportlab.lib.pagesizes import A4  # type: ignore
        from reportlab.lib.styles import getSampleStyleSheet  # type: ignore
        from reportlab.lib.units import cm  # type: ignore
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer  # type: ignore
    except ImportError:
        print("[WARN] reportlab not installed — writing PDF as text placeholder")
        _write_text(path.with_suffix(".md"), f"# {title}\n\n" + "\n\n".join(body_paragraphs))
        return

    doc = SimpleDocTemplate(str(path), pagesize=A4,
                            leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(title, styles["Title"]),
        Spacer(1, 0.4 * cm),
    ]
    for para in body_paragraphs:
        story.append(Paragraph(para.replace("\n", "<br/>"), styles["BodyText"]))
        story.append(Spacer(1, 0.3 * cm))
    doc.build(story)
    print(f"  [wrote] {path.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Document generators
# ---------------------------------------------------------------------------

def gen_policy_pdf(pol_id: str, title: str, dept: str, sections: list[tuple[str, str]]) -> None:
    """Generate a policy as a PDF."""
    body: list[str] = [
        f"<b>Document ID:</b> {pol_id} &nbsp;|&nbsp; <b>Department:</b> {dept} &nbsp;|&nbsp; "
        f"<b>Effective Date:</b> {date.today()} &nbsp;|&nbsp; <b>Status:</b> Active"
    ]
    for heading, text in sections:
        body.append(f"<b>{heading}</b>")
        body.append(text)
    _write_pdf(RAW_DIR / f"{pol_id}.pdf", title, body)


def gen_incident_md(inc: dict[str, Any]) -> None:
    """Generate an incident report as Markdown."""
    content = f"""# Incident Report — {inc["id"]}

**Date:** {inc["date"]}
**Severity:** {inc["severity"]}
**System Affected:** {inc["system"]}
**Owner Team:** {inc["team"]}
**Incident Lead:** {inc["lead"]}
**Referenced SOP:** {inc["sop"]} — {SOPS.get(inc["sop"], "Standard Procedure")}

## Summary

On {inc["date"]}, a {inc["severity"]} incident was raised against **{inc["system"]}** due to
{inc["cause"]}. The outage caused cascading failures in **{inc["linked_system"]}** which depends
on {inc["system"]} for critical operations.

## Impact

- {inc["system"]} became unavailable for approximately 47 minutes.
- Downstream service **{inc["linked_system"]}** experienced elevated error rates (>30%).
- Customer-facing operations managed by the **{inc["team"]}** team were degraded.

## Root Cause Analysis

The root cause was identified as: **{inc["cause"]}**. Investigation conducted by
**{inc["lead"]}** (Team Lead, {inc["team"]}) confirmed that {inc["linked_system"]} has a hard
dependency on {inc["system"]}; when {inc["system"]} saturated its connection pool, all downstream
callers including {inc["linked_system"]} began failing immediately.

## Resolution

Incident was resolved following **{inc["sop"]}** ({SOPS.get(inc["sop"], "Standard Procedure")}).
Steps taken:
1. Paged on-call engineer via PagerDuty escalation per SOP-05.
2. Identified offending query pattern in {inc["system"]} logs.
3. Applied connection pool limit increase + circuit breaker configuration.
4. Verified {inc["linked_system"]} recovery via health-check endpoints.

## Action Items

| # | Action | Owner | Due |
|---|--------|-------|-----|
| 1 | Implement adaptive connection pooling in {inc["system"]} | {inc["lead"]} | +7 days |
| 2 | Add circuit breaker between {inc["linked_system"]} and {inc["system"]} | {PEOPLE["Infrastructure"]} | +14 days |
| 3 | Update runbook {inc["sop"]} with new recovery steps | {inc["lead"]} | +5 days |

## References

- SOP: {inc["sop"]} — {SOPS.get(inc["sop"], "")}
- Related: {inc["linked_system"]} dependency map
- Grafana dashboard: https://monitoring.internal/{inc["system"].lower()}/overview
"""
    _write_text(RAW_DIR / f"{inc['id']}.md", content)


def gen_sop_md(sop_id: str, title: str, owner_team: str, steps: list[str]) -> None:
    owner = PEOPLE[owner_team]
    content = f"""# {sop_id} — {title}

**Owner Team:** {owner_team}
**Procedure Owner:** {owner}
**Last Reviewed:** {date.today()}
**Version:** 2.1

## Purpose

This Standard Operating Procedure defines the steps the **{owner_team}** team must follow when
executing: **{title}**.

## Scope

Applies to all engineers in the **{owner_team}** team and any on-call responder triggered via
PagerDuty escalation. Cross-team coordination requires approval from {owner}.

## Prerequisites

- Access to internal monitoring (Grafana, Datadog)
- Write access to affected systems (granted per POL-003 — Information Security Policy)
- Familiarity with POL-002 (Data Retention Policy) if data recovery is involved

## Procedure

{chr(10).join(f'{i+1}. {step}' for i, step in enumerate(steps))}

## Escalation

If the procedure cannot be completed within 30 minutes, escalate to:
- Primary: **{owner}** ({owner_team} Lead)
- Secondary: **{PEOPLE["Infrastructure"]}** (Infrastructure)
- Executive: VP of Engineering

## Related Documents

- POL-003: Information Security Policy
- SOP-05: On-Call Escalation
- Contact directory: https://wiki.internal/contacts
"""
    _write_text(RAW_DIR / f"{sop_id}.md", content)


def gen_manual_md(system: str, owner_team: str) -> None:
    owner = PEOPLE[owner_team]
    deps = random.sample([s for s in SYSTEMS if s != system], k=min(2, len(SYSTEMS) - 1))
    content = f"""# Technical Manual — {system}

**Owner Team:** {owner_team}
**System Owner:** {owner}
**Version:** 3.4
**Last Updated:** {date.today()}

## Overview

**{system}** is a core component of the enterprise platform, managed by the **{owner_team}** team
under the technical leadership of **{owner}**.

It provides: real-time processing, data validation, and downstream event emission to services
including **{deps[0]}** and **{deps[1]}**.

## Architecture

```
[Clients] → [APIGateway] → [{system}] → [{deps[0]}]
                                      ↘ [{deps[1]}]
```

{system} depends on **Auth-DB** for all authentication and session validation. Any outage in
Auth-DB will cause {system} to return 503 errors to callers. See INC-204 for a historical
example of this failure mode.

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MAX_CONNECTIONS` | 100 | Connection pool ceiling |
| `TIMEOUT_MS` | 5000 | Request timeout in milliseconds |
| `RETRY_ATTEMPTS` | 3 | Retry count on transient failure |
| `CIRCUIT_BREAKER_THRESHOLD` | 0.5 | Error-rate threshold to open circuit |

## Operations

### Health Check
```
GET /health  →  {{ "status": "ok", "version": "3.4" }}
```

### Deployment
Deployments follow **SOP-04** (Change Management). All changes require approval from **{owner}**
and a successful run of the test suite in staging before production promotion.

### Incident Response
On failure, follow **SOP-01** (Incident Response Procedure). Page the **{owner_team}** team
on-call channel. If Auth-DB is involved, coordinate with **{PEOPLE["Infrastructure"]}**.

## Monitoring

- Grafana dashboard: https://monitoring.internal/{system.lower()}/overview
- Alert rules: PagerDuty policy `{owner_team.lower()}-{system.lower()}`
- Log stream: Datadog service `{system.lower()}`

## Related Documents

- SOP-01: Incident Response
- SOP-04: Change Management
- SOP-17: Payment Service Restoration (if {system} = Payment-Service)
- POL-003: Information Security Policy
"""
    slug = system.lower().replace("-", "_")
    _write_text(RAW_DIR / f"manual_{slug}.md", content)


def gen_faq_md() -> None:
    content = """# Enterprise Knowledge Assistant — FAQ

## General

**Q: Who owns the Payment-Service?**
A: Payment-Service is owned by the **Billing** team, led by **Priya Sharma**. For escalations,
contact Priya directly or page the Billing on-call via PagerDuty.

**Q: What do I do during a P1 incident?**
A: Follow SOP-01 (Incident Response Procedure). Immediately page the on-call engineer via
PagerDuty. If the incident involves Auth-DB or APIGateway, also loop in **Marcus Lee**
(Infrastructure). For security-related incidents, contact **Natalia Voss** (Security).

**Q: Which systems depend on Auth-DB?**
A: Auth-DB is a foundational service. Dependent systems include:
- Payment-Service (Billing team — Priya Sharma)
- UserProfile-API (Customer Success — Amara Okafor)
- APIGateway (Security — Natalia Voss)

Any Auth-DB outage triggers cascading failures across these systems. See INC-204 for the
March 2026 example.

**Q: How do I request access to a system?**
A: Submit an access request per SOP-03 (Access Provisioning). Access is governed by
POL-003 (Information Security Policy). All requests require manager approval.

**Q: What is the data retention period for transaction records?**
A: Per POL-002 (Data Retention Policy), transaction records are retained for 7 years.
PII data is anonymised after 90 days per GDPR requirements. Contact **Chen Wei**
(Data Engineering) for data queries.

**Q: Who is the on-call lead for Infrastructure incidents?**
A: **Marcus Lee** is the primary on-call lead for Infrastructure. The escalation path is:
Marcus Lee → VP Engineering → CTO. Follow SOP-05 for escalation steps.

**Q: How does the model router work?**
A: The AI assistant routes simple factual queries to gpt-4o-mini (faster, cheaper) and
complex multi-hop or reasoning queries to gpt-4o. Routing is based on query complexity
signals: length, presence of multi-entity references, and historical latency.

## Data & Compliance

**Q: Where is customer PII stored?**
A: Customer PII resides in UserProfile-API's backing store (managed by the Customer Success
team under Amara Okafor) and the DataWarehouse (Data Engineering, Chen Wei). Both are
governed by POL-002 and POL-003.

**Q: What happens if a security breach is detected?**
A: Follow SOP-22 (Security Breach Containment) immediately. Contact **Natalia Voss**
(Security Lead) within 15 minutes. The Security team will invoke POL-003 procedures and
notify relevant stakeholders. Do NOT attempt containment without Natalia's sign-off.

## Systems

**Q: What caused the March 2026 Payment-Service outage?**
A: INC-204 (2026-03-12, P1): Auth-DB hit its connection pool limit, causing Payment-Service
to fail. Payment-Service has a hard dependency on Auth-DB. Billing team lead Priya Sharma
managed recovery per SOP-17 (Payment Service Restoration).

**Q: Is there a runbook for ReportingPortal failures?**
A: Yes. ReportingPortal failures are usually caused by DataWarehouse schema drift (see
INC-203). Follow SOP-02 (Data Backup and Recovery). The Data Engineering team (Chen Wei)
owns both systems.
"""
    _write_text(RAW_DIR / "FAQ.md", content)


# ---------------------------------------------------------------------------
# CSV generators
# ---------------------------------------------------------------------------

def gen_users_csv() -> None:
    fieldnames = ["user_id", "name", "email", "team", "role", "active", "created_date"]
    rows = []
    for team, lead in PEOPLE.items():
        first, last = lead.split()
        rows.append({
            "user_id": f"U{len(rows)+1:04d}",
            "name": lead,
            "email": f"{first.lower()}.{last.lower()}@acme.internal",
            "team": team,
            "role": "Team Lead",
            "active": True,
            "created_date": str(date(2023, 1, 15)),
        })
    for _ in range(40):
        team = random.choice(TEAMS)
        name = fake.name()
        first, *rest = name.split()
        last = rest[-1] if rest else "Doe"
        rows.append({
            "user_id": f"U{len(rows)+1:04d}",
            "name": name,
            "email": f"{first.lower()}.{last.lower()}{random.randint(1,99)}@acme.internal",
            "team": team,
            "role": random.choice(["Engineer", "Analyst", "Manager", "Specialist"]),
            "active": random.choice([True, True, True, False]),
            "created_date": str(fake.date_between(date(2020, 1, 1), date(2025, 12, 31))),
        })
    path = RAW_DIR / "users.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  [wrote] {path.relative_to(ROOT)}")


def gen_products_csv() -> None:
    PRODUCTS = [
        ("PRD-001", "Analytics Suite", "Product", "SaaS", 299.00),
        ("PRD-002", "DataWarehouse Connector", "Data Engineering", "Integration", 149.00),
        ("PRD-003", "SecureVault", "Security", "Compliance", 499.00),
        ("PRD-004", "ReportingPortal Pro", "Product", "SaaS", 99.00),
        ("PRD-005", "Billing Automation", "Billing", "SaaS", 199.00),
        ("PRD-006", "InventoryEngine Lite", "Product", "SaaS", 79.00),
        ("PRD-007", "CustomerSuccess Hub", "Customer Success", "SaaS", 349.00),
    ]
    path = RAW_DIR / "products.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["product_id", "name", "owner_team", "category", "price_usd"])
        writer.writeheader()
        for p in PRODUCTS:
            writer.writerow(dict(zip(["product_id", "name", "owner_team", "category", "price_usd"], p)))
    print(f"  [wrote] {path.relative_to(ROOT)}")


def gen_transactions_csv() -> None:
    products = ["PRD-001", "PRD-002", "PRD-003", "PRD-004", "PRD-005", "PRD-006", "PRD-007"]
    path = RAW_DIR / "transactions.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["txn_id", "date", "user_id", "product_id", "amount_usd", "status", "payment_system"]
        )
        writer.writeheader()
        for i in range(200):
            txn_date = fake.date_between(date(2025, 1, 1), date(2026, 6, 1))
            writer.writerow({
                "txn_id": f"TXN-{i+1:05d}",
                "date": str(txn_date),
                "user_id": f"U{random.randint(1, 46):04d}",
                "product_id": random.choice(products),
                "amount_usd": round(random.uniform(10, 2000), 2),
                "status": random.choices(["completed", "pending", "failed"], weights=[80, 12, 8])[0],
                "payment_system": "Payment-Service",
            })
    print(f"  [wrote] {path.relative_to(ROOT)}")


def gen_doc_metadata_csv(doc_paths: list[str]) -> None:
    path = RAW_DIR / "doc_metadata.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["filename", "doc_type", "dept", "date", "author", "system_refs", "sop_refs"]
        )
        writer.writeheader()
        for dp in doc_paths:
            fname = Path(dp).name
            if fname.startswith("INC-"):
                inc = next((i for i in INCIDENTS if i["id"] == fname.replace(".md", "")), None)
                if inc:
                    writer.writerow({
                        "filename": fname,
                        "doc_type": "incident_report",
                        "dept": inc["team"],
                        "date": inc["date"],
                        "author": inc["lead"],
                        "system_refs": f"{inc['system']},{inc['linked_system']}",
                        "sop_refs": inc["sop"],
                    })
                    continue
            if fname.startswith("SOP-"):
                writer.writerow({
                    "filename": fname,
                    "doc_type": "sop",
                    "dept": "All",
                    "date": str(date.today()),
                    "author": "Ops Team",
                    "system_refs": "",
                    "sop_refs": fname.replace(".md", ""),
                })
                continue
            if fname.startswith("POL-"):
                writer.writerow({
                    "filename": fname,
                    "doc_type": "policy",
                    "dept": "All",
                    "date": str(date.today()),
                    "author": "Legal/Compliance",
                    "system_refs": "",
                    "sop_refs": "",
                })
                continue
            if fname.startswith("manual_"):
                system = fname.replace("manual_", "").replace(".md", "").replace("_", "-").title()
                writer.writerow({
                    "filename": fname,
                    "doc_type": "technical_manual",
                    "dept": "Infrastructure",
                    "date": str(date.today()),
                    "author": PEOPLE["Infrastructure"],
                    "system_refs": system,
                    "sop_refs": "SOP-01,SOP-04",
                })
                continue
            writer.writerow({
                "filename": fname,
                "doc_type": "general",
                "dept": "All",
                "date": str(date.today()),
                "author": "Knowledge Team",
                "system_refs": "",
                "sop_refs": "",
            })
    print(f"  [wrote] {path.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"\nGenerating fake enterprise corpus into {RAW_DIR}\n")
    generated: list[str] = []

    # --- Policies (PDF) ---
    gen_policy_pdf(
        "POL-001", "Acceptable Use Policy", "All",
        [
            ("1. Purpose",
             "This policy defines acceptable use of ACME Corp's information systems, networks, "
             "and data assets. It applies to all employees, contractors, and third-party vendors "
             "with access to ACME systems."),
            ("2. Scope",
             "Covers all ACME-owned or ACME-managed systems including Payment-Service, Auth-DB, "
             "UserProfile-API, DataWarehouse, Notification-Service, InventoryEngine, "
             "ReportingPortal, and APIGateway."),
            ("3. Acceptable Use",
             "Systems must be used for legitimate business purposes only. Employees must not "
             "attempt to access systems outside their granted permissions (per SOP-03 and "
             "POL-003). All access is logged and monitored by the Security team under "
             "Natalia Voss."),
            ("4. Prohibited Activities",
             "Prohibited: sharing credentials, bypassing Auth-DB authentication, exfiltrating "
             "customer PII from UserProfile-API or DataWarehouse, running unauthorised scripts "
             "on production systems without Change Management approval (SOP-04)."),
            ("5. Enforcement",
             "Violations are investigated by the Security team. Severe breaches trigger "
             "SOP-22 (Security Breach Containment). Contact Natalia Voss for questions."),
        ],
    )
    generated.append(str(RAW_DIR / "POL-001.pdf"))

    gen_policy_pdf(
        "POL-002", "Data Retention Policy", "Data Engineering",
        [
            ("1. Purpose",
             "Defines how long ACME retains different categories of data and the process for "
             "secure deletion or anonymisation. Owned by Data Engineering (Chen Wei)."),
            ("2. Retention Schedules",
             "Transaction records: 7 years (regulatory requirement). Customer PII in "
             "UserProfile-API and DataWarehouse: anonymised after 90 days per GDPR. "
             "Incident reports (e.g., INC-201 through INC-205): 3 years. System logs: 1 year. "
             "Backup snapshots: 30 days rolling."),
            ("3. Data Deletion",
             "Deletion must be coordinated by Chen Wei (Data Engineering). Involves: removing "
             "from DataWarehouse, purging from UserProfile-API backing store, notifying Billing "
             "team (Priya Sharma) if transaction data is affected."),
            ("4. Backup Procedures",
             "Follow SOP-02 (Data Backup and Recovery) for all backup operations. Backups are "
             "encrypted at rest and stored in geo-redundant locations managed by Infrastructure "
             "(Marcus Lee)."),
        ],
    )
    generated.append(str(RAW_DIR / "POL-002.pdf"))

    gen_policy_pdf(
        "POL-003", "Information Security Policy", "Security",
        [
            ("1. Purpose",
             "Establishes ACME's security controls for protecting information assets. "
             "Owned by the Security team under Natalia Voss."),
            ("2. Access Control",
             "All system access is provisioned via SOP-03 (Access Provisioning). "
             "Multi-factor authentication is mandatory for Auth-DB, UserProfile-API, "
             "DataWarehouse, and APIGateway. Access reviews are conducted quarterly."),
            ("3. Incident Response",
             "Security incidents follow SOP-01 (Incident Response) and SOP-22 (Security Breach "
             "Containment). All incidents must be reported to Natalia Voss within 15 minutes. "
             "See INC-205 (APIGateway TLS expiry) as a reference incident."),
            ("4. Encryption",
             "Data in transit: TLS 1.3 minimum. Data at rest: AES-256. APIGateway enforces "
             "TLS for all inbound requests. Certificate rotation is managed by the Security team."),
            ("5. Monitoring",
             "All systems are monitored via Grafana and Datadog. Alerts page the relevant team "
             "on-call. Security events are centralised in the SIEM managed by Natalia Voss."),
        ],
    )
    generated.append(str(RAW_DIR / "POL-003.pdf"))

    gen_policy_pdf(
        "POL-004", "Remote Work Policy", "All",
        [
            ("1. Purpose",
             "Governs remote work arrangements for ACME Corp employees. Ensures security "
             "and productivity standards are maintained outside the office."),
            ("2. Security Requirements",
             "Remote workers must use VPN to access internal systems (Payment-Service, Auth-DB, "
             "DataWarehouse, etc.). VPN access is provisioned per SOP-03. Policy enforcement "
             "by Natalia Voss (Security)."),
            ("3. Equipment",
             "Company-issued laptops only. Personal devices require MDM enrollment approved "
             "by the Security team. Encryption (FileVault / BitLocker) is mandatory."),
            ("4. Data Handling",
             "No PII downloads to local machines. Data must remain in ACME-managed systems. "
             "See POL-002 for data retention obligations and POL-003 for security controls."),
        ],
    )
    generated.append(str(RAW_DIR / "POL-004.pdf"))

    # --- Incidents (Markdown) ---
    for inc in INCIDENTS:
        gen_incident_md(inc)
        generated.append(str(RAW_DIR / f"{inc['id']}.md"))

    # --- SOPs (Markdown) ---
    sop_configs = [
        ("SOP-01", "Incident Response Procedure", "Infrastructure", [
            "Acknowledge the PagerDuty alert within 5 minutes.",
            "Assess severity (P1–P4) using the incident matrix in the runbook.",
            "Page the owning team lead (see PEOPLE directory in FAQ.md).",
            "Open a war-room Slack channel: #incident-<INC-ID>.",
            "Identify root cause using Grafana dashboards and Datadog logs.",
            "Apply remediation steps from the system-specific runbook.",
            "Validate recovery via health-check endpoints.",
            "Write post-mortem within 48 hours and update this SOP if gaps found.",
        ]),
        ("SOP-02", "Data Backup and Recovery", "Data Engineering", [
            "Verify backup status in the DataWarehouse backup dashboard.",
            "Identify the last clean snapshot (use the data catalog managed by Chen Wei).",
            "Notify stakeholders: Billing (Priya Sharma) if transaction data affected.",
            "Restore from snapshot to staging environment first.",
            "Run data integrity checks (row counts, checksums).",
            "Promote to production after sign-off from Chen Wei.",
            "Update the backup log and notify affected teams.",
        ]),
        ("SOP-03", "Access Provisioning", "Security", [
            "Receive access request ticket with manager approval.",
            "Verify requester identity via Auth-DB MFA.",
            "Check POL-003 to confirm access level is permitted.",
            "Grant access in the identity management system.",
            "Log the provisioning event in the audit trail.",
            "Notify the requester and their manager.",
            "Schedule access review for 90 days.",
        ]),
        ("SOP-04", "Change Management", "Infrastructure", [
            "Submit change request in the ITSM tool.",
            "Obtain approval from the owning team lead.",
            "Schedule the change during approved maintenance windows.",
            "Run automated tests in staging (CI/CD pipeline).",
            "Deploy to production with rollback plan ready.",
            "Monitor Grafana dashboards for 30 minutes post-deployment.",
            "Close the change request and document outcomes.",
        ]),
        ("SOP-05", "On-Call Escalation", "Infrastructure", [
            "Receive PagerDuty alert (auto-paged on P1/P2).",
            "Acknowledge within 5 minutes to prevent escalation.",
            "If unable to resolve in 20 minutes: escalate to team lead.",
            "Team lead escalation path: Marcus Lee → Natalia Voss → VP Engineering.",
            "For cross-team incidents, coordinate in #incident-war-room Slack channel.",
            "Document all actions in the incident ticket.",
        ]),
        ("SOP-17", "Payment Service Restoration", "Billing", [
            "Confirm Payment-Service is returning 5xx errors via APIGateway logs.",
            "Check Auth-DB connection pool metrics on Grafana (primary dependency).",
            "If Auth-DB is saturated: page Marcus Lee (Infrastructure) immediately.",
            "Apply Auth-DB connection pool increase per the runbook parameters.",
            "Enable Payment-Service circuit breaker to shed load.",
            "Verify Payment-Service health-check returns 200.",
            "Confirm transaction processing resumes (check Billing dashboard).",
            "Notify Priya Sharma (Billing Lead) of resolution.",
            "File INC report and update this SOP if new failure mode discovered.",
        ]),
        ("SOP-22", "Security Breach Containment", "Security", [
            "Alert Natalia Voss (Security Lead) immediately — within 15 minutes of detection.",
            "Isolate affected systems from the network (coordinate with Marcus Lee).",
            "Revoke compromised credentials via Auth-DB admin interface.",
            "Preserve logs (do NOT delete — legal requirement per POL-002).",
            "Notify legal/compliance team if PII may be exposed.",
            "Conduct forensic analysis with Security team.",
            "Document breach timeline and apply fixes.",
            "Issue post-breach security review and update POL-003 if needed.",
        ]),
    ]
    for sop_id, title, team, steps in sop_configs:
        gen_sop_md(sop_id, title, team, steps)
        generated.append(str(RAW_DIR / f"{sop_id}.md"))

    # --- Technical Manuals (Markdown) ---
    system_teams = [
        ("Payment-Service", "Billing"),
        ("Auth-DB", "Infrastructure"),
        ("UserProfile-API", "Customer Success"),
        ("DataWarehouse", "Data Engineering"),
        ("APIGateway", "Security"),
    ]
    for system, team in system_teams:
        gen_manual_md(system, team)
        slug = system.lower().replace("-", "_")
        generated.append(str(RAW_DIR / f"manual_{slug}.md"))

    # --- FAQ ---
    gen_faq_md()
    generated.append(str(RAW_DIR / "FAQ.md"))

    # --- CSVs ---
    gen_users_csv()
    generated.append(str(RAW_DIR / "users.csv"))
    gen_products_csv()
    generated.append(str(RAW_DIR / "products.csv"))
    gen_transactions_csv()
    generated.append(str(RAW_DIR / "transactions.csv"))

    # doc_metadata must come last (needs the list of generated docs)
    gen_doc_metadata_csv(generated)
    generated.append(str(RAW_DIR / "doc_metadata.csv"))

    print(f"\nDone. {len(generated)} files written to {RAW_DIR}/\n")
    # Persist manifest
    manifest_path = RAW_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {"generated": [str(Path(p).name) for p in generated]},
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  [wrote] {manifest_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
