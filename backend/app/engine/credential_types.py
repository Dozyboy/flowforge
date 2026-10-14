"""Credential types: which secret fields each integration needs."""

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CredentialField:
    name: str
    label: str
    secret: bool = True
    multiline: bool = False


@dataclass(frozen=True)
class CredentialType:
    type: str
    label: str
    description: str
    fields: tuple[CredentialField, ...]

    def validate(self, data: dict[str, Any]) -> list[str]:
        problems = [
            f"{f.label} is required"
            for f in self.fields
            if not isinstance(data.get(f.name), str) or not data[f.name].strip()
        ]
        if self.type == "google_service_account" and not problems:
            try:
                parsed = json.loads(data["service_account_json"])
                if not {"client_email", "private_key"} <= set(parsed):
                    problems.append("The JSON key must contain client_email and private_key")
            except json.JSONDecodeError:
                problems.append("Service account key must be valid JSON")
        if (
            self.type == "slack_webhook"
            and not problems
            and not data["url"].startswith("https://hooks.slack.com/")
        ):
            problems.append("Slack webhook URLs start with https://hooks.slack.com/")
        return problems

    def describe(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "label": self.label,
            "description": self.description,
            "fields": [
                {"name": f.name, "label": f.label, "secret": f.secret, "multiline": f.multiline}
                for f in self.fields
            ],
        }


CREDENTIAL_TYPES: dict[str, CredentialType] = {
    t.type: t
    for t in (
        CredentialType(
            "http_header",
            "HTTP header",
            "Sends a fixed header, e.g. X-API-Key, with HTTP requests.",
            (
                CredentialField("header_name", "Header name", secret=False),
                CredentialField("header_value", "Header value"),
            ),
        ),
        CredentialType(
            "bearer_token",
            "Bearer token",
            "Sends Authorization: Bearer <token> with HTTP requests.",
            (CredentialField("token", "Token"),),
        ),
        CredentialType(
            "slack_webhook",
            "Slack incoming webhook",
            "Posts messages to one Slack channel.",
            (CredentialField("url", "Webhook URL"),),
        ),
        CredentialType(
            "telegram_bot",
            "Telegram bot",
            "Sends messages as a bot created with @BotFather.",
            (CredentialField("token", "Bot token"),),
        ),
        CredentialType(
            "google_service_account",
            "Google service account",
            "Appends rows to Google Sheets shared with the service account email.",
            (CredentialField("service_account_json", "JSON key", multiline=True),),
        ),
    )
}
