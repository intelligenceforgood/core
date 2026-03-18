# Setting Up GitHub Actions CI/CD with Workload Identity Federation

**Estimated time:** 45–60 minutes
**Prerequisites:** Terraform access to dev and prod projects, GitHub admin access to `intelligenceforgood` org repos
**Scope:** Configure GitHub Actions workflows for automated testing, Docker builds, and Terraform deployments

---

## Overview

This guide configures CI/CD for three repos (`core`, `ui`, `infra`) using Workload Identity Federation (WIF) for keyless authentication to Google Cloud. It covers:

1. Workload Identity Federation pool/provider configuration
2. GitHub repository variables setup
3. Environment protection rules
4. Testing each workflow

---

## 1. Prerequisites Check

Before starting, verify:

```bash
# Authenticated as sa-infra impersonation
gcloud config list

# Terraform state access
cd /path/to/i4g/infra/environments/app/dev
terraform init

# GitHub CLI authenticated
gh auth status
```

---

## 2. Update Workload Identity Federation to Trust All Repos

Currently, the WIF attribute condition only trusts `intelligenceforgood/core`. Update it to trust all three repos (or the entire org).

### Option A: Trust specific repos (more secure)

Edit [infra/stacks/app/main.tf](../../infra/stacks/app/main.tf) (the unified stack — applies to both dev and prod):

> **Note (post-DRY refactor):** `environments/app/{dev,prod}/main.tf` are now thin wrappers that
> call `module "app" { source = "../../../stacks/app" … }`. All resource logic, including the
> WIF module, lives in `stacks/app/`. Edit the stack directly; the environment wrapper passes
> values through `terraform.tfvars`.

```terraform
module "github_wif" {
  source              = "../../modules/iam/workload_identity_github"
  project_id          = var.project_id
  pool_id             = local.github_wif.pool_id
  provider_id         = local.github_wif.provider_id
  github_repository   = var.github_repository
  # Change this line:
  attribute_condition = "attribute.repository in ['intelligenceforgood/core', 'intelligenceforgood/ui', 'intelligenceforgood/infra']"
}
```

### Option B: Trust entire org (simpler, slightly less restrictive)

```terraform
attribute_condition = "assertion.repository_owner == 'intelligenceforgood'"
```

Apply changes:

```bash
cd infra/environments/app/dev
terraform plan -var "project_id=i4g-dev" -var "github_repository=intelligenceforgood/core"
terraform apply -var "project_id=i4g-dev" -var "github_repository=intelligenceforgood/core"

cd ../prod
terraform plan -var "project_id=i4g-prod" -var "github_repository=intelligenceforgood/core"
# Review carefully before applying to prod
terraform apply -var "project_id=i4g-prod" -var "github_repository=intelligenceforgood/core"
```

---

## 3. Configure GitHub Repository Variables

Set variables for each repo in **Settings → Secrets and variables → Actions → Variables**.

### `intelligenceforgood/core` repo

| Variable                            | Value                                                                                                | Notes                                                                                  |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `TF_GCP_WORKLOAD_IDENTITY_PROVIDER` | `projects/<DEV_PROJECT_NUMBER>/locations/global/workloadIdentityPools/github-actions/providers/core` | Get project number: `gcloud projects describe i4g-dev --format='value(projectNumber)'` |
| `TF_GCP_SERVICE_ACCOUNT`            | `sa-infra@i4g-dev.iam.gserviceaccount.com`                                                           | Must have `artifactregistry.writer` on dev + prod                                      |
| `GCP_DEV_PROJECT_ID`                | `i4g-dev`                                                                                            |                                                                                        |
| `GCP_PROD_PROJECT_ID`               | `i4g-prod`                                                                                           |                                                                                        |

Set via CLI (faster than clicking):

