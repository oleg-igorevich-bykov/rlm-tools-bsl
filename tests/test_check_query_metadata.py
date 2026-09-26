"""Хелпер check_query_metadata: кейсы A–K приёмки на мини-конфигурации в духе БСП."""

from __future__ import annotations

import pytest

from _query_fixtures import make_helpers_for


@pytest.fixture()
def env(tmp_path, monkeypatch):
    bsl, cf, reader = make_helpers_for(tmp_path, monkeypatch)
    try:
        yield bsl, cf
    finally:
        reader.close()


def _kinds(r):
    return [(f["kind"], f["table"], f["field"]) for f in r["findings"]]


def test_registered_and_documented_signature(env):
    bsl, _ = env
    assert "check_query_metadata" in bsl
    assert "check_query_metadata" in bsl["help"]()


def test_a_valid(env):
    bsl, _ = env
    r = bsl["check_query_metadata"](
        query="ВЫБРАТЬ Т.Ссылка КАК Ссылка, Т.Наименование КАК Имя ИЗ Справочник.Пользователи КАК Т"
    )
    assert r["findings"] == [] and r["partial"] is False
    c = r["checked"]
    assert (c["queries"], c["tables"], c["aliases"], c["fields"]) == (1, 1, 1, 2)


def test_b_missing_field(env):
    bsl, _ = env
    r = bsl["check_query_metadata"](query="ВЫБРАТЬ Т.НесуществующийРеквизитQ КАК Р ИЗ Справочник.Пользователи КАК Т")
    assert _kinds(r) == [("missing_field", "Справочник.Пользователи", "НесуществующийРеквизитQ")]
    assert r["findings"][0]["owner"] == "main"


def test_c_d_register_slice(env):
    bsl, _ = env
    ok = bsl["check_query_metadata"](
        query="ВЫБРАТЬ К.Валюта, К.Курс, К.Кратность ИЗ РегистрСведений.КурсыВалют.СрезПоследних КАК К"
    )
    assert ok["findings"] == [] and ok["checked"]["fields"] == 3
    bad = bsl["check_query_metadata"](
        query="ВЫБРАТЬ К.НетТакогоПоляQ ИЗ РегистрСведений.КурсыВалют.СрезПоследних КАК К"
    )
    assert _kinds(bad) == [("missing_field", "РегистрСведений.КурсыВалют.СрезПоследних", "НетТакогоПоляQ")]


def test_e_join(env):
    bsl, _ = env
    r = bsl["check_query_metadata"](
        query="ВЫБРАТЬ В.Ссылка, К.Курс ИЗ Справочник.Валюты КАК В "
        "ЛЕВОЕ СОЕДИНЕНИЕ РегистрСведений.КурсыВалют.СрезПоследних КАК К ПО В.Ссылка = К.Валюта"
    )
    c = r["checked"]
    assert r["findings"] == [] and (c["tables"], c["aliases"], c["fields"]) == (2, 2, 3)


def test_f_temp_table(env):
    bsl, _ = env
    r = bsl["check_query_metadata"](
        query="ВЫБРАТЬ Т.Ссылка КАК Ссылка ПОМЕСТИТЬ ВТ ИЗ Справочник.Пользователи КАК Т ; "
        "ВЫБРАТЬ Х.Ссылка, Х.ЧтоУгодноQ ИЗ ВТ КАК Х"
    )
    assert r["findings"] == []
    assert any(s["reason"] == "временная таблица" and s["field"] == "ЧтоУгодноQ" for s in r["skipped"])


def test_g_missing_object(env):
    bsl, _ = env
    r = bsl["check_query_metadata"](query="ВЫБРАТЬ Т.Ссылка ИЗ Справочник.ТакогоНетСправочника КАК Т")
    assert _kinds(r) == [("missing_object", "Справочник.ТакогоНетСправочника", "")]
    assert r["findings"][0]["owner"] is None and r["findings"][0]["uncertain"] is False


def test_h_missing_virtual_table(env):
    bsl, _ = env
    r = bsl["check_query_metadata"](query="ВЫБРАТЬ К.Курс ИЗ РегистрСведений.КурсыВалют.НетТакойВиртуальной КАК К")
    assert [f["kind"] for f in r["findings"]] == ["missing_virtual_table"]


def test_dirless_object_is_checked(env):
    """Валюты лежат БЕЗ каталога (`Валюты.xml` рядом): раньше их реквизитов в индексе не было."""
    bsl, _ = env
    r = bsl["check_query_metadata"](query="ВЫБРАТЬ Т.Наименование, Т.Плохое ИЗ Справочник.Валюты КАК Т")
    assert _kinds(r) == [("missing_field", "Справочник.Валюты", "Плохое")]


