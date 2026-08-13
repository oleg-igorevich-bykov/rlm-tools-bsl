# rlm-tools-bsl — задачи для разработчика

Список найденных при эксплуатации проблем/доработок форка `rlm-tools-bsl`,
не решаемых на стороне fleet-инфраструктуры (`infra-mcp-fleet`/`mcp-fleet`) —
требуют правки в самом пакете. Ведётся в этом репозитории; на файл уже есть
ссылки из `fleet.yml`/`generate_fleet.py` (RLM_PROJECT_* auto-seed — см.
задачу ниже).

---

## 1. `graph_search_routines()` не соответствует актуальной сигнатуре `search_bsl_routines` на graph-стороне

**Статус:** открыта, есть рабочий обход (прямой вызов через `graph_call`/
`_call_tool_async` с правильными параметрами).
**Приоритет:** средний — публичная обёртка сломана для ЛЮБОГО вызова, но
низкоуровневый мост (`graph_bridge`) исправен, обходной путь есть.

### Где

`src/rlm_tools_bsl/graph_bridge.py:205-211`:

```python
def graph_search_routines(query: str, limit: int = 5, **filters) -> str:
    """Search routines by name/signature/description (metacode: search_bsl_routines)."""
    if not query:
        raise ValueError("graph_search_routines: 'query' cannot be empty")
    return call_tool_fn(
        "search_bsl_routines", {"query": query, "limit": limit, **filters}
    )
```

### В чём проблема

Обёртка шлёт `{"query": ..., "limit": ...}`, но актуальная сигнатура
`search_bsl_routines` на стороне графового сервера (1c-mcp-metacode,
`app/mcpsrv/typed_tools.py:5635`) требует **обязательный** `mode` и
`search_text` вместо `query`:

```python
def search_bsl_routines(
    mode: Literal["description", "name", "signature", "unused", "exported"],
    search_text: Optional[str] = None,
    search_match: Optional[Literal["exact", "starts_with", "contains"]] = None,
    owner_ref: Optional[str] = None,
    routine_type: Optional[Literal["Procedure", "Function"]] = None,
    export: Optional[bool] = None,
    directive: Optional[str] = None,
    is_ssl_api: Optional[bool] = None,
    routine_name: Optional[str] = None,
    owner_categories: Optional[List[str]] = None,
    module_type: Optional[Literal[...]] = None,
    min_score: Optional[float] = None,
    config: Optional[str] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    call_context_mode: Literal["none", "callees", "callers", "both"] = "none",
    call_context_limit: Optional[int] = 5,
    project_name: Optional[str] = None,
) -> str: ...
```

Похоже, сигнатура на стороне 1c-mcp-metacode эволюционировала (добавился
`mode`), а обёртка в форке не обновлена. Для сравнения — `graph_search_code`
(`query`/`limit` → `search_bsl_code`) и `graph_object_structure`
(`object_ref`/`sections` → `get_metadata_object_structure`) совпадают со
своими тулами один в один, там всё в порядке. Проблема только у
`graph_search_routines`.

### Как воспроизвести

Из rlm-контейнера (мост при этом полностью исправен — сеть/handshake/
доставка вызова работают, ошибка чисто в параметрах):

```bash
docker exec -i <rlm-контейнер> python3 - <<'PY'
from rlm_tools_bsl.graph_bridge import get_graph_config, _call_tool_async, _run_sync

url, timeout = get_graph_config()
out = _run_sync(_call_tool_async(url, "search_bsl_routines", {"query": "запись документа", "limit": 3}), timeout)
print(out)
PY
```

Результат — `RuntimeError` с Pydantic-валидацией:

```
2 validation errors for call[search_bsl_routines]
mode
  Missing required argument [type=missing_argument, ...]
query
  Unexpected keyword argument [type=unexpected_keyword_argument, ...]
```

Подтверждённый рабочий вызов с правильными параметрами (реальные данные
вернулись):

```bash
docker exec -i <rlm-контейнер> python3 - <<'PY'
from rlm_tools_bsl.graph_bridge import get_graph_config, _call_tool_async, _run_sync

url, timeout = get_graph_config()
out = _run_sync(_call_tool_async(url, "search_bsl_routines", {"mode": "description", "search_text": "запись документа", "limit": 3}), timeout)
print(out)
PY
```

### Предлагаемое исправление

Привести обёртку к реальной сигнатуре — `mode` обязателен, `query` заменить
на `search_text`:

```python
def graph_search_routines(mode: str, search_text: str | None = None, limit: int = 5, **filters) -> str:
    """Search/list BSL routines (metacode: search_bsl_routines).

    mode: 'description' | 'name' | 'signature' | 'unused' | 'exported'.
    search_text обязателен для description/name/signature (см. полное
    описание тула на graph-стороне — там же search_match/routine_type/
    export/owner_categories/module_type и т.д., прокидываются через **filters).
    """
    if not mode:
        raise ValueError("graph_search_routines: 'mode' cannot be empty")
    params = {"mode": mode, "limit": limit, **filters}
    if search_text is not None:
        params["search_text"] = search_text
    return call_tool_fn("search_bsl_routines", params)
```

Обновить и `GRAPH_HELPER_SIGNATURES` (описание для агента):

```python
"graph_search_routines(mode, search_text=None, limit=5, **filters) -> str — поиск/листинг процедур (граф); mode: description|name|signature|unused|exported",
```

### Тест, который нужно поправить вместе с кодом

`tests/test_graph_bridge.py:154` (`test_graph_search_routines_maps_to_search_bsl_routines`)
сейчас фиксирует СТАРОЕ (сломанное) поведение — проверяет, что
`graph_search_routines("РассчитатьГрафик", limit=2)` шлёт
`{"query": "РассчитатьГрафик", "limit": 2}`. Нужно переписать под новую
сигнатуру, например:

```python
def test_graph_search_routines_maps_to_search_bsl_routines():
    call = MagicMock(return_value="routine-hits")
    helpers = _helpers(call_tool_fn=call)

    out = helpers["graph_search_routines"]("name", search_text="РассчитатьГрафик", limit=2)

    assert out == "routine-hits"
    call.assert_called_once_with(
        "search_bsl_routines", {"mode": "name", "limit": 2, "search_text": "РассчитатьГрафик"}
    )
```

---

## 2. RLM_PROJECT_* auto-seed из окружения (задел на будущее)

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
