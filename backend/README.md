# SmartBite API

Backend разделён на HTTP API, прикладной сценарий и предметные правила. Общий сценарий генерации находится в `app/application/recipes.py`: его можно вызывать из нового адаптера для Telegram или мобильного приложения, не перенося туда правила API.

При заданном `GEMINI_API_KEY` backend по умолчанию вызывает Gemini Developer API через REST. Qwen доступен как дополнительный вариант: для его выбора укажите `SMARTBITE_GENERATOR_ADAPTER=app.qwen_adapter:create_client` и задайте `DASHSCOPE_API_KEY`. По умолчанию используется модель `qwen3.8-flash` и международный endpoint Сингапура; модель и endpoint задаются через `SMARTBITE_QWEN_MODEL` и `SMARTBITE_QWEN_BASE_URL`. Оба адаптера используют стандартную библиотеку Python без отдельного SDK. Без выбранного ключа запуск остаётся в демонстрационном режиме с фиксированными примерами; демо не понимает произвольные пожелания и не является ИИ-генератором. Другой поставщик подключается через `SMARTBITE_GENERATOR_ADAPTER` с фабрикой `package.module:create_client`, возвращающей объект с методом `request_json(system_instruction, input_json)`.

Для включения Gemini скопируйте корневой `.env.example` в `.env`, вставьте ключ из [Google AI Studio](https://aistudio.google.com/apikey), затем запустите Compose. Файл `.env` не добавляйте в репозиторий. Gemini получает список продуктов; пищевые исключения остаются внутри backend и применяются после генерации. Запросы и ответы не записываются в журналы. Перед передачей реальных пользовательских данных проверьте действующие [условия Gemini API](https://ai.google.dev/gemini-api/terms) и [уровни цен и использования данных](https://ai.google.dev/gemini-api/docs/pricing): бесплатный уровень может использовать запросы для улучшения продуктов Google.

Проверка ингредиентов использует небольшой словарь: она не является медицинским справочником и не гарантирует отсутствие скрытых компонентов или следов перекрёстного загрязнения.

## Локальный запуск

Из каталога `backend`:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

По умолчанию используется SQLite-файл `smartbite.db`. Для PostgreSQL задайте переменную `DATABASE_URL`; пример настройки находится в корневом `.env.example`. Проверка API доступна по `GET /api/health`, описание маршрутов — по адресу `http://localhost:8000/docs`.

Данные профиля и состав рецептов хранятся в отдельных связанных таблицах в 3НФ. Миграции переносят сохранённые списки в эту схему без потери значений и их порядка. ER-схема и описание ключей находятся в `architecture/data-model.md`.

## Проверки

```sh
python -m pytest -q
python -m alembic check
```

Тесты проверяют предметные правила, сценарий генерации, работу учётных записей, миграцию старых данных и интеграцию API с базой данных. Отдельные проверки PostgreSQL запускаются в CI на PostgreSQL 17. Миграции схемы хранятся в `migrations/versions` и применяются через Alembic.
