# Identity & Access Management Strategy

**Status:** Active (v2.0) — February 14, 2026
**Audience:** Engineering, security reviewers, product stakeholders across `core`, `planning`, and `ui`

This document is the single source of truth for how we authenticate users, authorize workloads, and evolve IAM across the i4g platform. It consolidates IAM content from `architecture.md`, planning artifacts, and the UI books so every repository references one canonical strategy. Updates to IAM MUST originate here.

---

## 1. Objectives and Scope

1. **Protect victims and analysts** — tokenize PII, gate privileged tooling, and log every access.
2. **Support multiple personas** — victims/end users, volunteer analysts, law enforcement (LEO), and automated jobs.
3. **Enable fast iteration** — today’s prototype runs entirely on Cloud Run with Google Identity; we need a pragmatic stopgap while designing the long-term zero-trust model.
4. **Document the path forward** — outline future-state controls (VPN, per-role endpoints, self-serve IAM) even if unimplemented.

**Covered repositories:** `core/`, `planning/`, `ui/`, `infra/`. Any IAM mention in other docs must reference this file.

---

## 2. Personas & Role Expectations

| Persona               | Capabilities                                   | Entry Requirements                                       | Near-term Controls                                                               | Future Controls                                                       |
| --------------------- | ---------------------------------------------- | -------------------------------------------------------- | -------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| Victim / End User     | Submit cases, upload evidence, check status    | Google account (temporary), future passkey/email options | Cloud Run IAM via Google tokens, signed URLs for uploads                         | Dedicated intake endpoint with anti-abuse, CAPTCHA, fraud throttling  |
| Analyst               | Review cases, run RAG search, generate reports | Google account in Analyst group, future VPN cert         | Cloud Run IAM + Google Group membership, Terraform-managed bindings              | Analyst-only endpoint behind VPN / BeyondCorp + device posture checks |
| Law Enforcement (LEO) | Search approved cases, download reports        | Provisioned Google account, MFA                          | Google Identity + role claim, signed report URLs                                 | Dedicated LEO portal with read-only scope + case export formats       |
| Automation (jobs)     | Ingest feeds, generate reports, rotate secrets | Service accounts only                                    | Terraform service accounts (`sa-ingest`, `sa-report`, etc.) with least privilege | Same accounts, plus workload-identity federation to CI/CD             |

---

## 3. Service & Endpoint Matrix

| Service                 | Purpose                         | URL (dev)                                          | IAM Owner        | Notes                                                            |
| ----------------------- | ------------------------------- | -------------------------------------------------- | ---------------- | ---------------------------------------------------------------- |
| FastAPI Gateway         | API for intake, review, reports | `https://fastapi-gateway-y5jge5w2cq-uc.a.run.app/` | `sa-app` runtime | Protected by Identity-Aware Proxy (IAP). 404 at `/` is expected. |
| Next.js Analyst Console | Analyst portal                  | `https://i4g-console-y5jge5w2cq-uc.a.run.app/`     | `sa-app` runtime | Protected by IAP; uses FastAPI APIs under the hood.              |

All application services currently reuse the shared runtime service account (`sa-app`). Terraform now owns both the Cloud Run `roles/run.invoker` binding (runtime + IAP service agent) and the IAP `roles/iap.httpsResourceAccessor` policy via the `i4g_analyst_members` input, which now points at the Workspace group `group:gcp-i4g-analyst@intelligenceforgood.org`. Project-level `roles/owner` grants flow through the sister variable `i4g_admin_members`, mapped to `group:gcp-i4g-admin@intelligenceforgood.org`.

---

## 4. Authentication Strategy

### 4.1 Current State — Three-Layer Authentication

Authentication operates at three complementary layers:

**Layer 1 — IAP via Global Load Balancer (infrastructure)**

- A Global External Application Load Balancer is the single ingress point for `app.intelligenceforgood.org` (console) and `api.intelligenceforgood.org` (FastAPI).
- Identity-Aware Proxy (IAP) is enabled on both backend services and enforces Google Sign-In _before_ traffic reaches Cloud Run.
- Cloud Run services use `ingress: internal-and-cloud-load-balancing` so direct access bypassing the LB is blocked.
- Terraform manages `roles/iap.httpsResourceAccessor` bindings via Google Groups (`gcp-i4g-analyst@intelligenceforgood.org`).

**Layer 2 — IAP JWT / Bearer token verification (application)**

The FastAPI `require_token()` dependency in `src/i4g/api/auth.py` validates credentials in priority order:

