.PHONY: up down logs seed shell backup restore test admin

up:            ## Поднять всё: база, приложение, планировщик, HTTPS
	docker compose up -d --build

down:          ## Остановить
	docker compose down

logs:          ## Смотреть логи приложения
	docker compose logs -f web worker

seed:          ## Наполнить демо-данными (стирает текущие!)
	docker compose exec web flask seed --reset

admin:         ## Завести администратора: make admin NAME="Иван Иванов"
	docker compose exec web flask create-member "$(NAME)" --admin

shell:         ## Консоль внутри контейнера приложения
	docker compose exec web bash

backup:        ## Бэкап базы в ./backups
	./scripts/backup.sh

restore:       ## Восстановить: make restore FILE=backups/chitkod-….sql.gz
	./scripts/restore.sh "$(FILE)"

test:          ## Прогнать тесты локально (нужен venv с requirements-dev.txt)
	python -m pytest -q
