.PHONY: setup install install-dev test test-all lint format clean serve \
        build-dev deploy-dev build-prod deploy-prod rehydrate

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
