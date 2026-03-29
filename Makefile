.PHONY: setup install install-dev test test-all lint format clean serve \
        build-dev deploy-dev build-prod deploy-prod \
        build-ingest-dev deploy-ingest-dev build-ingest-prod deploy-ingest-prod \
        build-intake-dev deploy-intake-dev build-intake-prod deploy-intake-prod \
        build-report-dev deploy-report-dev build-report-prod deploy-report-prod \
        build-dossier-dev deploy-dossier-dev build-dossier-prod deploy-dossier-prod \
        build-backup-dev deploy-backup-dev build-backup-prod deploy-backup-prod \
        deploy-analytics-dev deploy-analytics-prod \
        deploy-all-jobs-dev deploy-all-jobs-prod rehydrate

# ---------- Setup ----------
# Full first-time setup: install Python deps in editable mode.
# Prerequisites: conda env i4g already activated.
setup: install-dev
	@echo "✅ Setup complete. Run 'i4g --version' to verify."

install:
	pip install -e .

install-dev:
	pip install -e ".[dev,test]"
	pre-commit install

# ---------- Quality ----------
test:
	pytest tests/unit -v

test-all:
	pytest -v

lint:
	ruff check src/ tests/
	mypy src/i4g/

format:
	black src/ tests/
	isort src/ tests/

# ---------- Run ----------
serve:
	uvicorn i4g.api.app:app --reload

# ---------- Docker / Deploy ----------
build-dev:
	scripts/build_image.sh core-svc dev

deploy-dev: build-dev
	gcloud run deploy core-svc \
		--image us-central1-docker.pkg.dev/i4g-dev/applications/core-svc:dev \
		--region us-central1 \
		--project i4g-dev

build-prod:
	scripts/build_image.sh core-svc prod \
		--registry us-central1-docker.pkg.dev/i4g-prod/applications

deploy-prod: build-prod
	gcloud run deploy core-svc \
		--image us-central1-docker.pkg.dev/i4g-prod/applications/core-svc:prod \
		--region us-central1 \
		--project i4g-prod

# ---------- Jobs (Dev) ----------
build-ingest-dev:
	scripts/build_image.sh ingest-job dev

deploy-ingest-dev: build-ingest-dev
	gcloud run jobs deploy ingest-bootstrap \
		--image us-central1-docker.pkg.dev/i4g-dev/applications/ingest-job:dev \
		--region us-central1 \
		--project i4g-dev

build-intake-dev:
	scripts/build_image.sh intake-job dev

deploy-intake-dev: build-intake-dev
	gcloud run jobs deploy process-intakes \
		--image us-central1-docker.pkg.dev/i4g-dev/applications/intake-job:dev \
		--region us-central1 \
		--project i4g-dev

build-report-dev:
	scripts/build_image.sh report-job dev

deploy-report-dev: build-report-dev
	gcloud run jobs deploy generate-reports \
		--image us-central1-docker.pkg.dev/i4g-dev/applications/report-job:dev \
		--region us-central1 \
		--project i4g-dev

build-dossier-dev:
	scripts/build_image.sh dossier-job dev

deploy-dossier-dev: build-dossier-dev
	gcloud run jobs deploy dossier-queue \
		--image us-central1-docker.pkg.dev/i4g-dev/applications/dossier-job:dev \
		--region us-central1 \
		--project i4g-dev

build-backup-dev:
	scripts/build_image.sh backup-job dev

deploy-backup-dev: build-backup-dev
	gcloud run jobs deploy backup-db \
		--image us-central1-docker.pkg.dev/i4g-dev/applications/backup-job:dev \
		--region us-central1 \
		--project i4g-dev

# analytics-refresh reuses the ingest-job image (no separate build target).
deploy-analytics-dev:
	gcloud run jobs deploy analytics-refresh \
		--image us-central1-docker.pkg.dev/i4g-dev/applications/ingest-job:dev \
		--region us-central1 \
		--project i4g-dev

deploy-all-jobs-dev: deploy-ingest-dev deploy-intake-dev deploy-report-dev deploy-dossier-dev deploy-backup-dev deploy-analytics-dev
	@echo "✅ All dev jobs deployed."

# ---------- Jobs (Prod) ----------
build-ingest-prod:
	scripts/build_image.sh ingest-job prod \
		--registry us-central1-docker.pkg.dev/i4g-prod/applications

deploy-ingest-prod: build-ingest-prod
	gcloud run jobs deploy ingest-bootstrap \
		--image us-central1-docker.pkg.dev/i4g-prod/applications/ingest-job:prod \
		--region us-central1 \
		--project i4g-prod

build-intake-prod:
	scripts/build_image.sh intake-job prod \
		--registry us-central1-docker.pkg.dev/i4g-prod/applications

deploy-intake-prod: build-intake-prod
	gcloud run jobs deploy process-intakes \
		--image us-central1-docker.pkg.dev/i4g-prod/applications/intake-job:prod \
		--region us-central1 \
		--project i4g-prod

build-report-prod:
	scripts/build_image.sh report-job prod \
		--registry us-central1-docker.pkg.dev/i4g-prod/applications

deploy-report-prod: build-report-prod
	gcloud run jobs deploy generate-reports \
		--image us-central1-docker.pkg.dev/i4g-prod/applications/report-job:prod \
		--region us-central1 \
		--project i4g-prod

build-dossier-prod:
	scripts/build_image.sh dossier-job prod \
		--registry us-central1-docker.pkg.dev/i4g-prod/applications

deploy-dossier-prod: build-dossier-prod
	gcloud run jobs deploy dossier-queue \
		--image us-central1-docker.pkg.dev/i4g-prod/applications/dossier-job:prod \
		--region us-central1 \
		--project i4g-prod

build-backup-prod:
	scripts/build_image.sh backup-job prod \
		--registry us-central1-docker.pkg.dev/i4g-prod/applications

deploy-backup-prod: build-backup-prod
	gcloud run jobs deploy backup-db \
		--image us-central1-docker.pkg.dev/i4g-prod/applications/backup-job:prod \
		--region us-central1 \
		--project i4g-prod

# analytics-refresh reuses the ingest-job image (no separate build target).
deploy-analytics-prod:
	gcloud run jobs deploy analytics-refresh \
		--image us-central1-docker.pkg.dev/i4g-prod/applications/ingest-job:prod \
		--region us-central1 \
		--project i4g-prod

deploy-all-jobs-prod: deploy-ingest-prod deploy-intake-prod deploy-report-prod deploy-dossier-prod deploy-backup-prod deploy-analytics-prod
	@echo "✅ All prod jobs deployed."

# ---------- Clean ----------
clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .mypy_cache htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# ---------- Rehydrate (Copilot session bootstrap) ----------
rehydrate:
	@echo "--- Core Rehydrate ---"
	git status -sb
	@echo "--- Recent changes ---"
	git log --oneline -5 2>/dev/null || true
