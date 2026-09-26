"""Чистый модуль проверки запросов: разбор и сверка на синтетическом окружении."""

from __future__ import annotations

from rlm_tools_bsl.bsl_query_check import ObjInfo, QueryEnv, check_query


def _obj(category, name, attrs=(), dims=(), res=(), ts=None, reg=None, owner="main", fields_known=True):
    info = ObjInfo(category=category, name=name, owner=owner, reg=reg or {}, fields_known=fields_known)
    for a in attrs:
        info.fields[a.lower()] = (a, "attribute")
    for d in dims:
        info.fields[d.lower()] = (d, "dimension")
    for r in res:
        info.fields[r.lower()] = (r, "resource")
    if ts is not None:
        info.ts_known = True
        info.tabular_sections = list(ts)
        for tname, tattrs in ts.items():
            info.ts_fields[tname.lower()] = {a.lower(): a for a in tattrs}
    return info


def _catalog():
    return {
        ("Catalogs", "пользователи"): _obj(
            "Catalogs",
            "Пользователи",
            attrs=["Недействителен", "Подразделение", "Комментарий"],
            ts={"КонтактнаяИнформация": ["Тип", "Представление"]},
        ),
        ("Catalogs", "валюты"): _obj("Catalogs", "Валюты", attrs=["Наименование"], ts={}),
        ("InformationRegisters", "курсывалют"): _obj(
            "InformationRegisters",
            "КурсыВалют",
            dims=["Валюта"],
            res=["Курс", "Кратность"],
            reg={"periodicity": "Day"},
        ),
        ("AccumulationRegisters", "товары"): _obj(
            "AccumulationRegisters",
            "Товары",
            dims=["Склад"],
            res=["Количество"],
            reg={"registerType": "Balance"},
        ),
        ("AccumulationRegisters", "обороты"): _obj(
            "AccumulationRegisters", "Обороты", dims=["Склад"], res=["Сумма"], reg={"registerType": "Turnovers"}
        ),
        ("InformationRegisters", "непериодический"): _obj(
            "InformationRegisters",
            "Непериодический",
            dims=["Ключ"],
            res=["Значение"],
            reg={"periodicity": "Nonperiodical"},
        ),
        ("Documents", "заказ"): _obj(
            "Documents", "Заказ", attrs=["Контрагент"], ts={"Товары": ["Номенклатура", "Количество"]}
        ),
        ("Enums", "виды"): _obj("Enums", "Виды", fields_known=False),
    }


def _env(uncertain=False):
    data = _catalog()

    def lookup(cat, name):
        return data.get((cat, name.lower()))

    def names(cat):
        return [o.name for (c, _), o in data.items() if c == cat]

    return QueryEnv(lookup=lookup, names=names, uncertain=uncertain)


def run(text, **kw):
    return check_query(text, _env(kw.pop("uncertain", False)), **kw)


def kinds(res):
    return [(f["kind"], f["table"], f["field"]) for f in res.findings]


# --- кейсы A–H задания -------------------------------------------------------


def test_a_valid_catalog_fields():
    r = run("ВЫБРАТЬ Т.Ссылка КАК Ссылка, Т.Наименование КАК Имя ИЗ Справочник.Пользователи КАК Т")
    assert r.findings == [] and (r.tables, r.aliases, r.fields) == (1, 1, 2)


def test_b_missing_field():
    r = run("ВЫБРАТЬ Т.НесуществующийРеквизитQ КАК Р ИЗ Справочник.Пользователи КАК Т")
    assert kinds(r) == [("missing_field", "Справочник.Пользователи", "НесуществующийРеквизитQ")]
    assert "Пользователи" in r.findings[0]["message"]


def test_c_valid_slice_last():
    r = run(
        "ВЫБРАТЬ К.Валюта КАК В, К.Курс КАК Курс, К.Кратность КАК Кр ИЗ РегистрСведений.КурсыВалют.СрезПоследних КАК К"
    )
    assert r.findings == [] and r.fields == 3


def test_d_missing_field_in_slice():
    r = run("ВЫБРАТЬ К.НетТакогоПоляQ КАК X ИЗ РегистрСведений.КурсыВалют.СрезПоследних КАК К")
    assert kinds(r) == [("missing_field", "РегистрСведений.КурсыВалют.СрезПоследних", "НетТакогоПоляQ")]


def test_e_join_counts_unique_fields():
    r = run(
        "ВЫБРАТЬ В.Ссылка КАК Ссылка, К.Курс КАК Курс ИЗ Справочник.Валюты КАК В "
        "ЛЕВОЕ СОЕДИНЕНИЕ РегистрСведений.КурсыВалют.СрезПоследних КАК К ПО В.Ссылка = К.Валюта"
    )
    assert r.findings == [] and (r.tables, r.aliases, r.fields) == (2, 2, 3)


