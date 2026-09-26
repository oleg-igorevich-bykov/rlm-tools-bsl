"""v17: реестр объектов метаданных (``metadata_objects``) и свойства регистров."""

import sqlite3
import subprocess

import pytest

from rlm_tools_bsl.bsl_index import (
    IndexBuilder,
    IndexReader,
    _collect_metadata_objects,
)
from rlm_tools_bsl.bsl_xml_parsers import parse_metadata_xml

_NS = (
    'xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core" '
    'xmlns:xr="http://v8.1c.ru/8.3/xcf/readable"'
)


def _cf(kind: str, name: str, props: str = "", children: str = "") -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<MetaDataObject {_NS}>\n<{kind}>\n'
        f"  <Properties><Name>{name}</Name>{props}</Properties>\n"
        f"  <ChildObjects>{children}</ChildObjects>\n</{kind}>\n</MetaDataObject>\n"
    )


def _dim(name: str) -> str:
    return (
        f"<Dimension><Properties><Name>{name}</Name><Type><v8:Type>xs:string</v8:Type></Type></Properties></Dimension>"
    )


def _res(name: str) -> str:
    return (
        f"<Resource><Properties><Name>{name}</Name><Type><v8:Type>xs:decimal</v8:Type></Type></Properties></Resource>"
    )


_INFO_REG = _cf(
    "InformationRegister",
    "КурсыВалют",
    "<InformationRegisterPeriodicity>Day</InformationRegisterPeriodicity><WriteMode>Independent</WriteMode>",
    _dim("Валюта") + _res("Курс"),
)
_ACCUM_REG = _cf("AccumulationRegister", "Остатки", "<RegisterType>Turnovers</RegisterType>", _dim("Склад"))
_CATALOG = _cf(
    "Catalog",
    "Пользователи",
    "",
    "<TabularSection><Properties><Name>Контакты</Name></Properties><ChildObjects/></TabularSection>",
)
_ENUM = _cf("Enum", "Статусы")

_EDT_REG = """\
<?xml version="1.0" encoding="UTF-8"?>
<mdclass:InformationRegister xmlns:mdclass="http://g5.1c.ru/v8/dt/metadata/mdclass">
  <name>РегЭДТ</name>
  <periodicity>Month</periodicity>
</mdclass:InformationRegister>
"""
_EDT_REG_DEFAULTS = _EDT_REG.replace("<periodicity>Month</periodicity>", "").replace("РегЭДТ", "РегБезСвойств")


@pytest.fixture()
def project(tmp_path):
    for cat, name, xml in (
        ("InformationRegisters", "КурсыВалют", _INFO_REG),
        ("AccumulationRegisters", "Остатки", _ACCUM_REG),
        ("Catalogs", "Пользователи", _CATALOG),
        ("Enums", "Статусы", _ENUM),
    ):
        (tmp_path / cat).mkdir()
        (tmp_path / cat / f"{name}.xml").write_text(xml, encoding="utf-8")
    for name, xml in (("РегЭДТ", _EDT_REG), ("РегБезСвойств", _EDT_REG_DEFAULTS)):
        d = tmp_path / "InformationRegisters" / name
        d.mkdir()
        (d / f"{name}.mdo").write_text(xml, encoding="utf-8")
    return tmp_path


def test_parser_register_props_cf():
    parsed = parse_metadata_xml(_INFO_REG)
    assert parsed["register_props"] == {"periodicity": "Day", "writeMode": "Independent"}
    assert parse_metadata_xml(_ACCUM_REG)["register_props"] == {"registerType": "Turnovers"}


def test_parser_register_props_edt_absent_is_none():
    assert parse_metadata_xml(_EDT_REG)["register_props"] == {"periodicity": "Month", "writeMode": None}
    assert parse_metadata_xml(_EDT_REG_DEFAULTS)["register_props"]["periodicity"] is None


def test_parser_no_register_props_for_other_kinds():
    assert "register_props" not in parse_metadata_xml(_CATALOG)


