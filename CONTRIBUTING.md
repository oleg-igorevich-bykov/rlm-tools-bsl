# Как внести вклад

Спасибо за интерес к проекту! Ниже — краткое руководство для контрибьюторов.

## Быстрый старт

```bash
git clone https://github.com/oleg-igorevich-bykov/rlm-tools-bsl.git
cd rlm-tools-bsl
uv sync --dev
```

## Запуск тестов

```bash
uv run pytest tests/ -v
```

Тесты запускаются без реальных конфигураций 1С — используются фикстуры с минимальными файловыми структурами.

## Линтер и форматтер

В проекте используется [ruff](https://github.com/astral-sh/ruff). CI проверяет линтинг и форматирование на каждый push/PR.

Проверить локально перед коммитом:
```bash
uv run ruff check src/ tests/      # линтер
uv run ruff format --check src/ tests/  # проверка форматирования
```

Автоформат:
```bash
uv run ruff format src/ tests/
```

Конфигурация — в `pyproject.toml` (секция `[tool.ruff]`).

### Pre-commit хуки (опционально)

Для автоматической проверки перед коммитом:
```bash
uv run pre-commit install
```

## Code style

- Python 3.10+, без type annotations в существующем коде (не добавляйте в чужой код)
- `ensure_ascii=False` во всех `json.dumps` — кириллица должна быть читаемой
- Документация и комментарии к коммитам — на русском языке
- Не хардкодить версию — она берётся из `pyproject.toml`

## Структура проекта

```
src/rlm_tools_bsl/     # основной пакет
  server.py             # MCP-сервер (rlm_start, rlm_execute, rlm_end)
  sandbox.py            # песочница выполнения кода
  bsl_helpers.py        # BSL-специфичные хелперы
  bsl_index.py          # SQLite-индекс методов
  llm_bridge.py         # интеграция с LLM-провайдерами
  cli.py                # CLI (rlm-bsl-index)
tests/                  # unit + integration тесты
docs/                   # документация
```

## Версионирование

Проект публикуется в [PyPI](https://pypi.org/project/rlm-tools-bsl/). Если ваш PR изменяет код (не только документацию), **обязательно сделайте bump версии** в `pyproject.toml` и `uv.lock`:

- Багфиксы: `x.x.x` → `x.x.x+1` (patch)
- Новые фичи: `x.x.x` → `x.x+1.0` (minor)

Не забудьте добавить запись в `CHANGELOG.md`.

## Как отправить изменения

1. Форкните репозиторий
2. Создайте ветку от `master` (`git checkout -b feature/my-feature`)
3. Внесите изменения и убедитесь, что тесты проходят
4. Если изменён код — сделайте version bump в `pyproject.toml`, обновите `uv.lock` (`uv lock`), и добавьте запись в `CHANGELOG.md`
5. Отправьте PR с описанием: что изменено и зачем

## Что можно улучшить

- Новые хелперы для анализа BSL (парсинг форм, работа с правами)
- Оптимизации производительности на больших конфигурациях
- Поддержка новых AI-клиентов и LLM-провайдеров
- Улучшение документации и примеров
- При выполнении доработок тщательно следите, чтобы стратегии и рецепты поиска не "распухали" и оставались понятными и для слабых моделей

Подробные чеклисты для добавления таблиц, хелперов и рецептов — **[docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)** | Карта модулей — **[docs/MODULE_MAP.md](docs/MODULE_MAP.md)**

## Вопросы и баги

Создавайте [issue](https://github.com/oleg-igorevich-bykov/rlm-tools-bsl/issues) с описанием проблемы, версией Python, ОС и воспроизводимым примером.