def test_f_temp_table_fields_skipped():
    r = run(
        "ВЫБРАТЬ Т.Ссылка КАК Ссылка ПОМЕСТИТЬ ВТ ИЗ Справочник.Пользователи КАК Т ; "
        "ВЫБРАТЬ Х.Ссылка КАК Ссылка, Х.ЧтоУгодноQ КАК Что ИЗ ВТ КАК Х"
    )
    assert r.findings == []
    assert {s["reason"] for s in r.skipped} == {"временная таблица"}
    assert any(s["field"] == "ЧтоУгодноQ" for s in r.skipped)


def test_g_missing_object_no_field_noise():
    r = run("ВЫБРАТЬ Т.Ссылка КАК Ссылка ИЗ Справочник.ТакогоНетСправочника КАК Т")
    assert kinds(r) == [("missing_object", "Справочник.ТакогоНетСправочника", "")]
    assert r.skipped == []


def test_h_missing_virtual_table():
    r = run("ВЫБРАТЬ К.Курс ИЗ РегистрСведений.КурсыВалют.НетТакойВиртуальной КАК К")
    assert [f["kind"] for f in r.findings] == ["missing_virtual_table"]
    assert "СрезПоследних" in r.findings[0]["message"]


# --- язык, регистр, синтаксис ---------------------------------------------------


def test_english_syntax_and_case_insensitive():
    r = run("SELECT T.Ref AS Ref, t.description AS Name FROM catalog.пользователи AS T")
    assert r.findings == [] and r.fields == 2


def test_alias_named_like_kind_is_not_an_object():
    r = run("ВЫБРАТЬ Документ.Номер ИЗ Документ.Заказ КАК Документ")
    assert r.findings == []


def test_implicit_alias_without_as():
    r = run("ВЫБРАТЬ Т.Ссылка ИЗ Справочник.Пользователи Т")
    assert r.findings == [] and r.aliases == 1


def test_default_alias_is_last_name_part():
    r = run("ВЫБРАТЬ Валюты.Наименование, Валюты.Плохое ИЗ Справочник.Валюты")
    assert kinds(r) == [("missing_field", "Справочник.Валюты", "Плохое")]


# --- табличные части -----------------------------------------------------------


def test_tabular_section_ok_and_fields():
    r = run("ВЫБРАТЬ Т.Номенклатура, Т.НомерСтроки, Т.Ссылка, Т.Нет ИЗ Документ.Заказ.Товары КАК Т")
    assert kinds(r) == [("missing_field", "Документ.Заказ.Товары", "Нет")]


def test_missing_tabular_section():
    r = run("ВЫБРАТЬ Т.Тип ИЗ Справочник.Пользователи.КонтактнаяИнформацияX КАК Т")
    assert [f["kind"] for f in r.findings] == ["missing_tabular_section"]
    assert "КонтактнаяИнформация" in r.findings[0]["message"]


def test_valid_tabular_section():
    r = run("ВЫБРАТЬ Т.Тип ИЗ Справочник.Пользователи.КонтактнаяИнформация КАК Т")
    assert r.findings == []


def test_ts_name_is_a_valid_field_of_main_table():
    r = run("ВЫБРАТЬ Т.Товары ИЗ Документ.Заказ КАК Т")
    assert r.findings == []


# --- виртуальные таблицы регистров накопления ----------------------------------


def test_balance_register_virtual_tables():
    r = run(
        "ВЫБРАТЬ О.Склад, О.КоличествоОстаток, П.КоличествоПриход, П.КоличествоРасход, П.НачальныйОстатокX "
        "ИЗ РегистрНакопления.Товары.Остатки(&Д) КАК О, РегистрНакопления.Товары.Обороты(&Н, &К) КАК П"
    )
    assert kinds(r) == [("missing_field", "РегистрНакопления.Товары.Обороты", "НачальныйОстатокX")]


def test_balance_and_turnovers_fields():
    r = run(
        "ВЫБРАТЬ Т.КоличествоНачальныйОстаток, Т.КоличествоКонечныйОстаток, Т.КоличествоОборот, Т.Период "
        "ИЗ РегистрНакопления.Товары.ОстаткиИОбороты(, , Месяц, , ) КАК Т"
    )
    assert r.findings == []


def test_turnover_register_has_no_balance_tables():
    r = run("ВЫБРАТЬ Т.СуммаОборот ИЗ РегистрНакопления.Обороты.Остатки КАК Т")
    assert [f["kind"] for f in r.findings] == ["missing_virtual_table"]


