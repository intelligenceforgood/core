# Google Workspace SMTP Relay for I4G Notifications

Send notification emails from `i4g` services through Google Workspace.
This cookbook covers the **recommended relay path** (production on GCP)
and the **alternative user/password path** (local development or non-GCP
environments).

## When to use this

| Path                            | Use when                                                             |
| ------------------------------- | -------------------------------------------------------------------- |
| **Relay** (recommended)         | You deploy on GCP with a static egress IP. No credentials to manage. |
| **User/password** (alternative) | Local development, or environments without a static egress IP.       |

## Prerequisites

- Google Workspace admin access and a verified domain.
- For relay: GCP project with the static egress IP deployed
  (`terraform output serverless_egress_ip` in `infra/stacks/app/`).
- For user/password: a Google account with 2-Step Verification enabled.

Estimated time: 10–15 minutes (relay) or 20–35 minutes (user/password).

---

## Path A — SMTP Relay (recommended for production)

This path uses `smtp-relay.gmail.com`. Google authenticates by source IP
instead of username/password, so there are no credentials to rotate.

### A1. Retrieve the static egress IP

The IP is already provisioned by Terraform. Retrieve it:

```bash
cd infra/stacks/app
terraform output serverless_egress_ip
```

Copy the IP address (e.g. `34.x.x.x`).

### A2. Wire the VPC connector to core-svc

The VPC connector (`serverless-egress`) routes traffic through Cloud NAT
to the static IP. SSI already uses it; core-svc needs the same wiring.

In `infra/stacks/app/main.tf`, add these two lines inside the
`module "run_core_svc"` block (after the `depends_on` line or alongside
the other service config):

```hcl
vpc_connector                 = google_vpc_access_connector.serverless.id
vpc_connector_egress_settings = "ALL_TRAFFIC"
```

Apply the change:

```bash
cd infra/stacks/app
terraform plan -target=module.run_core_svc
terraform apply -target=module.run_core_svc
```

This routes all core-svc egress through the static IP. SSI already uses
this pattern — latency impact is negligible.

### A3. Allowlist the IP in Google Workspace

1. Sign in to **Google Admin Console** as a super admin.
2. Navigate to **Apps → Google Workspace → Gmail → Routing**.
3. Under **SMTP relay service**, click **Configure** (or **Add another rule**).
4. Set the following:

   | Field           | Value                                            |
   | --------------- | ------------------------------------------------ |
   | Allowed senders | Only addresses in my domains                     |
   | Authentication  | Only accept mail from the specified IP addresses |
   | IP addresses    | Add the static egress IP from step A1            |
   | Encryption      | Require TLS encryption                           |

5. Save. Changes propagate within a few minutes.

### A4. Create a sender identity (optional but recommended)

Create a dedicated mailbox so the sender is a real, auditable address:

1. In Admin Console → **Directory → Users → Add new user**.
2. Create `report@intelligenceforgood.org` (or your preferred sender).
3. No 2-Step Verification or App Password is needed for relay.

### A5. Configure I4G email settings

The email env vars are already added to `core_svc_env_vars` in both
`infra/environments/app/dev/terraform.tfvars` and
`infra/environments/app/prod/terraform.tfvars`:

```hcl
# inside core_svc_env_vars = { ... }
I4G_EMAIL__PROVIDER    = "smtp"
I4G_EMAIL__SMTP_HOST   = "smtp-relay.gmail.com"
I4G_EMAIL__FROM_ADDRESS = "report@intelligenceforgood.org"
```

These are plain env vars (not secrets) — same pattern as `I4G_LLM__PROVIDER`
and every other setting in that block. Deploy with `terraform apply`.

**No `settings.default.toml` change is needed** — the TOML defaults
(`provider = "log"`, `smtp_host = "localhost"`) are safe fallbacks for
local dev where email goes to the log only.

### A6. Validate delivery

1. Deploy core-svc with the new env vars.
2. Trigger a scheduled report or use the Report Builder.
3. Verify:
   - Internal recipient receives the email.
   - External recipient receives the email.
   - SPF/DKIM/DMARC pass (check headers in the received email).
   - No auth errors in Cloud Run logs.

If delivery fails:

- Confirm the static IP in Terraform output matches the IP allowlisted
  in Workspace Admin.
- Confirm the VPC connector is wired to core-svc
  (`gcloud run services describe core-svc --format='value(spec.template.metadata.annotations)'`).
- Check Google Admin → **Email log search** for relay rejections.

---

## Path B — User/Password SMTP (local development)

