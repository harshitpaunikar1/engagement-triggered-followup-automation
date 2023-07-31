# Engagement-Triggered Follow-Up Automation Diagrams

Generated on 2026-04-26T04:29:37Z from README narrative plus project blueprint requirements.

## Engagement signal → trigger flow

```mermaid
flowchart TD
    N1["Step 1\nMapped buyer journey and defined follow-up SLAs by segment and stage"]
    N2["Step 2\nCaptured engagement signals (opens, clicks, page visits, replies, inactivity) and "]
    N1 --> N2
    N3["Step 3\nDesigned rules engine/state machine to pick templates and timing; added throttling"]
    N2 --> N3
    N4["Step 4\nImplemented Python workflows with scheduled jobs, CRM/API connectors, dynamic HTML"]
    N3 --> N4
    N5["Step 5\nRan QA with seed mailboxes, A/B tests, monitoring for bounces, spam indicators, la"]
    N4 --> N5
```

## Rules engine state machine

```mermaid
flowchart LR
    N1["Inputs\nInbound API requests and job metadata"]
    N2["Decision Layer\nRules engine state machine"]
    N1 --> N2
    N3["User Surface\nAPI-facing integration surface described in the README"]
    N2 --> N3
    N4["Business Outcome\nSLA adherence"]
    N3 --> N4
```

## Evidence Gap Map

```mermaid
flowchart LR
    N1["Present\nREADME, diagrams.md, local SVG assets"]
    N2["Missing\nSource code, screenshots, raw datasets"]
    N1 --> N2
    N3["Next Task\nReplace inferred notes with checked-in artifacts"]
    N2 --> N3
```