def test_collector_covers_all_categories_and_props(project):
    rows = {(c, n): p for c, n, p, _ in _collect_metadata_objects(str(project))}
    assert ("Enums", "Статусы") in rows  # существование без разбора
    assert rows[("Enums", "Статусы")] == "{}"
    assert '"Контакты"' in rows[("Catalogs", "Пользователи")]
    assert '"Day"' in rows[("InformationRegisters", "КурсыВалют")]


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", check=True)


@pytest.fixture()
def built(project, monkeypatch):
    monkeypatch.setenv("RLM_INDEX_DIR", str(project.parent / (project.name + "_idx")))
    _git(project, "init")
    _git(project, "config", "user.name", "Test")
    _git(project, "config", "user.email", "test@test.com")
    _git(project, "add", ".")
    _git(project, "commit", "-m", "initial")
    db_path = IndexBuilder().build(str(project), build_calls=False, build_fts=False)
    return project, db_path


def test_build_fills_registry(built):
    _, db_path = built
    conn = sqlite3.connect(str(db_path))
    n = conn.execute("SELECT COUNT(*) FROM metadata_objects").fetchone()[0]
    flag = conn.execute("SELECT value FROM index_meta WHERE key='has_metadata_objects'").fetchone()
    conn.close()
    assert n == 6
    assert flag[0] == "1"


def test_reader_exact_case_insensitive_cyrillic(built):
    _, db_path = built
    reader = IndexReader(db_path)
    try:
        obj = reader.get_metadata_object("InformationRegisters", "курсыВАЛЮТ")
        assert obj["object_name"] == "КурсыВалют"
        assert obj["props"]["reg"] == {"periodicity": "Day", "writeMode": "Independent"}
        assert reader.get_metadata_object("InformationRegisters", "Нет") == {}
        assert reader.get_metadata_object("Catalogs", "КурсыВалют") == {}
        assert "Пользователи" in reader.get_metadata_object_names("Catalogs")
        fields = reader.get_object_fields("InformationRegisters", "КурсыВалют")
        assert {(f["attr_name"], f["attr_kind"]) for f in fields} == {("Валюта", "dimension"), ("Курс", "resource")}
    finally:
        reader.close()


def test_update_rebuilds_registry_on_xml_change(built, monkeypatch):
    project, db_path = built
    new = project / "Catalogs" / "Валюты.xml"
    new.write_text(_cf("Catalog", "Валюты"), encoding="utf-8")
    (project / "Enums" / "Статусы.xml").unlink()
    _git(project, "add", "-A")
    _git(project, "commit", "-m", "change")
    IndexBuilder().update(str(project))
    reader = IndexReader(db_path)
    try:
        assert reader.get_metadata_object("Catalogs", "Валюты")["object_name"] == "Валюты"
        assert reader.get_metadata_object("Enums", "Статусы") == {}
    finally:
        reader.close()


def test_update_of_v16_index_forces_full_rebuild_and_fills_registry(built):
    """Порог принудительной пересборки поднят до 17: на индексе v16 таблицы реестра нет, а
    нетронутые XML `update` не перечитывает — без пересборки реестр остался бы пустым."""
    project, db_path = built
    conn = sqlite3.connect(str(db_path))
    conn.execute("DROP TABLE metadata_objects")
    conn.execute("DELETE FROM index_meta WHERE key='has_metadata_objects'")
    conn.execute("UPDATE index_meta SET value='16' WHERE key='builder_version'")
    conn.commit()
    conn.close()
    delta = IndexBuilder().update(str(project))
    assert "schema upgrade" in delta.get("rebuild_reason", ""), delta
    reader = IndexReader(db_path)
    try:
        assert reader.get_metadata_object("Catalogs", "Пользователи")["object_name"] == "Пользователи"
        assert reader.metadata_registry_state() == {"has_metadata": True, "has_registry": True}
    finally:
        reader.close()