```bash
gh variable set TF_GCP_WORKLOAD_IDENTITY_PROVIDER \
  --body "projects/$(gcloud projects describe i4g-dev --format='value(projectNumber)')/locations/global/workloadIdentityPools/github-actions/providers/core" \
  --repo intelligenceforgood/core

gh variable set TF_GCP_SERVICE_ACCOUNT \
  --body "sa-infra@i4g-dev.iam.gserviceaccount.com" \
  --repo intelligenceforgood/core

gh variable set GCP_DEV_PROJECT_ID --body "i4g-dev" --repo intelligenceforgood/core
gh variable set GCP_PROD_PROJECT_ID --body "i4g-prod" --repo intelligenceforgood/core
```

### `intelligenceforgood/ui` repo

Same 4 variables as `core`:

```bash
gh variable set TF_GCP_WORKLOAD_IDENTITY_PROVIDER \
  --body "projects/$(gcloud projects describe i4g-dev --format='value(projectNumber)')/locations/global/workloadIdentityPools/github-actions/providers/core" \
  --repo intelligenceforgood/ui

gh variable set TF_GCP_SERVICE_ACCOUNT \
  --body "sa-infra@i4g-dev.iam.gserviceaccount.com" \
  --repo intelligenceforgood/ui

gh variable set GCP_DEV_PROJECT_ID --body "i4g-dev" --repo intelligenceforgood/ui
gh variable set GCP_PROD_PROJECT_ID --body "i4g-prod" --repo intelligenceforgood/ui
```

### `intelligenceforgood/infra` repo

Dev variables should already exist. Add prod:

```bash
gh variable set TF_GCP_PROD_PROJECT_ID --body "i4g-prod" --repo intelligenceforgood/infra

gh variable set TF_GCP_PROD_WORKLOAD_IDENTITY_PROVIDER \
  --body "projects/$(gcloud projects describe i4g-prod --format='value(projectNumber)')/locations/global/workloadIdentityPools/github-actions/providers/core" \
  --repo intelligenceforgood/infra

gh variable set TF_GCP_PROD_SERVICE_ACCOUNT \
  --body "sa-infra@i4g-prod.iam.gserviceaccount.com" \
  --repo intelligenceforgood/infra
```

---

## 4. Configure GitHub Environments (infra repo only)

The prod Terraform workflow requires manual approval before applying. Create a `production` environment with required reviewers:

