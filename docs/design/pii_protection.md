# PII Protection: Victim Intake Encryption

> **Status**: Active (v1.0)
> **Last Updated**: April 2026
> **Audience:** Engineers and architects. End-user guidance lives in the `docs/` repo; this file is technical.

## Overview

The platform protects victim PII through targeted Fernet encryption of intake contact fields. Investigation entities (wallets, emails, phone numbers extracted from case narratives) are stored in cleartext — they are evidence, not victim PII. Only the reporter's personal contact information is encrypted at rest.

## What is encrypted

| Field             | Table      | Column            | Encrypted |
| ----------------- | ---------- | ----------------- | --------- |
| Reporter name     | `intakes`  | `reporter_name`   | Yes       |
| Contact email     | `intakes`  | `contact_email`   | Yes       |
| Contact phone     | `intakes`  | `contact_phone`   | Yes       |
| Contact handle    | `intakes`  | `contact_handle`  | Yes       |
| Case entities     | `entities` | `value`           | No        |
| Case text/summary | `cases`    | `text`, `summary` | No        |

## Encryption scheme

- **Algorithm:** Fernet (AES-128-CBC + HMAC-SHA256), provided by the `cryptography` library.
- **Key:** A single Fernet key supplied via `I4G_CRYPTO__PII_KEY` env var. In cloud environments, the key is stored in Secret Manager (`projects/i4g-{env}/secrets/pii-encryption-key`).
- **Encrypt on write:** `IntakeStore.create_intake()` encrypts the four contact fields before the DB insert.
- **Decrypt on read:** `IntakeStore.get_intake()` / `list_intakes()` decrypt contact fields, gated by analyst role.
- **Missing key:** When `I4G_CRYPTO__PII_KEY` is not set (e.g., `I4G_ENV=local`), contact fields are stored in cleartext.

## Audit logging

Every decryption of victim contact fields is logged to the `audit_log` table in the main database:

- **actor:** The authenticated user who requested the decryption.
- **action:** `decrypt_contact`
- **target:** The intake ID.
- **timestamp:** UTC timestamp of the access.

The `GET /intakes/{id}/contact` endpoint returns decrypted contact info and writes an audit record on each call.

## Victim-contact redaction in case text

During ingestion, the reporter's `contact_email` and `contact_phone` (from the linked intake) are replaced with `[VICTIM_EMAIL]` and `[VICTIM_PHONE]` markers in the case narrative text. This prevents victim contact info from appearing in search results or vector embeddings.

## Key management

- **Local dev:** No key required. Contact fields are stored unencrypted.
- **Cloud (dev/prod):** A Fernet key is generated and stored in Secret Manager. Cloud Run services receive it via `--set-secrets="I4G_CRYPTO__PII_KEY=pii-encryption-key:latest"`.
- **Rotation:** When rotation is needed, use `MultiFernet` with the new key first and old key second, then re-encrypt existing records. This is not yet implemented — the current design uses a single key.

## Related docs

- [Compliance & data retention](../compliance.md)
- [Architecture overview](architecture.md)
- [Data model](data_model.md)
