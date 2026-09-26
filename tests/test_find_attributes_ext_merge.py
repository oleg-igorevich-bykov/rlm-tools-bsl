"""v1.39.0: find_attributes(object_name=...) подмешивает реквизиты расширения к объекту основной конфигурации."""

from __future__ import annotations

import pytest

from _query_fixtures import make_helpers_for


@pytest.fixture()
def env(tmp_path, monkeypatch):
    bsl, _cf, reader = make_helpers_for(tmp_path, monkeypatch, with_ext=True)
    try:
        yield bsl
    finally:
        reader.close()


def test_extension_attr_added_to_main_object(env):
    rows = env["find_attributes"](object_name="Пользователи")
    names = {r["attr_name"] for r in rows}
    assert {"Недействителен", "Комментарий", "РасширенныйРеквизит"} <= names
    ext = [r for r in rows if r["attr_name"] == "РасширенныйРеквизит"]
    assert ext[0]["owner"].startswith("extension:")
    main = [r for r in rows if r["attr_name"] == "Комментарий"]
    assert main[0]["owner"] == "main"


def test_no_duplicates_when_ext_repeats_main_attribute(env, tmp_path):
    rows = env["find_attributes"](object_name="Пользователи")
    keys = [(r["attr_name"], r["attr_kind"], r.get("ts_name")) for r in rows]
    assert len(keys) == len(set(keys))


def test_kind_and_name_filters_apply_to_ext_rows(env):
    assert env["find_attributes"](object_name="Пользователи", kind="dimension") == []
    rows = env["find_attributes"](name="Расширенный", object_name="Пользователи")
    assert [r["attr_name"] for r in rows] == ["РасширенныйРеквизит"]


def test_without_extension_behaviour_unchanged(tmp_path, monkeypatch):
    bsl, _cf, reader = make_helpers_for(tmp_path, monkeypatch, with_ext=False)
    try:
        names = {r["attr_name"] for r in bsl["find_attributes"](object_name="Пользователи")}
        assert "РасширенныйРеквизит" not in names
        assert "Комментарий" in names
    finally:
        reader.close()
