.PHONY: up down seed benchmark ablation test lint

up:
	docker compose up --build -d

down:
	docker compose down

seed:
	docker compose exec api python scripts/seed.py --count 50000 --replace

benchmark:
	docker compose exec api python scripts/benchmark.py --repetitions 5

ablation:
	docker compose exec api python scripts/ablation.py --repetitions 5

test:
	pytest -q

lint:
	ruff check .
