import json
import time
from email.utils import parseaddr
from typing import Any, ClassVar
from urllib.parse import quote

import jwt

from app.config import get_settings
from app.engine.net import raise_for_status, safe_request
from app.engine.nodes.base import (
    NodeCategory,
    NodeContext,
    NodeExecutionError,
    NodeResult,
    NodeType,
    require_list,
)
from app.services import email as email_service


def credential_field(*types: str) -> dict[str, Any]:
    return {
        "type": "string",
        "title": "Credential",
        "x-ui": "credential",
        "x-credential-types": list(types),
    }


def auth_headers(credential: dict[str, Any]) -> dict[str, str]:
    if "header_name" in credential:
        return {credential["header_name"]: credential["header_value"]}
    if "token" in credential:
        return {"Authorization": f"Bearer {credential['token']}"}
    return {}


class IntegrationNode(NodeType):
    category: ClassVar[NodeCategory] = NodeCategory.INTEGRATION


class HttpRequestNode(IntegrationNode):
    type = "http_request"
    label = "HTTP request"
    description = "Call any HTTP API. JSON responses are parsed automatically."
    icon = "globe"
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "method": {
                "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                "title": "Method",
                "default": "GET",
            },
            "url": {"type": "string", "title": "URL", "minLength": 1},
            "headers": {"type": "object", "title": "Headers", "x-ui": "json"},
            "query": {"type": "object", "title": "Query parameters", "x-ui": "json"},
            "body": {"title": "JSON body", "x-ui": "json"},
            "credential_id": credential_field("http_header", "bearer_token"),
            "fail_on_error_status": {
                "type": "boolean",
                "title": "Fail on 4xx/5xx",
                "default": True,
            },
        },
        "required": ["method", "url"],
    }

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        headers = {str(k): str(v) for k, v in (config.get("headers") or {}).items()}
        if config.get("credential_id"):
            credential = await ctx.resolve_credential(
                config["credential_id"], ("http_header", "bearer_token")
            )
            headers.update(auth_headers(credential))
        result = await safe_request(
            ctx.http,
            config["method"],
            config["url"],
            headers=headers,
            params=config.get("query") or None,
            json_body=config.get("body") if config["method"] != "GET" else None,
        )
        if config.get("fail_on_error_status", True):
            raise_for_status(result, "The server")
        return NodeResult(
            output={"status": result.status, "headers": result.headers, "body": result.body}
        )


class SendEmailNode(IntegrationNode):
    type = "send_email"
    label = "Send email"
    description = "Send a plain-text email through the platform's mail server."
    icon = "mail"
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "to": {"type": "string", "title": "To (comma-separated)", "minLength": 3},
            "subject": {"type": "string", "title": "Subject", "minLength": 1},
            "body": {"type": "string", "title": "Body", "x-ui": "textarea", "minLength": 1},
        },
        "required": ["to", "subject", "body"],
    }

    async def execute(self, ctx: NodeContext) -> NodeResult:
        recipients = [r.strip() for r in str(ctx.config["to"]).split(",") if r.strip()]
        invalid = [r for r in recipients if "@" not in parseaddr(r)[1]]
        if not recipients or invalid:
            raise NodeExecutionError(
                f"Invalid recipient: {', '.join(invalid) or 'none'}", retryable=False
            )
        if len(recipients) > 20:
            raise NodeExecutionError("At most 20 recipients per email", retryable=False)
        email = email_service.OutgoingEmail(
            to=", ".join(recipients),
            subject=str(ctx.config["subject"])[:200],
            text=str(ctx.config["body"]),
        )
        try:
            await email_service.deliver_email(email)
        except OSError as exc:
            raise NodeExecutionError(f"Could not send email: {exc}") from exc
        return NodeResult(output={"sent_to": recipients})


