# Руководство разработчика (внутренние чеклисты)

## Добавление новой таблицы индекса (17 шагов)

1. **`bsl_index.py` `_SCHEMA_SQL`** — `CREATE TABLE` с колонками и типами
2. **`bsl_index.py` `_SCHEMA_SQL`** — `CREATE INDEX` для поиска (NOCASE для текстовых)
3. **`bsl_index.py` `_collect_metadata_tables()`** — сбор данных из XML/файлов
4. **`bsl_xml_parsers.py`** — парсер для CF-формата (если XML-источник)
5. **`bsl_xml_parsers.py`** — парсер для EDT-формата (если `.mdo`-источник)
6. **`bsl_index.py` `_insert_metadata_tables()`** — `INSERT` собранных данных
7. **`bsl_index.py` `IndexBuilder.build()`** — интеграция в полную сборку
8. **`bsl_index.py` `IndexBuilder.update()`** — `CREATE TABLE IF NOT EXISTS` для совместимости со старыми индексами
9. **`bsl_index.py` `index_meta`** — ключи `has_X`, `X_count` в метаданных
10. **`bsl_index.py` `IndexReader`** — `get_X()` метод с параметром `limit`
11. **`bsl_index.py` `get_statistics()`** — счётчик в статистике
12. **`cli.py`** — вывод в `build` / `info`
13. **`bsl_helpers.py`** — helper-функция + `_reg(name, fn, sig, cat, kw, recipe)`
14. **`bsl_knowledge.py`** — WORKFLOW, INDEX TIPS, recipe (если бизнес-домен)
15. **`docs/INDEXING.md`** — схема таблицы, API, benchmark
16. **`docs/HELPERS.md`** — описание хелпера
17. **`tests/`** — тесты: builder, reader, helper, CLI assertions
18. **Git fast path** — обновить `_update_git_fast()`, `_collect_metadata_tables()` kwargs, `_insert_metadata_tables_selective()` — см. [INDEXING.md § 6.1 «Добавление новых категорий / таблиц»](INDEXING.md#добавление-новых-категорий--таблиц-чеклист-для-разработчика)

## Добавление нового хелпера (обновлённый чеклист — уроки v1.36.0)

Прежняя версия («4 шага») занижала реальное число точек синхронизации — за сессию v1.36.0 (два новых хелпера, `find_role_objects` и `get_object_structures`) почти каждая из них хоть раз была упущена с первого захода. Полный список:

1. **`bsl_helpers.py`** — функция + `_reg(name, fn, sig, cat, kw, recipe)`.
2. **`bsl_knowledge.py`** — recipe (если хелпер привязан к бизнес-домену) и/или строка дизамбигуации в `_STRATEGY_HEADER` (если новый хелпер пересекается по смыслу с уже существующим).
3. **Дизамбигуация — если добавлена пара, у нее ТРИ точки синхронизации, а не одна:**
   - структурированная запись в `DISAMBIGUATION_PAIRS` (`bsl_strategy_data.py`);
   - точный заголовок `A(...) vs B(...):` в `_STRATEGY_HEADER` (`bsl_knowledge.py`) — сверяется regex-тестом `test_full_strategy_block_covers_every_structured_pair`;
   - `_SLIM_DISAMBIGUATION_POINTER` НЕ трогать руками — он сам считает `len(DISAMBIGUATION_PAIRS)`.
4. **`docs/HELPERS.md`** — описание в соответствующей категории.
5. **`CHANGELOG.md`** — запись в `[Unreleased]` (`### Добавлено`).
6. **`tests/`** — тесты хелпера (вызов, параметры, ожидаемый вывод, изоляция ошибок, empty-table `None` vs no-match `[]` для reader-методов).
7. **Счётчики, залоченные тестами — бампнуть ВСЕ, если добавлен хелпер и/или пара дизамбигуации:**
   - `tests/test_start_cost_budget.py::test_helper_snapshot_count_locked` — общее число хелперов;
   - `tests/test_strategy_data.py::test_disambiguation_pairs_count` — число пар;
   - `tests/test_rlm_help.py::test_disambiguation_full` — **зеркало предыдущего теста в ДРУГОМ файле**, легко упустить, потому что ничего явно на него не ссылается кроме комментария в MODULE_MAP.md.
8. **Прозаические упоминания итоговых чисел — они дублируются в нескольких файлах и расходятся молча, т.к. ничем не залочены тестами. Прогнать `grep -rn "хелпер" docs/*.md README.md src/rlm_tools_bsl/_sandbox_config.py` и поправить каждое совпадение с устаревшим числом:**
   - `docs/MODULE_MAP.md` — строка «Хелперов в песочнице» (с разбивкой по категориям) и соседняя строка «Пары DISAMBIGUATION», плюс замечание техобслуживания у `test_helper_snapshot_count_locked`;
   - `docs/ARCHITECTURE.md` — «N BSL-специфичных хелпера + 8 стандартных I/O + 2 LLM = **M хелперов**»;
   - `README.md` — та же формула в разделе «Как работает (под капотом)»;
   - `docs/FAQ.md` — «все N хелперов» (встречается не один раз в файле);
   - `src/rlm_tools_bsl/_sandbox_config.py` — комментарий про размер IPC-снапшота («N хелперов с recipe» ~KiB) в `ipc_max_bytes()`.
9. **Перед тем как считать задачу закрытой** — прогнать полный `pytest`, а не только static-review: точечные символьные бюджеты (`test_start_cost_budget.py`, ±5% допуска) и мелкие regex-тесты на дизамбигуацию проще всего сломать именно строчечными правками текста рецептов/стратегии, и такие поломки не видны при чтении диффа глазами.

## Добавление нового бизнес-рецепта (2 шага)

1. **`bsl_knowledge.py` `_BUSINESS_RECIPES`** — новый рецепт (ключевые слова + шаблон ответа)
2. **`tests/`** — тест на matching (ключевые слова совпадают, рецепт возвращается)
