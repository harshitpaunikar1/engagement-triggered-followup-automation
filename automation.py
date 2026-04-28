"""
Engagement-triggered follow-up automation engine.
Monitors engagement signals (opens, clicks, form fills) and triggers personalized follow-up sequences.
"""
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class EngagementEvent:
    lead_id: str
    event_type: str           # email_open, link_click, form_submit, page_view
    source: str               # campaign name or page URL
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FollowUpTask:
    lead_id: str
    task_type: str            # send_email, assign_rep, schedule_call, add_tag
    priority: int             # 1=high, 2=medium, 3=low
    payload: Dict[str, Any] = field(default_factory=dict)
    scheduled_at: Optional[datetime] = None
    status: str = "pending"   # pending, sent, failed


@dataclass
class FollowUpRule:
    rule_id: str
    trigger_event: str
    conditions: Dict[str, Any]  # e.g. {"min_score": 70, "max_days_since_last_touch": 7}
    action_type: str
    action_payload_template: Dict[str, Any]
    delay_hours: float = 0.0
    priority: int = 2
    enabled: bool = True


class LeadScoreTracker:
    """Accumulates engagement events into a numeric lead score per lead."""

    EVENT_WEIGHTS = {
        "form_submit": 30,
        "link_click": 10,
        "email_open": 5,
        "page_view": 2,
    }

    def __init__(self):
        self._scores: Dict[str, float] = {}
        self._events: Dict[str, List[EngagementEvent]] = {}

    def ingest(self, event: EngagementEvent) -> float:
        """Add event weight to lead score and return new score."""
        weight = self.EVENT_WEIGHTS.get(event.event_type, 1)
        self._scores[event.lead_id] = self._scores.get(event.lead_id, 0) + weight
        self._events.setdefault(event.lead_id, []).append(event)
        return self._scores[event.lead_id]

    def get_score(self, lead_id: str) -> float:
        return self._scores.get(lead_id, 0)

    def days_since_last_touch(self, lead_id: str) -> Optional[float]:
        events = self._events.get(lead_id, [])
        if not events:
            return None
        last_ts = max(e.timestamp for e in events)
        return (time.time() - last_ts) / 86400

    def recent_events(self, lead_id: str, hours: float = 24) -> List[EngagementEvent]:
        cutoff = time.time() - hours * 3600
        return [e for e in self._events.get(lead_id, []) if e.timestamp >= cutoff]


class RuleEngine:
    """Evaluates follow-up rules against engagement events and queues tasks."""

    def __init__(self, score_tracker: LeadScoreTracker):
        self.score_tracker = score_tracker
        self.rules: List[FollowUpRule] = []
        self.task_queue: List[FollowUpTask] = []
        self._triggered: Dict[str, set] = {}  # lead_id -> set of rule_ids already triggered

    def add_rule(self, rule: FollowUpRule) -> None:
        self.rules.append(rule)

    def _check_conditions(self, rule: FollowUpRule, event: EngagementEvent) -> bool:
        lead_id = event.lead_id
        conds = rule.conditions
        if "min_score" in conds:
            if self.score_tracker.get_score(lead_id) < conds["min_score"]:
                return False
        if "max_days_since_last_touch" in conds:
            days = self.score_tracker.days_since_last_touch(lead_id)
            if days is None or days > conds["max_days_since_last_touch"]:
                return False
        if "required_source" in conds:
            if event.source != conds["required_source"]:
                return False
        return True

    def evaluate(self, event: EngagementEvent) -> List[FollowUpTask]:
        """Evaluate all enabled rules against an event and return new tasks."""
        new_tasks = []
        for rule in self.rules:
            if not rule.enabled:
                continue
            if rule.trigger_event != event.event_type:
                continue
            triggered_set = self._triggered.setdefault(event.lead_id, set())
            if rule.rule_id in triggered_set:
                continue
            if not self._check_conditions(rule, event):
                continue
            schedule_time = None
            if rule.delay_hours > 0:
                schedule_time = datetime.utcnow() + timedelta(hours=rule.delay_hours)
            payload = {**rule.action_payload_template, "lead_id": event.lead_id,
                       "triggered_by": event.event_type, "source": event.source}
            task = FollowUpTask(
                lead_id=event.lead_id,
                task_type=rule.action_type,
                priority=rule.priority,
                payload=payload,
                scheduled_at=schedule_time,
                status="pending",
            )
            new_tasks.append(task)
            self.task_queue.append(task)
            triggered_set.add(rule.rule_id)
            logger.info("Rule '%s' triggered for lead '%s': %s", rule.rule_id, event.lead_id, rule.action_type)
        return new_tasks