| Priority | Method        | Header                          | Behaviour                                                                                                                                                                                   |
| -------- | ------------- | ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1        | Auth disabled | —                               | `settings.identity.disable_auth` → returns mock `local-dev` admin. Used for local development only.                                                                                         |
| 2        | IAP JWT       | `X-Goog-IAP-JWT-Assertion`      | Verified using Google's IAP-specific signing keys (`/iap/verify/public_key-jwk`). Audience matched against `I4G_IDENTITY__AUDIENCE`. Email extracted → role resolved from `accounts` table. |
| 3        | Bearer token  | `Authorization: Bearer <token>` | Verified as a standard Google ID token (OIDC certs). Used for service-to-service calls (e.g., Cloud Run → Cloud Run).                                                                       |
| 4        | API key       | `X-API-KEY`                     | Compared against `settings.api.key` (`I4G_API__KEY` env var). Falls back to `username: "service"` if no forwarded user.                                                                     |

**Layer 3 — Forwarded user identity (SSR bridge)**

The Next.js console runs as a Cloud Run service and makes SSR (server-side) API calls on behalf of the browser user. Because the API sits behind its own IAP backend, the console cannot forward the raw `X-Goog-IAP-JWT-Assertion` (IAP strips/replaces it on the second hop). Instead:

1. The console's `getIapHeaders()` decodes the incoming IAP assertion from the browser request and extracts the user's email.
2. It sends the email as `X-I4G-Forwarded-User` alongside a service-to-service Bearer token or API key.
3. The API's `_maybe_resolve_forwarded_user()` trusts this header when the authenticated identity is a service account (`*.iam.gserviceaccount.com`), and resolves the forwarded email's role from the `accounts` table.
4. Direct end-user hits (non-SA identity) are never overridden.

This ensures the API always knows the real browser user's identity, even through the double-IAP hop.

### 4.2 Local Development

When `I4G_ENV=local` or `settings.identity.disable_auth=true`, authentication is bypassed entirely. The API returns a mock admin user (`local-dev`). The UI's `getIapHeaders()` skips IAP token generation for localhost targets.

### 4.3 Future Enhancements

- **Device-based checks:** Pair IAP with BeyondCorp Enterprise or Context-Aware Access policies to enforce device posture.
- **Non-Google identity options:** Evaluate passkeys or external IdPs (Auth0 for Nonprofits, Okta) to accommodate victims without Google accounts.
- **Per-persona endpoints:** Separate Cloud Run services for victim intake, analyst tools, and LEO portal with distinct IAP policies and rate limits.

---

## 5. Authorization

### 5.1 Application-Level RBAC (WS-5)

The platform enforces role-based access control at the application layer via the `accounts` table and FastAPI dependencies.

**Role hierarchy** (defined in `src/i4g/api/roles.py`):

```
user  <  analyst  <  leo  ≤  admin
```

| Role      | Capabilities                                               | Default for                         |
| --------- | ---------------------------------------------------------- | ----------------------------------- |
| `user`    | Read-only access to public case summaries                  | First-time login (auto-provisioned) |
| `analyst` | Full case review, annotation, search, report generation    | Promoted by admin                   |
| `leo`     | All analyst capabilities plus LEO-specific reports         | Promoted by admin                   |
| `admin`   | All capabilities plus user management, campaigns, bulk ops | Manually assigned                   |

**`require_role()` dependency:** FastAPI routes declare a minimum role. The `has_role()` function checks whether the user's role satisfies the requirement via the hierarchy (e.g., `admin` satisfies any role check). Invalid role strings are rejected.

**Accounts table** (`email` PK, `role`, `display_name`, `is_active`, `created_at`, `updated_at`):

- Auto-provisioned on first authenticated request via `AccountStore.get_or_create_account()` with `DEFAULT_ROLE = user`.
- Deactivated accounts receive HTTP 403 at the auth layer.
- All role changes and deactivations are audited to the `review_actions` table with actor attribution.

**Accounts management API** (`/accounts` router, admin-only except `/me`):

| Endpoint                           | Auth              | Purpose                                           |
| ---------------------------------- | ----------------- | ------------------------------------------------- |
| `GET /accounts/me`                 | Any authenticated | Returns current user identity + effective role    |
| `GET /accounts`                    | `admin`           | Lists all accounts (optional `?active_only=true`) |
| `PUT /accounts/{email}/role`       | `admin`           | Change role (self-demotion blocked)               |
| `PUT /accounts/{email}/deactivate` | `admin`           | Soft-disable (self-deactivation blocked)          |
| `PUT /accounts/{email}/reactivate` | `admin`           | Re-enable a deactivated account                   |

**UI enforcement:** The analyst console mirrors the role hierarchy client-side via `AuthProvider` / `useAuth()`. Navigation items are filtered by `minRole` (e.g., User Management and Campaigns require `admin`). The admin accounts table prevents self-demotion and self-deactivation in the UI as well.

