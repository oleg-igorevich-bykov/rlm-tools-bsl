# Спецификация: `check_query_metadata` — проверка запросов 1С по индексу метаданных

Источник требований: `D:\projects\rules\cc_rules_1c\docs\tasks\rlm-tools-bsl-query-validation.md` (ФТ-1…7, НФТ-1…3, кейсы A–K). Релиз: v1.39.0. Дизайн утверждён 2026-09-26.

## Принятые решения

| Вопрос | Решение |
|---|---|
| Данные о регистрах | Расширить индексатор: периодичность, режим записи, вид регистра. `BUILDER_VERSION` 16 → 17 |
| Существование объектов | Новая таблица `metadata_objects` по всем категориям `_CATEGORY_RU` |
| Расширения | Чиним слияние в `find_attributes(object_name=...)`: реквизиты расширения добавляются к непустому результату основной конфигурации (аддитивно) |
| Категории | Существование проверяется для всех запрашиваемых; поля — только для 6 категорий из `object_attributes`, для остальных поля идут в `skipped` |
| Имя хелпера | `check_query_metadata(query="", path="", limit=100)` |
| `source_file` в находках | не добавляется, достаточно `owner` |
| Форма/СКД | вне первой версии |
| `extract_queries` | новое поле `text` (ядро всегда возвращает текст) |

## Компоненты

1. **Индексатор** (`bsl_xml_parsers.py`, `bsl_index.py`): парсер CF и MDO читает свойства регистров; таблица `metadata_objects(category, object_name, props_json, source_file)`; заполнение во всех путях записи (bulk, selective, pointwise); ридер `get_metadata_object`.
2. **`find_attributes`**: слияние реквизитов расширений в режиме `object_name`.
3. **`bsl_query_check.py`** (чистый модуль): токенизатор запроса, разбор пакета (`;`, `ПОМЕСТИТЬ`, `ОБЪЕДИНИТЬ`, вложенные запросы), привязка «псевдоним → таблица», ссылки `Псевдоним.Поле`, стандартные реквизиты по видам объектов (ru/en, надмножество), закрытые списки виртуальных таблиц и суффиксы полей, ближайшие имена.
4. **`extract_queries`**: поле `text`.
5. **Хелпер** в `bsl_helpers.py`: проводка индекса, счётчики, `limit`, `line`, `owner`, `partial`/`uncertain`.
6. **Документация и тесты**: `bsl_knowledge.py`, `docs/HELPERS.md`, `AGENT_INSTRUCTIONS.md`, `CHANGELOG.md`, `tests/`.

## Политика молчания

Не находка, а `skipped` с причиной: поля временных таблиц, вложенных запросов и объединений, неизвестный псевдоним, параметры, выражения, разыменование (`Т.Владелец.Наименование`), поля регистров бухгалтерии и планов счетов, поля категорий вне `object_attributes`. Стандартные реквизиты берутся надмножеством без учёта свойств объекта.

## Формат ответа

```
{"checked": {"queries","tables","aliases","fields"},
 "findings": [{kind, severity, object, table, alias, field, line, query_index, owner, message, uncertain}],
 "skipped": [{reason, alias_or_table, line}],
 "partial": bool}
```

`kind`: `missing_object`, `missing_tabular_section`, `missing_virtual_table`, `missing_field`.

## Приёмка

Кейсы A–K задания на `D:\projects\docs\ssl\3.1.12\repo`; НФТ-1 (200 запросов ≤ 2 с); прогон по всем запросам БСП с разбором каждой находки на ложные.
