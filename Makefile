.PHONY: test up down worker pool deploy logs

test:
	python -m pytest -q
up:
	docker compose up -d --build n8n gateway
worker:
	docker compose --profile worker up -d --build worker
pool:
	docker compose --profile worker run --rm worker prefect work-pool create nas-local --type process
deploy:
	docker compose --profile worker run --rm worker prefect deploy --all
logs:
	docker compose logs -f n8n gateway
down:
	docker compose --profile worker down
