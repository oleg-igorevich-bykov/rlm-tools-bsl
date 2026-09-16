# rlm-tools-bsl — задачи для разработчика

Список найденных при эксплуатации проблем/доработок форка `rlm-tools-bsl`,
не решаемых на стороне fleet-инфраструктуры (`infra-mcp-fleet`/`mcp-fleet`) —
требуют правки в самом пакете. Ведётся в этом репозитории; на файл уже есть
ссылки из `fleet.yml`/`generate_fleet.py` (RLM_PROJECT_* auto-seed — см.
задачу ниже).

---

## 1. `graph_search_routines()` не соответствует актуальной сигнатуре `search_bsl_routines` на graph-стороне

**Статус:** исправлено в 1.36.0. Обёртка в `graph_bridge.py` приведена к реальной сигнатуре (`mode` обязателен, `search_text` вместо `query`), `GRAPH_HELPER_SIGNATURES` и `tests/test_graph_bridge.py::test_graph_search_routines_maps_to_search_bsl_routines` обновлены вместе с кодом (добавлен `test_graph_search_routines_requires_mode`).

---

## 2. RLM_PROJECT_* auto-seed из окружения

**Статус:** реализовано (см. `seed_project_from_env()` в `projects.py`, вызывается из `server.main()` сразу после `load_project_env()`; тесты — `tests/test_projects.py`). Описание ниже — как было сформулировано предложение от 24.07, оставлено для истории принятого решения; сам bind-mount `rlm_config_dir` можно убирать по готовности fleet-инфраструктуры перейти на переменные окружения.


Контейнер уже получает `RLM_PROJECT_NAME`/`RLM_PROJECT_PATH`/
`RLM_PROJECT_DESCRIPTION` (см. `generate_fleet.py` в `infra-mcp-fleet`/
`mcp-fleet`, комментарий у формирования env rlm-сервиса), но текущий образ
их игнорирует (безопасно, unknown env var). Предложение от 24.07: научить
образ на старте сам регистрировать/обновлять проект в `projects.json` по
этим переменным — тогда можно будет убрать текущий bind-mount
`rlm_config_dir` + generator-side запись `projects.json`, которые остаются
источником `_rlm`-symlink-race класса проблем (инцидент 24.07). Не убирать
bind-mount, пока эта задача не реализована и `RLM_VERSION` не подтверждён
обновлённым образом.