def test_common_attribute_field_is_not_reported(env):
    """Разделитель — общий реквизит: у объекта его нет, но в запросе он валиден."""
    bsl, _ = env
    r = bsl["check_query_metadata"](
        query="ВЫБРАТЬ Т.Разделитель ИЗ Справочник.Пользователи КАК Т, "
        "РегистрСведений.КурсыВалют.СрезПоследних КАК К ГДЕ К.Разделитель = Т.Разделитель"
    )
    assert r["findings"] == []
    bad = bsl["check_query_metadata"](query="ВЫБРАТЬ Т.РазделительX ИЗ Справочник.Пользователи КАК Т")
    assert [f["kind"] for f in bad["findings"]] == ["missing_field"]


def test_english_syntax(env):
    bsl, _ = env
    r = bsl["check_query_metadata"](query="SELECT T.Ref AS Ref, T.Description AS Name FROM Catalog.Пользователи AS T")
    assert r["findings"] == [] and r["checked"]["fields"] == 2


def test_tabular_section_from_registry(env):
    bsl, _ = env
    ok = bsl["check_query_metadata"](query="ВЫБРАТЬ Т.Тип ИЗ Справочник.Пользователи.КонтактнаяИнформация КАК Т")
    assert ok["findings"] == []
    bad = bsl["check_query_metadata"](query="ВЫБРАТЬ Т.Тип ИЗ Справочник.Пользователи.НетТакой КАК Т")
    assert [f["kind"] for f in bad["findings"]] == ["missing_tabular_section"]


def test_enum_exists_but_fields_skipped(env):
    bsl, _ = env
    r = bsl["check_query_metadata"](
        query="ВЫБРАТЬ Т.Ссылка ИЗ Перечисление.ВидыКонтактов КАК Т ГДЕ Т.Ссылка = ЗНАЧЕНИЕ(Перечисление.ВидыКонтактов.Х)"
    )
    assert r["findings"] == []


def test_i_module_lines(env):
    bsl, cf = env
    import os

    module = os.path.join(cf, "Catalogs", "Пользователи", "Ext", "ObjectModule.bsl")
    body = (
        "Процедура П1() Экспорт\n"
        "    Запрос = Новый Запрос;\n"
        '    Запрос.Текст = "ВЫБРАТЬ Т.Ссылка ИЗ Справочник.Пользователи КАК Т";\n'
        "КонецПроцедуры\n"
        "\n"
        "Процедура П2() Экспорт\n"
        "    Запрос = Новый Запрос;\n"
        '    Запрос.Текст = "ВЫБРАТЬ\n'
        "    |   Т.НесуществующийРеквизитQ\n"
        '    |ИЗ Справочник.Пользователи КАК Т";\n'
        "КонецПроцедуры\n"
        "\n"
        "Процедура П3() Экспорт\n"
        '    З = Новый Запрос("ВЫБРАТЬ Т.Ссылка ИЗ Справочник.ТакогоНетСправочника КАК Т");\n'
        "КонецПроцедуры\n"
    )
    with open(module, "w", encoding="utf-8-sig") as f:
        f.write(body)
    r = bsl["check_query_metadata"](path="Catalogs/Пользователи/Ext/ObjectModule.bsl")
    assert r["checked"]["queries"] == 3 and len(r["findings"]) == 2
    by_kind = {f["kind"]: f for f in r["findings"]}
    assert by_kind["missing_field"]["line"] == 9  # строка «|   Т.НесуществующийРеквизитQ»
    assert by_kind["missing_object"]["line"] == 14
    assert by_kind["missing_field"]["query_index"] == 1


def test_wrapped_assignment_line_is_literal_line(env):
    bsl, cf = env
    import os

    module = os.path.join(cf, "Catalogs", "Пользователи", "Ext", "ObjectModule.bsl")
    with open(module, "w", encoding="utf-8-sig") as f:
        f.write(
            "Процедура П() Экспорт\n"
            "    Запрос.Текст =\n"
            '        "ВЫБРАТЬ\n'
            "        |    Т.Плохое\n"
            '        |ИЗ Справочник.Пользователи КАК Т";\n'
            "КонецПроцедуры\n"
        )
    r = bsl["check_query_metadata"](path="Catalogs/Пользователи/Ext/ObjectModule.bsl")
    assert [(f["kind"], f["line"]) for f in r["findings"]] == [("missing_field", 4)]


