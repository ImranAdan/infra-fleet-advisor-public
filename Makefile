.PHONY: setup review test lint typecheck check

FLEET_CHECKOUT ?= ../infra-fleet-public
REVIEW_OUTPUT ?= review-output

setup:
	uv sync --frozen

review:
	uv run --frozen infra-fleet-advisor review \
		--checkout "$(FLEET_CHECKOUT)" \
		--sha "$$(git -c core.fsmonitor=false -C "$(FLEET_CHECKOUT)" rev-parse HEAD)" \
		--policy policy.yaml --intent-dir intent \
		--output-dir "$(REVIEW_OUTPUT)" --synthesizer stub

test:
	uv run --frozen pytest -q

lint:
	uv run --frozen ruff check .
	uv run --frozen ruff format --check .

typecheck:
	uv run --frozen mypy src

check: lint typecheck test