class FollowUpAutomationEngine:
    """
    Orchestrates engagement event ingestion, scoring, rule evaluation, and task dispatch.
    """

    def __init__(self, dispatch_callback: Optional[Callable[[FollowUpTask], None]] = None):
        self.score_tracker = LeadScoreTracker()
        self.rule_engine = RuleEngine(self.score_tracker)
        self.dispatch_callback = dispatch_callback
        self._processed_events = 0

    def add_rule(self, rule: FollowUpRule) -> None:
        self.rule_engine.add_rule(rule)

    def process_event(self, event: EngagementEvent) -> List[FollowUpTask]:
        """Ingest an engagement event, update score, evaluate rules, dispatch tasks."""
        self.score_tracker.ingest(event)
        self._processed_events += 1
        tasks = self.rule_engine.evaluate(event)
        for task in tasks:
            if self.dispatch_callback:
                try:
                    self.dispatch_callback(task)
                except Exception as exc:
                    logger.error("Dispatch callback failed for task %s: %s", task.task_type, exc)
                    task.status = "failed"
        return tasks

    def get_lead_summary(self, lead_id: str) -> Dict:
        return {
            "lead_id": lead_id,
            "score": self.score_tracker.get_score(lead_id),
            "days_since_last_touch": self.score_tracker.days_since_last_touch(lead_id),
            "pending_tasks": sum(
                1 for t in self.rule_engine.task_queue
                if t.lead_id == lead_id and t.status == "pending"
            ),
        }

    def engine_stats(self) -> Dict:
        tasks = self.rule_engine.task_queue
        return {
            "events_processed": self._processed_events,
            "total_tasks": len(tasks),
            "pending_tasks": sum(1 for t in tasks if t.status == "pending"),
            "failed_tasks": sum(1 for t in tasks if t.status == "failed"),
        }


if __name__ == "__main__":
    def task_printer(task: FollowUpTask):
        print(f"  DISPATCH [{task.priority}] {task.task_type} for {task.lead_id}: {task.payload}")

    engine = FollowUpAutomationEngine(dispatch_callback=task_printer)

    engine.add_rule(FollowUpRule(
        rule_id="high_score_call",
        trigger_event="form_submit",
        conditions={"min_score": 30},
        action_type="schedule_call",
        action_payload_template={"reason": "High engagement after form submit"},
        delay_hours=1.0,
        priority=1,
    ))
    engine.add_rule(FollowUpRule(
        rule_id="click_email",
        trigger_event="link_click",
        conditions={},
        action_type="send_email",
        action_payload_template={"template": "click_followup_v1"},
        delay_hours=0.5,
        priority=2,
    ))

    events = [
        EngagementEvent("lead_001", "email_open", "campaign_q2"),
        EngagementEvent("lead_001", "link_click", "campaign_q2"),
        EngagementEvent("lead_001", "form_submit", "landing_page_A"),
        EngagementEvent("lead_002", "email_open", "campaign_q2"),
    ]

    print("Processing events...")
    for ev in events:
        tasks = engine.process_event(ev)
        if tasks:
            print(f"Event '{ev.event_type}' by '{ev.lead_id}' triggered {len(tasks)} task(s).")

    print("\nLead 001 summary:", engine.get_lead_summary("lead_001"))
    print("Engine stats:", engine.engine_stats())