def test_extract_queries_text_field_is_additive(env):
    bsl, cf = env
    import os

    module = os.path.join(cf, "Catalogs", "Пользователи", "Ext", "ObjectModule.bsl")
    with open(module, "w", encoding="utf-8-sig") as f:
        f.write('Запрос.Текст = "ВЫБРАТЬ Т.Ссылка ГДЕ Т.Х = ""а"" ИЗ Справочник.Пользователи КАК Т";\n')
    q = bsl["extract_queries"]("Catalogs/Пользователи/Ext/ObjectModule.bsl")[0]
    assert q["text"] == 'ВЫБРАТЬ Т.Ссылка ГДЕ Т.Х = "а" ИЗ Справочник.Пользователи КАК Т'
    assert q["text_preview"].startswith("ВЫБРАТЬ") and q["tables"] == ["Справочник.Пользователи"]
    assert "text" not in bsl["extract_queries"]("Catalogs/Пользователи/Ext/ObjectModule.bsl", include_text=False)[0]


def test_limit_truncates(env):
    bsl, _ = env
    q = "ВЫБРАТЬ " + ", ".join(f"Т.Нет{i}" for i in range(5)) + " ИЗ Справочник.Пользователи КАК Т"
    r = bsl["check_query_metadata"](query=q, limit=2)
    assert len(r["findings"]) == 2 and r["truncated"] is True and r["findings_total"] == 5


def test_argument_validation(env):
    bsl, _ = env
    assert "error" in bsl["check_query_metadata"]()
    assert "error" in bsl["check_query_metadata"](query="x", path="y")
    assert "error" in bsl["check_query_metadata"](query=None)
    r = bsl["check_query_metadata"](query="ВЫБРАТЬ 1", limit=None)
    assert "error" not in r


# --- расширения (кейс J) -------------------------------------------------------


def test_j_extension_attribute_counts_as_existing(tmp_path, monkeypatch):
    bsl, _cf, reader = make_helpers_for(tmp_path, monkeypatch, with_ext=True)
    try:
        r = bsl["check_query_metadata"](
            query="ВЫБРАТЬ Т.РасширенныйРеквизит, Т.Комментарий ИЗ Справочник.Пользователи КАК Т"
        )
        assert r["findings"] == []
        assert r["checked"]["by_owner"].get("main") == 1
        assert r["checked"]["by_owner"].get("extension:ExtQ") == 1
        bad = bsl["check_query_metadata"](query="ВЫБРАТЬ Т.НетТакого ИЗ Справочник.Пользователи КАК Т")
        assert bad["findings"][0]["owner"] == "main"
    finally:
        reader.close()


def test_extension_only_object_exists(tmp_path, monkeypatch):
    bsl, _cf, reader = make_helpers_for(tmp_path, monkeypatch, with_ext=True)
    try:
        r = bsl["check_query_metadata"](query="ВЫБРАТЬ Т.ЕгоРеквизит, Т.Нет ИЗ Справочник.ТолькоРасширение КАК Т")
        assert [(f["kind"], f["field"], f["owner"]) for f in r["findings"]] == [
            ("missing_field", "Нет", "extension:ExtQ")
        ]
        assert r["checked"]["by_owner"] == {"extension:ExtQ": 1}
    finally:
        reader.close()


# --- честность результата (кейс K) ---------------------------------------------


def test_k_no_index_is_partial(tmp_path, monkeypatch):
    bsl, _cf, _ = make_helpers_for(tmp_path, monkeypatch, with_index=False)
    r = bsl["check_query_metadata"](query="ВЫБРАТЬ Т.Ссылка ИЗ Справочник.Пользователи КАК Т")
    assert r["partial"] is True and r["findings"] == [] and r["note"]


def test_k_old_index_without_registry_is_partial(tmp_path, monkeypatch):
    import sqlite3

    bsl, cf, reader = make_helpers_for(tmp_path, monkeypatch)
    try:
        conn = sqlite3.connect(str(reader._db_path)) if hasattr(reader, "_db_path") else None
        if conn is not None:
            conn.execute("DELETE FROM index_meta WHERE key='has_metadata_objects'")
            conn.commit()
            conn.close()
        else:  # без доступа к пути — имитируем ридером без реестра
            reader.metadata_registry_state = lambda: {"has_metadata": True, "has_registry": False}
        r = bsl["check_query_metadata"](query="ВЫБРАТЬ Т.Ссылка ИЗ Справочник.Пользователи КАК Т")
        assert r["partial"] is True and r["findings"] == []
    finally:
        reader.close()