def test_nonperiodical_register_has_no_slices():
    r = run("ВЫБРАТЬ Т.Ключ ИЗ РегистрСведений.Непериодический.СрезПоследних КАК Т")
    assert [f["kind"] for f in r.findings] == ["missing_virtual_table"]


def test_register_main_table_standard_attrs():
    r = run("ВЫБРАТЬ Т.Период, Т.Регистратор, Т.Склад, Т.КоличествоX ИЗ РегистрНакопления.Товары КАК Т")
    assert kinds(r) == [("missing_field", "РегистрНакопления.Товары", "КоличествоX")]


# --- политика молчания ---------------------------------------------------------


def test_subquery_alias_fields_skipped():
    r = run("ВЫБРАТЬ П.Что ИЗ (ВЫБРАТЬ Т.Ссылка КАК Что ИЗ Справочник.Пользователи КАК Т) КАК П")
    assert r.findings == []
    assert [s["reason"] for s in r.skipped] == ["вложенный запрос"]


def test_correlated_subquery_sees_outer_alias():
    r = run(
        "ВЫБРАТЬ Т.Ссылка ИЗ Справочник.Пользователи КАК Т "
        "ГДЕ Т.Ссылка В (ВЫБРАТЬ З.Контрагент ИЗ Документ.Заказ КАК З ГДЕ З.Контрагент = Т.Комментарий)"
    )
    assert r.findings == []
    r2 = run(
        "ВЫБРАТЬ Т.Ссылка ИЗ Справочник.Пользователи КАК Т "
        "ГДЕ Т.Ссылка В (ВЫБРАТЬ З.Контрагент ИЗ Документ.Заказ КАК З ГДЕ З.Контрагент = Т.НетТакого)"
    )
    assert kinds(r2) == [("missing_field", "Справочник.Пользователи", "НетТакого")]


def test_unknown_alias_skipped():
    r = run("ВЫБРАТЬ Х.Поле ИЗ Справочник.Пользователи КАК Т")
    assert r.findings == [] and r.skipped[0]["reason"] == "неизвестный псевдоним"


def test_numbers_and_params_are_not_refs():
    r = run("ВЫБРАТЬ 1.5 КАК Ч, &Пар.Поле ИЗ Справочник.Пользователи КАК Т ГДЕ Т.Комментарий = &П")
    assert r.findings == [] and r.skipped == []


def test_strings_and_comments_ignored():
    r = run('ВЫБРАТЬ "Т.Нет" КАК А, Т.Ссылка // Т.Нет2\nИЗ Справочник.Пользователи КАК Т')
    assert r.findings == []


def test_union_blocks_have_own_aliases():
    r = run(
        "ВЫБРАТЬ Т.Ссылка ИЗ Справочник.Пользователи КАК Т ОБЪЕДИНИТЬ ВСЕ ВЫБРАТЬ Т.Ссылка ИЗ Справочник.Валюты КАК Т"
    )
    assert r.findings == []
    r2 = run(
        "ВЫБРАТЬ Т.Ссылка ИЗ Справочник.Пользователи КАК Т ОБЪЕДИНИТЬ ВСЕ "
        "ВЫБРАТЬ Т.Комментарий ИЗ Справочник.Валюты КАК Т"
    )
    assert kinds(r2) == [("missing_field", "Справочник.Валюты", "Комментарий")]


def test_fields_of_unindexed_category_skipped():
    r = run("ВЫБРАТЬ Т.Что ИЗ Перечисление.Виды КАК Т")
    assert r.findings == []
    assert r.skipped[0]["reason"] == "состав полей категории не индексируется"


def test_extract_and_deref_only_first_part_checked():
    r = run("ВЫБРАТЬ Т.Подразделение.Наименование ИЗ Справочник.Пользователи КАК Т")
    assert r.findings == []


# --- ложные срабатывания, найденные прогоном по БСП ------------------------------


def test_common_attribute_is_a_valid_field_of_any_object():
    """Разделитель `ОбластьДанныхВспомогательныеДанные` — общий реквизит: в составе объекта его нет."""
    env = _env()
    env.common_fields = frozenset({"областьданныхвспомогательныеданные"})
    q = "ВЫБРАТЬ К.ОбластьДанныхВспомогательныеДанные, К.Курс ИЗ РегистрСведений.КурсыВалют.СрезПоследних КАК К"
    assert check_query(q, env).findings == []
    q2 = "ВЫБРАТЬ Т.ОбластьДанныхВспомогательныеДанные ИЗ Справочник.Пользователи КАК Т"
    assert check_query(q2, env).findings == []
    assert check_query(q.replace("ОбластьДанныхВспомогательныеДанные", "Нет"), env).findings != []


