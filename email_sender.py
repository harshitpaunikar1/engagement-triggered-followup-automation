"""
Email sender module for engagement-triggered follow-up automation.
Renders Jinja2-style templates and dispatches via SMTP with retry logic.
"""
import logging
import re
import smtplib
import time
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SMTPConfig:
    host: str = "localhost"
    port: int = 587
    use_tls: bool = True
    username: str = ""
    password: str = ""
    sender_email: str = "noreply@example.com"
    sender_name: str = "Follow-Up Bot"
    timeout_s: int = 10


@dataclass
class EmailTemplate:
    template_id: str
    subject: str
    body_text: str
    body_html: Optional[str] = None

    def render(self, variables: Dict[str, Any]) -> "EmailTemplate":
        """Replace {{key}} placeholders with variable values."""
        def replace(text: str) -> str:
            for k, v in variables.items():
                text = text.replace(f"{{{{{k}}}}}", str(v))
            return text
        return EmailTemplate(
            template_id=self.template_id,
            subject=replace(self.subject),
            body_text=replace(self.body_text),
            body_html=replace(self.body_html) if self.body_html else None,
        )


@dataclass
class EmailMessage:
    to_email: str
    to_name: str
    template: EmailTemplate
    variables: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SendResult:
    message_id: str
    to_email: str
    template_id: str
    success: bool
    error: Optional[str] = None
    attempts: int = 1
    sent_at: float = field(default_factory=time.time)


class TemplateLibrary:
    """Manages a collection of email templates keyed by template_id."""

    BUILTIN_TEMPLATES = {
        "click_followup_v1": EmailTemplate(
            template_id="click_followup_v1",
            subject="You showed interest - here's what's next, {{first_name}}",
            body_text=(
                "Hi {{first_name}},\n\n"
                "We noticed you clicked through one of our recent emails.\n"
                "We'd love to share more about how we can help you.\n\n"
                "Reply to this email or book a quick call.\n\n"
                "Best,\n{{sender_name}}"
            ),
        ),
        "form_submit_high_score": EmailTemplate(
            template_id="form_submit_high_score",
            subject="Thanks for reaching out, {{first_name}}!",
            body_text=(
                "Hi {{first_name}},\n\n"
                "Thanks for filling out our form. Our team will reach out within 24 hours.\n\n"
                "In the meantime, check out our resources: {{resource_url}}\n\n"
                "Best,\n{{sender_name}}"
            ),
        ),
        "re_engagement": EmailTemplate(
            template_id="re_engagement",
            subject="We miss you, {{first_name}}",
            body_text=(
                "Hi {{first_name}},\n\n"
                "It's been a while since we've heard from you.\n"
                "Is there anything we can help with?\n\n"
                "Best,\n{{sender_name}}"
            ),
        ),
    }

    def __init__(self):
        self._templates: Dict[str, EmailTemplate] = dict(self.BUILTIN_TEMPLATES)

    def add(self, template: EmailTemplate) -> None:
        self._templates[template.template_id] = template

    def get(self, template_id: str) -> Optional[EmailTemplate]:
        return self._templates.get(template_id)

    def list_templates(self) -> List[str]:
        return list(self._templates.keys())


class EmailSender:
    """
    Sends emails via SMTP with template rendering, retry logic, and delivery tracking.
    Supports dry-run mode for testing without real SMTP connectivity.
    """

    def __init__(self, smtp_config: SMTPConfig, template_library: TemplateLibrary,
                 dry_run: bool = True, max_retries: int = 3, retry_delay_s: float = 2.0):
        self.smtp_config = smtp_config
        self.templates = template_library
        self.dry_run = dry_run
        self.max_retries = max_retries
        self.retry_delay_s = retry_delay_s
        self._sent_log: List[SendResult] = []

    def _build_mime(self, to_email: str, to_name: str, rendered: EmailTemplate) -> MIMEMultipart:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{self.smtp_config.sender_name} <{self.smtp_config.sender_email}>"
        msg["To"] = f"{to_name} <{to_email}>"
        msg["Subject"] = rendered.subject
        msg.attach(MIMEText(rendered.body_text, "plain"))
        if rendered.body_html:
            msg.attach(MIMEText(rendered.body_html, "html"))
        return msg

    def _smtp_send(self, mime_msg: MIMEMultipart, to_email: str) -> None:
        if self.smtp_config.use_tls:
            server = smtplib.SMTP(self.smtp_config.host, self.smtp_config.port,
                                  timeout=self.smtp_config.timeout_s)
            server.ehlo()
            server.starttls()
        else:
            server = smtplib.SMTP(self.smtp_config.host, self.smtp_config.port,
                                  timeout=self.smtp_config.timeout_s)
        if self.smtp_config.username:
            server.login(self.smtp_config.username, self.smtp_config.password)
        server.sendmail(self.smtp_config.sender_email, to_email, mime_msg.as_string())
        server.quit()

    def send(self, message: EmailMessage) -> SendResult:
        """Render template and send email with retry logic."""
        template = self.templates.get(message.template.template_id)
        if template is None:
            template = message.template
        variables = {"sender_name": self.smtp_config.sender_name, **message.variables}
        rendered = template.render(variables)
        message_id = f"{message.template.template_id}_{message.to_email}_{int(time.time())}"

        if self.dry_run:
            logger.info("[DRY RUN] Would send '%s' to %s", rendered.subject, message.to_email)
            result = SendResult(message_id=message_id, to_email=message.to_email,
                                template_id=template.template_id, success=True, attempts=1)
            self._sent_log.append(result)
            return result

        mime_msg = self._build_mime(message.to_email, message.to_name, rendered)
        attempts = 0
        last_error = None
        while attempts < self.max_retries:
            attempts += 1
            try:
                self._smtp_send(mime_msg, message.to_email)
                result = SendResult(message_id=message_id, to_email=message.to_email,
                                    template_id=template.template_id, success=True, attempts=attempts)
                self._sent_log.append(result)
                logger.info("Email sent to %s (attempt %d)", message.to_email, attempts)
                return result
            except Exception as exc:
                last_error = str(exc)
                logger.warning("Send attempt %d failed: %s", attempts, exc)
                if attempts < self.max_retries:
                    time.sleep(self.retry_delay_s)

        result = SendResult(message_id=message_id, to_email=message.to_email,
                            template_id=template.template_id, success=False,
                            error=last_error, attempts=attempts)
        self._sent_log.append(result)
        return result

    def delivery_stats(self) -> Dict:
        total = len(self._sent_log)
        success = sum(1 for r in self._sent_log if r.success)
        return {
            "total": total,
            "success": success,
            "failed": total - success,
            "success_rate_pct": round(success / total * 100, 1) if total > 0 else 0.0,
        }


if __name__ == "__main__":
    lib = TemplateLibrary()
    smtp_config = SMTPConfig(
        host="smtp.example.com",
        port=587,
        sender_email="noreply@example.com",
        sender_name="Sales Bot",
    )
    sender = EmailSender(smtp_config=smtp_config, template_library=lib, dry_run=True)

    template = lib.get("click_followup_v1")
    message = EmailMessage(
        to_email="john@example.com",
        to_name="John Doe",
        template=template,
        variables={"first_name": "John"},
    )
    result = sender.send(message)
    print("Send result:", result)
    print("Delivery stats:", sender.delivery_stats())
    print("Available templates:", lib.list_templates())
