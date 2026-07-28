.DEFAULT_GOAL := help
.PHONY: help setup fmt lint types test cov accept check integration clean yt

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "};{printf "\033[36m%-13s\033[0m %s\n",$$1,$$2}'

setup:  ## Instala deps e hooks
	uv sync --all-extras
	uv run pre-commit install --install-hooks

fmt:  ## Formata e corrige o que dá
	uv run ruff format .
	uv run ruff check --fix .

lint:  ## Lint sem corrigir
	uv run ruff check .
	uv run ruff format --check .

types:  ## Type check estrito
	uv run mypy --strict src

test:  ## Testes rápidos (sem rede, sem aceite)
	uv run pytest -q -m "not integration and not acceptance"

cov:  ## Testes com cobertura e limiares
	uv run pytest -m "not integration" \
		--cov=src/vascobot --cov-report=term-missing --cov-fail-under=85
	@# Strict 100% só nos módulos de lógica pura, quando existirem
	@if ls src/vascobot/pipeline/rules.py src/vascobot/pipeline/priority.py \
	      src/vascobot/pipeline/compose.py src/vascobot/publishers/cost.py \
	      2>/dev/null | grep -q .; then \
	  uv run coverage report --include="*/rules.py,*/priority.py,*/compose.py,*/cost.py" \
	    --fail-under=100; \
	else \
	  echo "⏭  strict-100 skip: módulos ainda não existem (Fase 2/3)"; \
	fi

accept:  ## Só os critérios de aceite (CA-xx)
	uv run pytest -q -m acceptance

check: lint types cov accept  ## ⬅️ Portão completo. Verde = pronto.
	@echo "✅ todos os portões passaram"

integration:  ## Testes com rede real — manual, nunca no CI
	uv run pytest -q -m integration

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov

yt:
	@osascript -e 'tell application "Brave Browser"' \
		-e 'repeat with w in windows' \
		-e 'repeat with t in tabs of w' \
		-e 'if URL of t contains "youtube.com" then' \
		-e 'execute t javascript "var v = document.getElementsByTagName(\"video\")[0]; v.paused ? v.play() : v.pause();"' \
		-e 'end if' \
		-e 'end repeat' \
		-e 'end repeat' \
		-e 'end tell'