This path uses `smtp.gmail.com` with a Google App Password. Use it for
local development or environments that cannot use relay.

### B1. Create a dedicated sender mailbox

1. In Admin Console → **Directory → Users → Add new user**.
2. Create `report@intelligenceforgood.org`.
3. Store ownership details in your team secret store.

### B2. Enable 2-Step Verification and generate an App Password

Google requires 2-Step Verification on an account before it can generate
App Passwords. This only affects the sender account — it has no impact
on the relay setup in Path A.

**As Workspace admin (your own account):**

1. Go to [admin.google.com](https://admin.google.com) →
   **Security → Authentication → 2-step verification**.
2. Ensure the policy is set to **Allow users to turn on 2-Step
   Verification** (or **Enforce**). This is an org-wide policy gate.

**Sign in as the sender account (`report@intelligenceforgood.org`):**

You must sign in as the sender account — App Passwords are per-account
and cannot be created from your own admin account.

3. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
   (while signed in as `report@...`).
4. Under **How you sign in to Google**, complete **2-Step Verification**
   setup (phone or authenticator app).
5. After 2-Step Verification is active, go to
   [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
6. Enter app name `i4g-local-dev` and click **Create**.
7. Copy the 16-character password that appears.

Treat this like a secret — `.env.local` for local, Secret Manager for cloud.

### B3. Configure settings

Add to `config/settings.local.toml` (git-ignored):

```toml
[email]
provider = "smtp"
smtp_host = "smtp.gmail.com"
smtp_user = "report@intelligenceforgood.org"
smtp_password = "xxxx xxxx xxxx xxxx"
from_address = "report@intelligenceforgood.org"
```

Or use env vars if you prefer:

```bash
I4G_EMAIL__PROVIDER=smtp
I4G_EMAIL__SMTP_HOST=smtp.gmail.com
I4G_EMAIL__SMTP_USER=report@intelligenceforgood.org
I4G_EMAIL__SMTP_PASSWORD=xxxx xxxx xxxx xxxx
I4G_EMAIL__FROM_ADDRESS=report@intelligenceforgood.org
```

Notes:

- `smtp_password` is the App Password, not the account login password.
  For cloud deployments, put this in Secret Manager — it is a real credential.
- Keep `from_address` aligned with the authenticated sender or a verified
  alias.
- To send from a branded alias (`alerts@intelligenceforgood.org`), add it as
  a "Send mail as" address in the sender account's Gmail settings.

### B4. Validate delivery

Run the API locally (`uvicorn i4g.api.app:app --reload`), trigger a
scheduled report, and verify:

1. Internal and external recipients receive the email.
2. No auth errors in application logs.
3. SPF/DKIM/DMARC pass.

If delivery fails:

- Confirm 2-Step Verification is active on the sender account.
- Confirm the App Password is current and not revoked.
- Confirm host/port are `smtp.gmail.com` / `587`.

---

## How the email service works

The `EmailSettings` section in `i4g.settings` controls delivery:

| Setting                    | Default             | Notes                                                        |
| -------------------------- | ------------------- | ------------------------------------------------------------ |
| `I4G_EMAIL__PROVIDER`      | `log`               | `log` = log-only, `smtp` = real delivery                     |
| `I4G_EMAIL__SMTP_HOST`     | `localhost`         | `smtp-relay.gmail.com` (relay) or `smtp.gmail.com` (user/pw) |
| `I4G_EMAIL__SMTP_PORT`     | `587`               | STARTTLS port                                                |
| `I4G_EMAIL__SMTP_USER`     | (empty)             | Leave empty for relay; set for user/password                 |
| `I4G_EMAIL__SMTP_PASSWORD` | (empty)             | Leave empty for relay; App Password for user/password        |
| `I4G_EMAIL__FROM_ADDRESS`  | `noreply@i4g.local` | Must be a real address in your domain                        |
| `I4G_EMAIL__USE_TLS`       | `true`              | Always keep enabled                                          |

When `SMTP_USER` and `SMTP_PASSWORD` are empty, the email service skips
authentication — this is the relay path. When both are set, it uses
SMTP LOGIN — this is the user/password path.

See: `core/src/i4g/services/email_service.py`,
`core/src/i4g/settings/sections/jobs.py` (`EmailSettings`).

## Related docs

- [Cookbook index](README.md)
- [Bootstrap and environment patterns](bootstrap_environments.md)
- [Settings manifest and env-var reference](../../docs/config/README.md)
- [Infra: stacks/app/main.tf](../../../infra/stacks/app/main.tf) — VPC connector and static IP
