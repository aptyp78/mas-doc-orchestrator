.PHONY: help install test lint run clean

help:
	@echo "MAS Doc Orchestrator"
	@echo ""
	@echo "  make install    — установка зависимостей"
	@echo "  make test       — запуск тестов"
	@echo "  make lint       — ruff check + mypy"
	@echo "  make run DOC=<путь>  — прогон оркестратора"
	@echo "  make normalize DOC=<путь> — нормализация"
	@echo "  make clean      — очистка output/"

install:
	pip3 install --break-system-packages -e ".[dev]"

test:
	python3 -m pytest tests/ -v

lint:
	ruff check src/ tests/
	mypy src/ --ignore-missing-imports

run:
	@test -n "$(DOC)" || (echo "Укажите DOC=<путь к PDF>" && exit 1)
	python3 scripts/run_orchestrator.py "$(DOC)"

normalize:
	@test -n "$(DOC)" || (echo "Укажите DOC=<путь к PDF>" && exit 1)
	python3 scripts/run_normalize.py "$(DOC)"

clean:
	rm -rf output/*