**Route-level auth coverage:**

| Route group                    | Auth requirement                                     |
| ------------------------------ | ---------------------------------------------------- |
| `/accounts/*`                  | `require_token` (me), `require_role("admin")` (CRUD) |
| `/campaigns/*` (create/update) | `require_role("admin")`                              |
| `/tasks/*` (update)            | `require_role("admin")`                              |
| `/tokenization/detokenize`     | `require_role("analyst")`                            |
| `/reviews/*`, `/intakes/*`     | `require_token`                                      |
| Other read endpoints           | `require_token`                                      |

### 5.2 Infrastructure-Level Authorization

1. **Runtime Service Accounts**
   - `sa-app`: shared by FastAPI and the Next.js console. Roles: `roles/storage.objectViewer`, `roles/secretmanager.secretAccessor`, `roles/run.invoker` (self), `roles/logging.logWriter`, `roles/cloudsql.client`, plus Discovery search role.
   - `sa-ingest`, `sa-report`, `sa-vault`, `sa-infra`: per-job least-privilege grants (see Terraform modules).

2. **Workspace Groups & Human Roles**
   - `gcp-i4g-admin@intelligenceforgood.org` — break-glass administrator group. Terraform grants `roles/owner` on each project.
   - `gcp-i4g-analyst@intelligenceforgood.org` — analyst cohort. Terraform feeds this group into Cloud Run invoker and IAP accessor policies so onboarding requires only Google Workspace membership changes.
   - Law-enforcement and partner groups will be created before shipping those personas.

3. **Cloud Run + IAP Policy Management**
   - Terraform manages both the Cloud Run `roles/run.invoker` binding and the IAP `roles/iap.httpsResourceAccessor` policy, both derived from `i4g_analyst_members`. Avoid manual IAM edits so Terraform remains authoritative.

4. **Data Plane Permissions**
   - Cloud SQL: analysts read only assigned cases; PII vault locked to backend service account.
   - Cloud Storage: uniform bucket-level access; signed URLs for user downloads/uploads.
   - Vertex AI Search: custom roles bound to runtime SAs.
   - Secret Manager: versioned secrets per service account; rotate quarterly.

5. **Audit & Monitoring**
   - Application-level audit: role changes, account deactivation, and review actions written to `review_actions` table with actor + timestamp.
   - Cloud Audit Logs retained ≥400 days.
   - Daily Terraform drift check (planned).
   - Streaming alerts for IAM policy changes and authentication failures (planned).

---

## 6. Identity-Aware Proxy (IAP) Configuration

IAP is now the ingress layer for every Cloud Run HTTPS endpoint. The helper SPA has been removed; instead, analysts hit the standard Cloud Run URLs and IAP gates access.

### 6.1 Terraform-managed configuration

- `infra/modules/iap/project` wires project-level access defaults (allowed domains, HTTP OPTIONS). When `iap_manage_brand=true` (only possible if the project belongs to an organization), it will also create/manage the brand; otherwise it simply reuses the manually created brand name.
- `infra/modules/iap/cloud_run_service` always manages the `roles/iap.httpsResourceAccessor` bindings derived from `i4g_analyst_members`. When `iap_manage_clients=true`, it additionally creates per-service OAuth clients and Secret Manager entries; for standalone projects we leave this disabled and rely on Google’s default IAP client.
- Every environment now requires the following tfvars before planning:
  - `iap_support_email` — verified Workspace/Gmail address (only used when managing the brand but kept for parity).
  - `iap_application_title` _(optional)_ — consent screen title.
  - `iap_manage_brand`, `iap_existing_brand_name`, `iap_manage_clients` _(optional)_ — feature toggles described above.
  - `iap_secret_replication_locations` _(optional)_ — list of regions for the stored secrets (defaults to the Cloud Run region).
- Terraform automatically grants Cloud Run `roles/run.invoker` to the shared runtime service account plus the IAP service agent so the proxy can reach the backend. Only service-to-service callers should be added via the legacy `*_invoker_members` variables.
- Outputs (`terraform output iap`) expose the brand name plus optional OAuth client metadata (null until `iap_manage_clients=true`).
- Drift management: rerun `terraform plan -var-file=terraform.tfvars` whenever group membership changes to confirm the policy is still aligned; record ad-hoc manual bindings in `planning/change_log.md`.

### 6.2 Manual overrides / break-glass

Terraform is the source of truth, but if we need an emergency change before a plan/apply cycle finishes, use the stock `gcloud` commands:

1. **Enable IAP for a service** (only if Terraform hasn’t already done so):
   ```bash
   gcloud iap web enable \
      --resource-type=run \
      --service=i4g-console \
      --project=i4g-dev \
      --region=us-central1
   ```
