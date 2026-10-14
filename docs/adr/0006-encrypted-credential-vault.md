# ADR-0006: Encrypted, write-only credential vault

- Status: Accepted

## Context

Integrations need secrets: Slack webhook URLs, Telegram bot tokens, API keys for HTTP calls, Google service-account keys. They must not appear in workflow JSON (which is exported and versioned), in the browser, in logs, or in plain text in database backups.

## Decision

- Secrets are stored in `credentials.encrypted_data`, encrypted with Fernet (AES-128-CBC + HMAC-SHA256) using `CREDENTIALS_KEY` from the environment.
- Nodes reference credentials by ID in their config; exports therefore contain no secrets.
- The API is write-only: create, rename/replace, delete, list metadata. There is no endpoint that returns the decrypted value.
- Decryption happens only in the worker, at the moment a node executes, and the value is never included in step input/output.

## Consequences

- A database leak alone does not expose secrets; the key is needed too.
- Rotating `CREDENTIALS_KEY` requires re-encrypting rows. `MultiFernet` supports this; a rotation script is listed as future work.
- Users cannot "view" a saved secret, only replace it — the standard behaviour of secret stores.
