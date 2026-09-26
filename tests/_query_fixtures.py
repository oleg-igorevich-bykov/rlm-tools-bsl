"""Общие фикстуры проверки запросов: мини-конфигурация в духе БСП + расширение."""

from __future__ import annotations

import os
import textwrap

from rlm_tools_bsl.bsl_helpers import make_bsl_helpers
from rlm_tools_bsl.bsl_index import IndexBuilder, IndexReader
from rlm_tools_bsl.format_detector import detect_format
from rlm_tools_bsl.helpers import make_helpers

NS = (
    'xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core" '
    'xmlns:xr="http://v8.1c.ru/8.3/xcf/readable"'
)

_CF_MAIN = f"""<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject {NS}><Configuration uuid="00000000-0000-0000-0000-000000000001"><Properties>
<Name>MainCfg</Name><NamePrefix/></Properties></Configuration></MetaDataObject>
"""


def ext_configuration_xml(name="ExtQ"):
    return textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <MetaDataObject {NS}><Configuration uuid="00000000-0000-0000-0000-000000000002"><Properties>
        <ObjectBelonging>Adopted</ObjectBelonging><Name>{name}</Name>
        <ConfigurationExtensionPurpose>Customization</ConfigurationExtensionPurpose>
        <NamePrefix>ext_</NamePrefix></Properties></Configuration></MetaDataObject>
    """)


def attr(name: str, kind: str = "Attribute", typ: str = "xs:string") -> str:
    return f"<{kind}><Properties><Name>{name}</Name><Type><v8:Type>{typ}</v8:Type></Type></Properties></{kind}>"


def ts(name: str, *attrs: str) -> str:
    return (
        f"<TabularSection><Properties><Name>{name}</Name></Properties>"
        f"<ChildObjects>{''.join(attr(a) for a in attrs)}</ChildObjects></TabularSection>"
    )


def obj_xml(kind: str, name: str, props: str = "", children: str = "") -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<MetaDataObject {NS}>\n<{kind}>\n'
        f"<Properties><Name>{name}</Name>{props}</Properties>\n"
        f"<ChildObjects>{children}</ChildObjects>\n</{kind}>\n</MetaDataObject>\n"
    )


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def make_main(cf: str) -> None:
    """Основная конфигурация: часть объектов с каталогом, часть только `Имя.xml`."""
    _write(os.path.join(cf, "Configuration.xml"), _CF_MAIN)
    users = obj_xml(
        "Catalog",
        "Пользователи",
        "",
        attr("Недействителен", typ="xs:boolean")
        + attr("Подразделение")
        + attr("Комментарий")
        + ts("КонтактнаяИнформация", "Тип", "Представление"),
    )
    _write(os.path.join(cf, "Catalogs", "Пользователи.xml"), users)
    _write(
        os.path.join(cf, "Catalogs", "Пользователи", "Ext", "ObjectModule.bsl"),
        "Процедура П() Экспорт\nКонецПроцедуры\n",
    )
    # Валюты — БЕЗ каталога (только sibling xml): ровно тот случай, что раньше выпадал из индекса
    _write(os.path.join(cf, "Catalogs", "Валюты.xml"), obj_xml("Catalog", "Валюты", "", attr("Наименование")))
    rates = obj_xml(
        "InformationRegister",
        "КурсыВалют",
        "<InformationRegisterPeriodicity>Day</InformationRegisterPeriodicity><WriteMode>Independent</WriteMode>",
        attr("Валюта", "Dimension")
        + attr("Курс", "Resource", "xs:decimal")
        + attr("Кратность", "Resource", "xs:decimal"),
    )
    _write(os.path.join(cf, "InformationRegisters", "КурсыВалют.xml"), rates)
    stock = obj_xml(
        "AccumulationRegister",
        "ТоварыНаСкладах",
        "<RegisterType>Balance</RegisterType>",
        attr("Склад", "Dimension") + attr("Количество", "Resource", "xs:decimal") + attr("Партия", "Attribute"),
    )
    _write(os.path.join(cf, "AccumulationRegisters", "ТоварыНаСкладах.xml"), stock)
    _write(os.path.join(cf, "Enums", "ВидыКонтактов.xml"), obj_xml("Enum", "ВидыКонтактов"))
    _write(os.path.join(cf, "CommonAttributes", "Разделитель.xml"), obj_xml("CommonAttribute", "Разделитель"))
    doc = obj_xml("Document", "Заказ", "", attr("Контрагент") + ts("Товары", "Номенклатура", "Количество"))
    _write(os.path.join(cf, "Documents", "Заказ.xml"), doc)


def make_extension(cfe: str) -> None:
    """Расширение: добавляет реквизит к существующему справочнику и новый объект."""
    _write(os.path.join(cfe, "Configuration.xml"), ext_configuration_xml())
    _write(
        os.path.join(cfe, "Catalogs", "Пользователи.xml"),
        obj_xml("Catalog", "Пользователи", "<ObjectBelonging>Adopted</ObjectBelonging>", attr("РасширенныйРеквизит")),
    )
    _write(
        os.path.join(cfe, "Catalogs", "ТолькоРасширение.xml"),
        obj_xml("Catalog", "ТолькоРасширение", "", attr("ЕгоРеквизит")),
    )


def make_helpers_for(tmp_path, monkeypatch, *, with_ext: bool = False, with_index: bool = True):
    """Вернуть (bsl_helpers, cf_root, reader_or_None)."""
    monkeypatch.setenv("RLM_INDEX_DIR", str(tmp_path / "idx"))
    cf = os.path.join(str(tmp_path), "src", "cf")
    cfe = os.path.join(str(tmp_path), "src", "cfe", "ExtQ")
    make_main(cf)
    if with_ext:
        make_extension(cfe)
    reader = None
    if with_index:
        db_path = IndexBuilder().build(cf, build_calls=False, build_metadata=True, build_fts=False)
        reader = IndexReader(db_path)
    generic, resolve_safe = make_helpers(cf, idx_reader=reader)
    bsl = make_bsl_helpers(
        base_path=cf,
        resolve_safe=resolve_safe,
        read_file_fn=generic["read_file"],
        grep_fn=generic["grep"],
        glob_files_fn=generic["glob_files"],
        format_info=detect_format(cf),
        idx_reader=reader,
        extension_paths=[cfe] if with_ext else None,
    )
    return bsl, cf, reader