2. **Grant access to a group or user** (remember to capture the change in `planning/change_log.md` and back-port to Terraform tfvars):
   ```bash
   gcloud iap web add-iam-policy-binding \
      --resource-type=run \
      --service=i4g-console \
      --project=i4g-dev \
      --region=us-central1 \
      --member=group:gcp-i4g-analyst@intelligenceforgood.org \
      --role=roles/iap.httpsResourceAccessor
   ```
3. **Repeat for FastAPI** as needed; Terraform will reconcile the bindings on the next apply.

### 6.3 Consuming identity inside the app

- **IAP JWT verification (implemented):** The FastAPI `require_token()` dependency verifies `X-Goog-IAP-JWT-Assertion` using Google's IAP-specific signing keys and the configured audience (`I4G_IDENTITY__AUDIENCE`). The authenticated email is mapped to an application role via the `accounts` table.
- **Forwarded user identity (implemented):** When the Next.js SSR layer calls the API, it forwards the browser user's email via `X-I4G-Forwarded-User`. The API trusts this header only when the authenticated caller is a service account. See §4.1 for the full flow.
- **CLI access:** Scripts call Cloud Run directly with `gcloud auth print-identity-token --audiences=<IAP_CLIENT_ID>` as long as the caller account is part of the IAP policy.

---

## 7. IAM Roadmap

| Phase       | Status                 | Deliverables                                                                                                                                                                                                                                                                                                                                                                                          |
| ----------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Phase 0** | ✅ Complete (Dec 2025) | IAM strategy published, Quick Auth helper removed, every Cloud Run service gated behind Terraform-managed IAP.                                                                                                                                                                                                                                                                                        |
| **Phase 1** | ✅ Complete (Feb 2026) | IAP JWT verification in FastAPI (`_verify_iap_jwt` with IAP certs). Forwarded-user identity bridge (`X-I4G-Forwarded-User`). DB-backed RBAC with `accounts` table, 4-role hierarchy (`user < analyst < leo ≤ admin`), `require_role()` dependency. Admin UI for user/role management (`/admin/users`). Audit logging for role changes and deactivation. Role-aware navigation in the analyst console. |
| **Phase 2** | Planned (Q2 2026)      | Introduce role-specific endpoints or Cloud Run services (victim intake, LEO portal). Add device-posture checks via BeyondCorp / Context-Aware Access. Expand audit trail to cover case-level access.                                                                                                                                                                                                  |
| **Phase 3** | Planned (Q3 2026)      | Evaluate non-Google identity options (passkeys, Auth0 for Nonprofits). Automate IAM drift detection. Implement signed report attestations for legal workflows.                                                                                                                                                                                                                                        |

Open questions:

1. Which VPN / ZTNA solution best balances cost and volunteer usability?
2. How do we onboard law-enforcement partners who cannot use Google accounts?
3. What compliance requirements (CJIS, HIPAA, etc.) apply, and how do they influence log retention and MFA policies?

---

## 8. Operational Runbook Highlights

- **Group Management:** Manage `gcp-i4g-analyst@intelligenceforgood.org`, `gcp-i4g-admin@intelligenceforgood.org`, and the upcoming persona-specific lists manually until we automate via Workspace Admin APIs. Document membership changes in `planning/change_log.md`.
- **Terraform Inputs:** `i4g_analyst_members` is pinned to `group:gcp-i4g-analyst@intelligenceforgood.org` and `i4g_admin_members` to `group:gcp-i4g-admin@intelligenceforgood.org`. Keep dev/prod tfvars in sync and update Workspace groups rather than editing tfvars when onboarding.
- **Incident Response:** On suspected credential leak, (1) remove the user from the Google Group, (2) rotate secrets via Secret Manager, (3) re-run Terraform to enforce IAM bindings, (4) rotate the IAP OAuth client secret (new Secret Manager version) if needed.
- **Logging & Metrics:** Track `403` responses from Cloud Run; correlate with IAP audit logs to detect auth friction or brute-force attempts.

---

## 9. References

- [design/architecture.md](architecture.md) — system overview (defers IAM details to this document).
- `planning/future_architecture.md` — long-term blueprint; IAM sections summarized here.
- `docs/book/api/authentication.md` — API-focused auth guide for developers.
- `docs/book/security/access-control.md` — end-user guide to requesting access and understanding roles.
- `infra/` Terraform modules (`iam/`, `run/service`, `iap/`, `lb/`) — enforce the described policies.
- `src/i4g/api/auth.py` — authentication middleware implementation.
- `src/i4g/api/roles.py` — role enum, hierarchy, `has_role()` function.
- `src/i4g/api/accounts.py` — accounts management API endpoints.

_End of document._