1. Go to [intelligenceforgood/infra Settings → Environments](https://github.com/intelligenceforgood/infra/settings/environments)
2. Click **New environment**
3. Name: `production`
4. Check **Required reviewers** → add yourself (or your team)
5. Save

Now, any push to `main` that triggers `terraform-prod.yml` will block at the apply step until you approve it in the GitHub Actions UI.

---

## 5. Verify IAM Bindings

The `sa-infra` service account needs the following roles:

### In `i4g-dev` and `i4g-prod`:

```bash
# Check Artifact Registry access
gcloud projects get-iam-policy i4g-dev --flatten="bindings[].members" \
  --filter="bindings.members:sa-infra@i4g-dev.iam.gserviceaccount.com AND bindings.role:roles/artifactregistry.writer"

# Should return the binding; if empty, add it:
gcloud projects add-iam-policy-binding i4g-dev \
  --member="serviceAccount:sa-infra@i4g-dev.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"

# Repeat for prod
gcloud projects add-iam-policy-binding i4g-prod \
  --member="serviceAccount:sa-infra@i4g-prod.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"
```

### Workload Identity User binding:

Verify the SA can be impersonated by the WIF principal:

```bash
gcloud iam service-accounts get-iam-policy sa-infra@i4g-dev.iam.gserviceaccount.com
```

Should include a `roles/iam.workloadIdentityUser` binding with member:

```
principalSet://iam.googleapis.com/projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github-actions/attribute.repository/intelligenceforgood/core
```

(Or similar for all three repos if using Option A above, or the org-wide pattern if Option B.)

If missing, Terraform should have created it via `google_service_account_iam_binding.infra_wif`. Re-apply the Terraform module if needed.

---

## 6. Test Each Workflow

### Test D71: UI CI workflow

**PR test (lint + type-check + test):**

```bash
cd /path/to/i4g/ui
git checkout -b test-ui-ci
echo "# Test PR" >> README.md
git add README.md
git commit -m "test: trigger UI CI"
git push origin test-ui-ci
gh pr create --title "Test UI CI" --body "Testing lint-test job"
```

Check [Actions tab](https://github.com/intelligenceforgood/ui/actions) for the `UI CI` workflow. The `lint-test` job should run.

**Docker build test:**

After merging the PR above:

```bash
cd /path/to/i4g/ui
git checkout main
git pull
echo "0.1.1" > VERSION.txt
git add VERSION.txt
git commit -m "chore: bump version to test Docker build"
git push origin main
```

Watch the Actions tab. The `build-push` job should:

1. Authenticate via WIF
2. Build `i4g-console` image
3. Push to both dev and prod registries

Verify:

```bash
gcloud artifacts docker images list us-central1-docker.pkg.dev/i4g-dev/applications/i4g-console
gcloud artifacts docker images list us-central1-docker.pkg.dev/i4g-prod/applications/i4g-console
```

### Test D72: Prod Terraform workflow

```bash
cd /path/to/i4g/infra
git checkout -b test-terraform-prod
# Make a safe no-op change
echo "# Test change $(date)" >> environments/app/prod/README.md
git add environments/app/prod/README.md
git commit -m "test: trigger prod Terraform plan"
git push origin test-terraform-prod
gh pr create --title "Test Terraform Prod" --body "Testing plan-only job"
```

Check Actions tab. The `plan` job should run and show the Terraform plan output.

Merge the PR:

```bash
gh pr merge --squash
```

The `apply` job should start but **pause** waiting for approval. Go to the Actions tab, find the run, and click **Review deployments → Approve**. The apply will proceed.

### Test D73: Core Docker build workflow

```bash
cd /path/to/i4g/core
git checkout -b test-docker-build
# Bump version
echo "0.1.1" > VERSION.txt
git add VERSION.txt
git commit -m "chore: bump version to test Docker builds"
git push origin test-docker-build
gh pr create --title "Bump version" --body "Testing Docker build matrix"
# Merge immediately (no PR checks for VERSION.txt-only changes)
gh pr merge --squash --admin
```

Watch Actions. The matrix build should fire, building all 5 images in parallel. Total time: ~10–15 minutes.

Verify all images:

```bash
for img in core-svc dossier-job ingest-job intake-job report-job; do
  echo "=== $img ==="
  gcloud artifacts docker images list us-central1-docker.pkg.dev/i4g-dev/applications/$img --limit 1
done
```

---

## 7. Ongoing Usage

### Triggering builds

- **UI**: Bump `ui/VERSION.txt`, merge to main → Docker image published
- **Core**: Bump `core/VERSION.txt`, merge to main → All 6 images published
- **Infra (prod)**: Change Terraform in `environments/app/prod/` or `modules/`, merge to main → Plan + manual approval → Apply

### Troubleshooting

**"Failed to get ID token: Federated token exchange request failed"**

- Check WIF provider `attribute_condition` matches the repo
- Verify `TF_GCP_WORKLOAD_IDENTITY_PROVIDER` variable is correct
- Confirm SA has `roles/iam.workloadIdentityUser` for the WIF principal

**"Permission denied: artifacts.dockerimages.create"**

- Add `roles/artifactregistry.writer` to `sa-infra` in the target project

**Prod apply never starts**

- Check that the `production` environment exists and has required reviewers
- Confirm your GitHub user is a collaborator on the repo

---

## 8. Security Notes

- WIF tokens are scoped to the workflow run and expire after 10 minutes
- No long-lived service account keys are stored in GitHub secrets
- All secrets are managed via Google Secret Manager; GitHub only has WIF config
- Limit WIF trust to specific repos (`attribute_condition`) when possible
- Use GitHub environment protection for prod applies (already done for Terraform)

---

## Related Docs

- [Workload Identity Federation module](../../infra/modules/iam/workload_identity_github/README.md)
- [Settings environment variables](../config/README.md#environment-variables)
- [Docker build script](../../scripts/build_image.sh) (manual alternative)
- [Terraform deployment checklist](../runbooks/hybrid_search_deployment_checklist.md)