def test_substitution_placeholder_source_is_opaque_and_alias_is_not_an_object():
    """`ИЗ #ИмяТаблицы КАК ПланОбмена`: `ПланОбмена.Ссылка` — псевдоним, а не объект."""
    r = run("ВЫБРАТЬ ПланОбмена.Ссылка ИЗ #ИмяТаблицыПланаОбмена КАК ПланОбмена ГДЕ НЕ ПланОбмена.ЭтотУзел")
    assert r.findings == []
    assert {s["reason"] for s in r.skipped} == {"параметр запроса"}


def test_question_mark_placeholder_in_table_path_is_opaque():
    r = run(
        "ВЫБРАТЬ КОЛИЧЕСТВО(ТабличнаяЧасть?.Ссылка) ИЗ Справочник.Пользователи.ТабличнаяЧасть? КАК ТабличнаяЧасть? "
        "ГДЕ ТабличнаяЧасть?.Ссылка = &Ключ"
    )
    assert r.findings == []


def test_percent_placeholder_object_name_is_ignored():
    r = run("ВЫБРАТЬ Т.Ссылка ИЗ Справочник.%1 КАК Т")
    assert r.findings == []


def test_alias_equal_to_kind_word_declared_via_as_wins_over_object():
    r = run("ВЫБРАТЬ Справочник.Х ИЗ &Таблица КАК Справочник")
    assert r.findings == []


def test_cast_to_missing_object_is_still_reported_when_kind_not_an_alias():
    r = run("ВЫБРАТЬ ВЫРАЗИТЬ(Т.Комментарий КАК Справочник.НетТакого) ИЗ Справочник.Пользователи КАК Т")
    assert [f["kind"] for f in r.findings] == ["missing_object"]


# --- объекты вне FROM ----------------------------------------------------------


def test_object_refs_anywhere():
    r = run(
        "ВЫБРАТЬ ВЫРАЗИТЬ(Т.Комментарий КАК Справочник.НетТакого) КАК А, ТИП(Документ.Заказ) КАК Б "
        "ИЗ Справочник.Пользователи КАК Т ГДЕ Т.Ссылка = ЗНАЧЕНИЕ(Справочник.Пользователи.ПустаяСсылка)"
    )
    assert kinds(r) == [("missing_object", "Справочник.НетТакого", "")]
    assert r.objects == 3


def test_field_chain_after_alias_is_not_object():
    r = run("ВЫБРАТЬ Т.Документ.Номер ИЗ Справочник.Пользователи КАК Т")
    assert [f["kind"] for f in r.findings] == ["missing_field"]  # поле «Документ» нет у справочника


# --- строки, дедупликация, неуверенность ----------------------------------------


def test_line_mapping_and_dedup():
    text = "ВЫБРАТЬ\n  Т.Плохое,\n  Т.Плохое\nИЗ Справочник.Пользователи КАК Т"
    r = run(text, base_line=10, query_index=3)
    assert len(r.findings) == 1
    assert r.findings[0]["line"] == 11 and r.findings[0]["query_index"] == 3


def test_missing_object_uncertain_on_partial_index():
    r = run("ВЫБРАТЬ Т.Ссылка ИЗ Справочник.Нет КАК Т", uncertain=True)
    f = r.findings[0]
    assert f["uncertain"] is True and f["severity"] == "warning"
    r2 = run("ВЫБРАТЬ Т.Нет ИЗ Справочник.Пользователи КАК Т", uncertain=True)
    assert r2.findings[0]["uncertain"] is False  # существование объекта доказано


def test_nearest_names_up_to_three():
    r = run("ВЫБРАТЬ Т.Комментарийй ИЗ Справочник.Пользователи КАК Т")
    assert "Комментарий" in r.findings[0]["message"]
    r2 = run("ВЫБРАТЬ Т.Ссылка ИЗ Справочник.Пользователь КАК Т")
    assert "Пользователи" in r2.findings[0]["message"]


def test_owner_is_propagated():
    env_data = {("Catalogs", "х"): _obj("Catalogs", "Х", attrs=["А"], owner="extension:Р")}
    env = QueryEnv(lookup=lambda c, n: env_data.get((c, n.lower())), names=lambda c: [])
    r = check_query("ВЫБРАТЬ Т.Б ИЗ Справочник.Х КАК Т", env)
    assert r.findings[0]["owner"] == "extension:Р"


def test_multiple_sources_via_comma_and_params():
    r = run("ВЫБРАТЬ А.Ссылка, Б.Ссылка ИЗ Справочник.Пользователи КАК А, Справочник.Валюты КАК Б ГДЕ А.Ссылка = &П")
    assert r.findings == [] and r.aliases == 2