class SlackMessageNode(IntegrationNode):
    type = "slack_message"
    label = "Slack message"
    description = "Post a message to a Slack channel through an incoming webhook."
    icon = "slack"
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "credential_id": credential_field("slack_webhook"),
            "text": {"type": "string", "title": "Message", "x-ui": "textarea", "minLength": 1},
        },
        "required": ["credential_id", "text"],
    }

    async def execute(self, ctx: NodeContext) -> NodeResult:
        credential = await ctx.resolve_credential(ctx.config["credential_id"], ("slack_webhook",))
        result = await safe_request(
            ctx.http, "POST", credential["url"], json_body={"text": ctx.config["text"]}
        )
        raise_for_status(result, "Slack")
        return NodeResult(output={"ok": True})


class TelegramMessageNode(IntegrationNode):
    type = "telegram_message"
    label = "Telegram message"
    description = "Send a message from your Telegram bot to a chat."
    icon = "send"
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "credential_id": credential_field("telegram_bot"),
            "chat_id": {"type": "string", "title": "Chat ID", "minLength": 1},
            "text": {"type": "string", "title": "Message", "x-ui": "textarea", "minLength": 1},
        },
        "required": ["credential_id", "chat_id", "text"],
    }

    async def execute(self, ctx: NodeContext) -> NodeResult:
        credential = await ctx.resolve_credential(ctx.config["credential_id"], ("telegram_bot",))
        base = get_settings().telegram_api_url
        result = await safe_request(
            ctx.http,
            "POST",
            f"{base}/bot{credential['token']}/sendMessage",
            json_body={"chat_id": ctx.config["chat_id"], "text": ctx.config["text"]},
        )
        raise_for_status(result, "Telegram")
        message_id = (
            result.body.get("result", {}).get("message_id")
            if isinstance(result.body, dict)
            else None
        )
        return NodeResult(output={"message_id": message_id})


class GoogleSheetsAppendNode(IntegrationNode):
    type = "google_sheets_append"
    label = "Google Sheets: add row"
    description = "Append a row to a spreadsheet shared with your service account."
    icon = "sheet"
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "credential_id": credential_field("google_service_account"),
            "spreadsheet_id": {"type": "string", "title": "Spreadsheet ID", "minLength": 10},
            "range": {"type": "string", "title": "Sheet / range", "default": "Sheet1!A1"},
            "values": {
                "type": "array",
                "title": "Row values",
                "items": {"type": "string"},
                "minItems": 1,
                "x-ui": "tags",
            },
        },
        "required": ["credential_id", "spreadsheet_id", "values"],
    }

    async def _access_token(self, ctx: NodeContext, key: dict[str, Any]) -> str:
        settings = get_settings()
        now = int(time.time())
        assertion = jwt.encode(
            {
                "iss": key["client_email"],
                "scope": "https://www.googleapis.com/auth/spreadsheets",
                "aud": settings.google_token_url,
                "iat": now,
                "exp": now + 3600,
            },
            key["private_key"],
            algorithm="RS256",
        )
        result = await safe_request(
            ctx.http,
            "POST",
            settings.google_token_url,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
        raise_for_status(result, "Google OAuth")
        if not isinstance(result.body, dict) or "access_token" not in result.body:
            raise NodeExecutionError("Google did not return an access token")
        return str(result.body["access_token"])

    async def execute(self, ctx: NodeContext) -> NodeResult:
        credential = await ctx.resolve_credential(
            ctx.config["credential_id"], ("google_service_account",)
        )
        try:
            key = json.loads(credential["service_account_json"])
        except json.JSONDecodeError as exc:
            raise NodeExecutionError(
                "Service account key is not valid JSON", retryable=False
            ) from exc
        token = await self._access_token(ctx, key)
        values = [str(v) for v in require_list(ctx.config["values"], "values")]
        sheet_range = quote(str(ctx.config.get("range") or "Sheet1!A1"), safe="!:")
        url = (
            f"{get_settings().google_sheets_api_url}/spreadsheets/{ctx.config['spreadsheet_id']}"
            f"/values/{sheet_range}:append"
        )
        result = await safe_request(
            ctx.http,
            "POST",
            url,
            headers={"Authorization": f"Bearer {token}"},
            params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
            json_body={"values": [values]},
        )
        raise_for_status(result, "Google Sheets")
        updated = result.body.get("updates", {}) if isinstance(result.body, dict) else {}
        return NodeResult(output={"updated_range": updated.get("updatedRange"), "values": values})
