.PHONY: test migrate migrate-check api web up down

test:
	cd backend && python3 -m pytest -q

migrate:
	cd backend && python3 -m alembic upgrade head

migrate-check:
	cd backend && python3 -m alembic check

api:
	cd backend && python3 -m uvicorn app.main:app --reload

web:
	cd frontend && npm run dev

up:
	docker compose up --build

down:
	docker compose down
