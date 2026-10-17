# Модель данных SmartBite

Основная БД проекта — PostgreSQL. SQLite используется в быстрых локальных тестах. Структура управляется миграциями Alembic; массивы значений профиля и рецепта хранятся отдельными строками, а не списками внутри JSON-полей.

## Связи сущностей

```mermaid
erDiagram
    USERS ||--|| PROFILES : has
    PROFILES ||--o{ PROFILE_SETTINGS : contains
    USERS ||--o{ LOGIN_SESSIONS : opens
    USERS ||--o{ RECIPES : owns
    RECIPES ||--o{ RECIPE_INPUT_PRODUCTS : starts_with
    RECIPES ||--o{ RECIPE_INGREDIENTS : contains
    RECIPES ||--o{ RECIPE_STEPS : describes
    RECIPES ||--o{ RECIPE_MISSING_PRODUCTS : needs
    USERS ||--o{ RECIPE_RATINGS : leaves
    RECIPES ||--o| RECIPE_RATINGS : receives
    USERS ||--o{ USAGE_EVENTS : generates

    USERS {
        int id PK
        string email UK
        string password_salt
        string password_hash
        datetime created_at
    }
    PROFILES {
        int id PK
        int user_id FK,UK
    }
    PROFILE_SETTINGS {
        int profile_id PK,FK
        string kind PK
        int position PK
        string value
    }
    LOGIN_SESSIONS {
        int id PK
        int user_id FK
        string token_hash UK
        datetime expires_at
        datetime created_at
    }
    RECIPES {
        int id PK
        int user_id FK
        string mode
        bool is_saved
        string description
        string title
        int preparation_time_minutes
        datetime created_at
    }
    RECIPE_INPUT_PRODUCTS {
        int recipe_id PK,FK
        int position PK
        string name
    }
    RECIPE_INGREDIENTS {
        int recipe_id PK,FK
        int position PK
        string name
        string quantity
    }
    RECIPE_STEPS {
        int recipe_id PK,FK
        int position PK
        string instruction
        int duration_minutes
    }
    RECIPE_MISSING_PRODUCTS {
        int recipe_id PK,FK
        int position PK
        string name
    }
    RECIPE_RATINGS {
        int id PK
        int user_id FK
        int recipe_id FK
        bool suitable
        datetime created_at
    }
    USAGE_EVENTS {
        int id PK
        int user_id FK
        string event_type
        datetime occurred_at
    }
```

## Таблицы и ключи

| Таблица | Назначение и ключи |
| --- | --- |
| `users` | Учётная запись. `id` — первичный ключ, `email` уникален. |
| `profiles` | Один профиль на пользователя. `user_id` — внешний ключ и уникальный столбец. |
| `profile_settings` | По одному значению предпочтения или исключения в строке. Первичный ключ: `(profile_id, kind, position)`; `kind` ограничен значениями `preference` и `exclusion`. Позиция сохраняет исходный порядок. |
| `login_sessions` | Сессии пользователя. Хранится хеш токена; `token_hash` уникален. |
| `recipes` | Основные атрибуты рецепта и его владелец. Время приготовления может отсутствовать. |
| `recipe_input_products` | Продукты, указанные для запроса. Ключ `(recipe_id, position)`. |
| `recipe_ingredients` | Ингредиент и его количество. Ключ `(recipe_id, position)`; количество может отсутствовать. |
| `recipe_steps` | Текст шага и необязательная длительность. Ключ `(recipe_id, position)`. |
| `recipe_missing_products` | Продукты, которых не хватает для рецепта. Ключ `(recipe_id, position)`. |
| `recipe_ratings` | Оценка пригодности. Ограничение уникальности `(user_id, recipe_id)` оставляет одну актуальную оценку пользователя на рецепт. |
| `usage_events` | Событие пользователя и время события; текст запроса и список продуктов здесь не хранятся. |

В дочерних таблицах `position` нумерует строки внутри владельца, чтобы при чтении восстановить порядок продуктов, ингредиентов и шагов. Удаление пользователя каскадно удаляет его профиль, сессии, рецепты и события; удаление рецепта — его дочерние строки и оценку.

## Нормализация

Модель приведена к 3НФ. Значения списков разложены на отдельные строки: каждая ячейка хранит одно значение (1НФ). Составные ключи дочерних таблиц включают владельца и позицию, а остальные поля зависят от всего ключа (2НФ). В таблицах нет полей, зависящих от других неключевых полей; например, название и количество ингредиента хранятся в строке, идентифицируемой рецептом и позицией (3НФ). Данные профиля не дублируются в рецептах, а данные владельца не копируются в строки ингредиентов.

ORM сохраняет удобное для приложения представление: поля `input_products`, `ingredients`, `steps`, `missing_products`, `preferences` и `exclusions` читаются и записываются как обычные списки. Это преобразование выполняется между объектами приложения и нормализованными таблицами; в БД массивов JSON для них нет.

## Проверки и обновление

Миграция `d7c4a1e82b90` переносит существующие списки профиля и рецептов в дочерние таблицы, сохраняя значения и порядок. Автоматические интеграционные тесты проверяют миграцию вперёд и назад на SQLite. Отдельные тесты PostgreSQL запускаются в CI и проверяют сохранение, восстановление порядка и ограничения связей в целевой СУБД.

При выдаче и сохранении рецепта backend проверяет его ингредиенты по активным исключениям. Книга рецептов выбирает только сохранённые рецепты текущего пользователя; операции с книгой и оценками ограничиваются владельцем.
