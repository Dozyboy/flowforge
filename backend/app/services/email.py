"""Transactional emails. Building the message happens here; delivery happens in the worker."""

import html
from dataclasses import dataclass
from email.message import EmailMessage

import aiosmtplib

from app.config import get_settings
from app.services.jobs import JobQueue


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    text: str
    action_label: str | None = None
    action_url: str | None = None


def _render_html(email: OutgoingEmail) -> str:
    paragraphs = "".join(f"<p>{html.escape(p)}</p>" for p in email.text.split("\n\n") if p.strip())
    button = ""
    if email.action_url and email.action_label:
        button = (
            f'<p><a href="{html.escape(email.action_url)}" style="background:#4f46e5;color:#fff;'
            f'padding:10px 18px;border-radius:6px;text-decoration:none;display:inline-block">'
            f"{html.escape(email.action_label)}</a></p>"
        )
    return (
        '<div style="font-family:system-ui,sans-serif;max-width:560px;margin:auto;color:#0f172a">'
        f"{paragraphs}{button}"
        '<p style="color:#64748b;font-size:12px">FlowForge</p></div>'
    )


async def queue_email(queue: JobQueue, email: OutgoingEmail) -> None:
    await queue.enqueue(
        "send_email",
        to=email.to,
        subject=email.subject,
        text=email.text if not email.action_url else f"{email.text}\n\n{email.action_url}",
        html_body=_render_html(email),
    )


async def deliver_email(email: OutgoingEmail) -> None:
    """Send immediately (used by workflow steps, which already run inside the worker)."""
    text = email.text if not email.action_url else f"{email.text}\n\n{email.action_url}"
    await deliver(email.to, email.subject, text, _render_html(email))


async def deliver(to: str, subject: str, text: str, html_body: str) -> None:
    settings = get_settings()
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    message.add_alternative(html_body, subtype="html")
    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username or None,
        password=settings.smtp_password.get_secret_value() or None,
        start_tls=settings.smtp_use_tls,
    )


def verification_email(to: str, token: str) -> OutgoingEmail:
    url = f"{get_settings().public_app_url}/verify-email?token={token}"
    return OutgoingEmail(
        to=to,
        subject="Verify your email address",
        text="Welcome to FlowForge! Please confirm your email address to finish setting up "
        "your account.",
        action_label="Verify email",
        action_url=url,
    )


def password_reset_email(to: str, token: str) -> OutgoingEmail:
    url = f"{get_settings().public_app_url}/reset-password?token={token}"
    return OutgoingEmail(
        to=to,
        subject="Reset your password",
        text="Someone requested a password reset for your FlowForge account. If this was not "
        "you, you can ignore this email. The link expires in 24 hours.",
        action_label="Reset password",
        action_url=url,
    )


def invitation_email(to: str, workspace_name: str, inviter_name: str, token: str) -> OutgoingEmail:
    url = f"{get_settings().public_app_url}/invitations/accept?token={token}"
    return OutgoingEmail(
        to=to,
        subject=f"{inviter_name} invited you to {workspace_name} on FlowForge",
        text=f"{inviter_name} invited you to join the {workspace_name} workspace on FlowForge.",
        action_label="Accept invitation",
        action_url=url,
    )


def approval_email(to: str, workflow_name: str, message: str, token: str) -> OutgoingEmail:
    url = f"{get_settings().public_app_url}/approvals/{token}"
    return OutgoingEmail(
        to=to,
        subject=f"Approval needed: {workflow_name}",
        text=f"The workflow “{workflow_name}” is waiting for your decision.\n\n{message}",
        action_label="Review and decide",
        action_url=url,
    )


def run_failed_email(to: str, workflow_name: str, error: str, run_url: str) -> OutgoingEmail:
    return OutgoingEmail(
        to=to,
        subject=f"Run failed: {workflow_name}",
        text=f"A run of “{workflow_name}” failed:\n\n{error}",
        action_label="Open run",
        action_url=run_url,
    )
