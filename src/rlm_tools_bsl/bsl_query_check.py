"""Проверка запроса 1С по метаданным конфигурации (v1.39.0).

Чистый модуль: без I/O и без обращений к индексу. Метаданные ему даёт вызывающий через
``QueryEnv`` (поиск объекта и список имён категории), поэтому логика разбора и сверки
тестируется на синтетических данных, а проводка индекса и расширений живёт в
``bsl_helpers.check_query_metadata``.

Политика молчания: ложное замечание хуже пропуска. Всё, что нельзя разрешить
однозначно (временные таблицы, вложенные запросы, неизвестные псевдонимы, параметры,
поля категорий с неразобранным составом), не считается ошибкой, а уходит в ``skipped``
с причиной.

Разбор — токенный, со стеком блоков ``ВЫБРАТЬ`` по глубине скобок. Ссылки ``Псевдоним.Поле``
собираются при проходе, а СВЕРЯЮТСЯ после него: источники (``ИЗ``/``СОЕДИНЕНИЕ``) стоят в
тексте ПОСЛЕ списка полей, которые на них ссылаются.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Callable

# ---------------------------------------------------------------------------
# Справочные данные
# ---------------------------------------------------------------------------

# Префикс вида объекта в запросе (оба языка, нижний регистр) -> категория индекса.
KIND_PREFIX: dict[str, str] = {
    "справочник": "Catalogs",
    "catalog": "Catalogs",
    "документ": "Documents",
    "document": "Documents",
    "перечисление": "Enums",
    "enum": "Enums",
    "планвидовхарактеристик": "ChartsOfCharacteristicTypes",
    "chartofcharacteristictypes": "ChartsOfCharacteristicTypes",
    "плансчетов": "ChartsOfAccounts",
    "chartofaccounts": "ChartsOfAccounts",
    "планвидоврасчета": "ChartsOfCalculationTypes",
    "chartofcalculationtypes": "ChartsOfCalculationTypes",
    "планобмена": "ExchangePlans",
    "exchangeplan": "ExchangePlans",
    "бизнеспроцесс": "BusinessProcesses",
    "businessprocess": "BusinessProcesses",
    "задача": "Tasks",
    "task": "Tasks",
    "регистрсведений": "InformationRegisters",
    "informationregister": "InformationRegisters",
    "регистрнакопления": "AccumulationRegisters",
    "accumulationregister": "AccumulationRegisters",
    "регистрбухгалтерии": "AccountingRegisters",
    "accountingregister": "AccountingRegisters",
    "регистррасчета": "CalculationRegisters",
    "calculationregister": "CalculationRegisters",
    "константа": "Constants",
    "constant": "Constants",
    "журналдокументов": "DocumentJournals",
    "documentjournal": "DocumentJournals",
}

CATEGORY_RU: dict[str, str] = {
    "Catalogs": "Справочник",
    "Documents": "Документ",
    "Enums": "Перечисление",
    "ChartsOfCharacteristicTypes": "ПланВидовХарактеристик",
    "ChartsOfAccounts": "ПланСчетов",
    "ChartsOfCalculationTypes": "ПланВидовРасчета",
    "ExchangePlans": "ПланОбмена",
    "BusinessProcesses": "БизнесПроцесс",
    "Tasks": "Задача",
    "InformationRegisters": "РегистрСведений",
    "AccumulationRegisters": "РегистрНакопления",
    "AccountingRegisters": "РегистрБухгалтерии",
    "CalculationRegisters": "РегистрРасчета",
    "Constants": "Константа",
    "DocumentJournals": "ЖурналДокументов",
}

# Виртуальные таблицы: написание (нижний регистр, оба языка) -> каноническое имя.
_VT_CANON: dict[str, str] = {
    "остатки": "Остатки",
    "balance": "Остатки",
    "обороты": "Обороты",
    "turnovers": "Обороты",
    "остаткииобороты": "ОстаткиИОбороты",
    "balanceandturnovers": "ОстаткиИОбороты",
    "срезпервых": "СрезПервых",
    "slicefirst": "СрезПервых",
    "срезпоследних": "СрезПоследних",
    "slicelast": "СрезПоследних",
    "изменения": "Изменения",
    "changes": "Изменения",
    "движенияссубконто": "ДвиженияССубконто",
    "recordswithextdimensions": "ДвиженияССубконто",
    "оборотыдткт": "ОборотыДтКт",
    "drcrturnovers": "ОборотыДтКт",
}

# Закрытый список виртуальных таблиц по виду регистра.
_VT_ALLOWED: dict[str, tuple[str, ...]] = {
    "InformationRegisters": ("СрезПервых", "СрезПоследних", "Изменения"),
    "AccumulationRegisters": ("Остатки", "Обороты", "ОстаткиИОбороты", "Изменения"),
    "AccountingRegisters": (
        "Остатки",
        "Обороты",
        "ОстаткиИОбороты",
        "ДвиженияССубконто",
        "ОборотыДтКт",
        "Изменения",
    ),
}

# Категории, у которых третья часть в позиции таблицы — табличная часть.
_TS_CATEGORIES = frozenset({"Catalogs", "Documents", "ChartsOfCharacteristicTypes"})

# Категории, у которых состав полей индексируется и проверяется.
FIELDS_CHECKED = frozenset(
    {"Catalogs", "Documents", "ChartsOfCharacteristicTypes", "InformationRegisters", "AccumulationRegisters"}
)

_RES_SUFFIX_BALANCE = ("остаток", "balance")
_RES_SUFFIX_TURNOVER = ("оборот", "приход", "расход", "turnover", "receipt", "expense")
_RES_SUFFIX_OPENING = ("начальныйостаток", "конечныйостаток", "openingbalance", "closingbalance")

_REG_STD = frozenset(
    {
        "период",
        "period",
        "регистратор",
        "recorder",
        "номерстроки",
        "linenumber",
        "активность",
        "active",
        "виддвижения",
        "recordtype",
    }
)
_VT_EXTRA = _REG_STD | frozenset(
    {
        f"период{p}"
        for p in ("секунда", "минута", "час", "день", "неделя", "декада", "месяц", "квартал", "полугодие", "год")
    }
    | {
        f"period{p}"
        for p in ("second", "minute", "hour", "day", "week", "tendays", "month", "quarter", "halfyear", "year")
    }
)

_CATALOG_STD = frozenset(
    {
        "ссылка",
        "ref",
        "пометкаудаления",
        "deletionmark",
        "владелец",
        "owner",
        "родитель",
        "parent",
        "код",
        "code",
        "наименование",
        "description",
        "этогруппа",
        "isfolder",
        "предопределенный",
        "predefined",
        "имяпредопределенныхданных",
        "predefineddataname",
        "версияданных",
        "dataversion",
        "представление",
        "presentation",
    }
)
_STD_ATTRS: dict[str, frozenset[str]] = {
    "Catalogs": _CATALOG_STD,
    "ChartsOfCharacteristicTypes": _CATALOG_STD | {"типзначения", "valuetype"},
    "Documents": frozenset(
        {
            "ссылка",
            "ref",
            "пометкаудаления",
            "deletionmark",
            "дата",
            "date",
            "номер",
            "number",
            "проведен",
            "posted",
            "версияданных",
            "dataversion",
            "представление",
            "presentation",
        }
    ),
    "InformationRegisters": _REG_STD,
    "AccumulationRegisters": _REG_STD,
}
_TS_STD = frozenset({"ссылка", "ref", "номерстроки", "linenumber"})

# Ключевые слова: не могут быть ни псевдонимом, ни именем таблицы.
_KEYWORDS = frozenset(
    """
    выбрать select из from соединение join как as поместить into объединить union
    где where сгруппировать group упорядочить order по by имеющие having левое left
    правое right внутреннее inner полное full внешнее outer разрешенные allowed
    различные distinct первые top все all для for изменения update итоги totals
    индексировать index автоупорядочивание autoorder уничтожить drop и and или or не not
    в in между between подобно like есть is null истина true ложь false когда when
    тогда then иначе else конец end выбор case
    """.split()
)
# Ключевые слова, после которых список источников ИЗ закончился.
_FROM_END = frozenset(
    "где where сгруппировать group упорядочить order имеющие having итоги totals для for "
    "индексировать index автоупорядочивание autoorder объединить union".split()
)
_SELECT_KW = frozenset({"выбрать", "select"})
_FROM_KW = frozenset({"из", "from"})
_JOIN_KW = frozenset({"соединение", "join"})
_INTO_KW = frozenset({"поместить", "into"})
_AS_KW = frozenset({"как", "as"})

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<comment>//[^\n]*)
  | (?P<str>"(?:[^"]|"")*"?)
  | (?P<param>&\w+)
  | (?P<dyn>[\#%]\w+|\w+\?)
  | (?P<word>\w+)
  | (?P<punct>.)
    """,
    re.X | re.S,
)


# ---------------------------------------------------------------------------
# Интерфейс к метаданным
# ---------------------------------------------------------------------------


@dataclass
class ObjInfo:
    """Что вызывающий знает об объекте метаданных."""

    category: str
    name: str  # каноническое написание
    owner: str = "main"
    tabular_sections: list[str] = field(default_factory=list)
    ts_known: bool = False
    reg: dict = field(default_factory=dict)  # periodicity / registerType / ...
    # нижний регистр -> (каноническое имя, вид: attribute|dimension|resource)
    fields: dict[str, tuple[str, str]] = field(default_factory=dict)
    # нижний регистр ТЧ -> {нижний регистр реквизита -> имя}
    ts_fields: dict[str, dict[str, str]] = field(default_factory=dict)
    fields_known: bool = True
    # нижний регистр поля -> владелец, если он отличается от владельца объекта
    # (реквизит расширения к объекту основной конфигурации); стандартные — владелец объекта
    field_owner: dict[str, str] = field(default_factory=dict)


@dataclass
class QueryEnv:
    lookup: Callable[[str, str], "ObjInfo | None"]
    names: Callable[[str], list[str]]
    uncertain: bool = False  # индекс неполон: «нет объекта» — неуверенное замечание
    # Имена общих реквизитов (нижний регистр): поле с таким именем допустимо у ЛЮБОГО объекта
    # (надмножество: к каким объектам реквизит применяется, не разбирается)
    common_fields: frozenset = frozenset()


@dataclass
class QueryCheck:
    findings: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    tables: int = 0
    objects: int = 0
    aliases: int = 0
    fields: int = 0
    by_owner: dict[str, int] = field(default_factory=dict)  # проверенные поля по владельцам


# ---------------------------------------------------------------------------
# Токенизация и разбор
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[tuple[str, str, int]]:
    toks: list[tuple[str, str, int]] = []
    line = 0
    pos = 0
    n = len(text)
    while pos < n:
        m = _TOKEN_RE.match(text, pos)
        if m is None:  # недостижимо: punct берёт любой символ
            pos += 1
            continue
        kind = m.lastgroup or "punct"
        chunk = m.group()
        if kind == "ws" or kind == "comment":
            pass
        else:
            toks.append((kind, chunk, line))
        line += chunk.count("\n")
        pos = m.end()
    return toks


def _is_ident(text: str) -> bool:
    return bool(text) and not text[0].isdigit()


@dataclass
class _Source:
    kind: str  # meta | temp | subquery | param
    name: str  # temp/param: имя; meta: имя объекта
    category: str = ""
    third: str = ""
    alias: str = ""
    line: int = 0
    kind_text: str = ""  # префикс, как написан в запросе
    depth0: int = 0
    params_seen: bool = False
    alias_expected: bool = False


@dataclass
class _Ref:
    head: str  # первая часть (псевдоним или префикс вида)
    name: str  # вторая часть
    line: int


class _Block:
    """Один ``ВЫБРАТЬ``: его источники, ссылки ``Псевдоним.Поле`` и родитель (внешний запрос)."""

    __slots__ = ("depth", "parent", "sources", "source_list", "refs", "from_active", "expect_source")

    def __init__(self, depth: int, parent: "_Block | None") -> None:
        self.depth = depth
        self.parent = parent
        self.sources: dict[str, _Source] = {}
        self.source_list: list[_Source] = []
        self.refs: list[_Ref] = []
        self.from_active = False
        self.expect_source = False


def _parse(text: str) -> "tuple[list[_Block], set[str]]":
    """Разбор текста. Возвращает (блоки, псевдонимы, объявленные через ``КАК`` где угодно)."""
    toks = _tokenize(text)
    # `ИЗ #ИмяТаблицы КАК ПланОбмена` — источник нераспознан, а псевдоним есть: без этого
    # `ПланОбмена.Ссылка` принимается за объект метаданных. Слово после КАК, за которым идёт
    # точка (`ВЫРАЗИТЬ(Х КАК Справочник.Y)`), псевдонимом не считается.
    declared: set[str] = set()
    for k in range(len(toks) - 1):
        if (
            toks[k][0] == "word"
            and toks[k][1].lower() in _AS_KW
            and toks[k + 1][0] == "word"
            and not (k + 2 < len(toks) and toks[k + 2][1] == ".")
        ):
            declared.add(toks[k + 1][1].lower())
    blocks: list[_Block] = []
    root = _Block(-1, None)
    blocks.append(root)
    stack: list[_Block] = []
    depth = 0
    # Источники, у которых ещё не решён псевдоним. СТЕК, а не одна переменная: у
    # вложенного запроса (`ИЗ (ВЫБРАТЬ ... ИЗ Т) КАК П`) внутренний источник иначе затёр бы
    # внешний, и псевдоним подзапроса терялся.
    pend: list[tuple[_Source, _Block]] = []
    n = len(toks)
    i = 0

    def finalize(alias_text: str | None) -> None:
        src, blk = pend.pop()
        alias = alias_text
        if alias is None:
            if src.kind == "meta":
                alias = src.third or src.name
            elif src.kind == "temp":
                alias = src.name
            else:
                alias = ""
        src.alias = alias or ""
        blk.source_list.append(src)
        if src.alias:
            blk.sources[src.alias.lower()] = src

    while i < n:
        kind, text_i, line = toks[i]
        low = text_i.lower()
        cur = stack[-1] if stack else root

        # --- ожидающий источник: решаем про псевдоним, когда вернулись на его глубину
        pending = pend[-1][0] if pend else None
        if pending is not None and depth == pending.depth0:
            if kind == "punct" and text_i == "(" and pending.kind == "meta" and not pending.params_seen:
                pending.params_seen = True  # параметры виртуальной таблицы — обычная обработка ниже
            elif kind == "word" and low in _AS_KW and not pending.alias_expected:
                pending.alias_expected = True
                i += 1
                continue
            elif kind == "word" and pending.alias_expected and _is_ident(text_i):
                finalize(text_i)
                i += 1
                continue
            elif kind == "word" and low not in _KEYWORDS and _is_ident(text_i) and not pending.alias_expected:
                finalize(text_i)
                i += 1
                continue
            else:
                finalize(None)
                cur = stack[-1] if stack else root

        # --- начало источника
        if cur.expect_source and depth == cur.depth:
            if kind == "punct" and text_i == "(":
                cur.expect_source = False
                pend.append((_Source(kind="subquery", name="", line=line, depth0=depth, params_seen=True), cur))
                depth += 1
                i += 1
                continue
            if kind in ("param", "dyn"):
                # параметр или подстановка времени выполнения (`#Имя`, `Имя?`, `%1`): источник
                # неизвестен, но псевдоним у него есть
                cur.expect_source = False
                pend.append((_Source(kind="param", name=text_i, line=line, depth0=depth), cur))
                i += 1
                continue
            if kind == "word" and _is_ident(text_i):
                if low in KIND_PREFIX and i + 2 < n and toks[i + 1][1] == "." and toks[i + 2][0] in ("word", "dyn"):
                    cur.expect_source = False
                    src = _Source(
                        kind="meta",
                        name=toks[i + 2][1],
                        category=KIND_PREFIX[low],
                        kind_text=text_i,
                        line=line,
                        depth0=depth,
                    )
                    j = i + 3
                    if toks[i + 2][0] == "dyn":
                        src.kind = "param"  # имя объекта подставляется при выполнении
                    if j + 1 < n and toks[j][1] == "." and toks[j + 1][0] in ("word", "dyn"):
                        if toks[j + 1][0] == "dyn":
                            src.kind = "param"  # ТЧ/виртуальная таблица подставляется при выполнении
                        else:
                            src.third = toks[j + 1][1]
                        j += 2
                    pend.append((src, cur))
                    i = j
                    continue
                if low not in _KEYWORDS:
                    cur.expect_source = False
                    pend.append((_Source(kind="temp", name=text_i, line=line, depth0=depth), cur))
                    i += 1
                    continue
            cur.expect_source = False  # токен не начинает источник — не ждём его дальше

        # --- обычная обработка токена
        if kind == "punct":
            if text_i == "(":
                depth += 1
            elif text_i == ")":
                depth -= 1
                while stack and stack[-1].depth > depth:
                    stack.pop()
            elif text_i == ";":
                while pend:
                    finalize(None)
                stack.clear()
                depth = 0
            elif (
                text_i == ","
                and stack
                and stack[-1].depth == depth
                and stack[-1].from_active
                and not (pend and pend[-1][0].depth0 == depth)
            ):
                stack[-1].expect_source = True
        elif kind == "word":
            if low in _SELECT_KW:
                while stack and stack[-1].depth >= depth:
                    stack.pop()
                blk = _Block(depth, stack[-1] if stack else None)
                blocks.append(blk)
                stack.append(blk)
            elif low in _FROM_KW and stack and stack[-1].depth == depth:
                stack[-1].from_active = True
                stack[-1].expect_source = True
            elif low in _JOIN_KW and stack and stack[-1].depth == depth:
                stack[-1].from_active = True
                stack[-1].expect_source = True
            elif low in _FROM_END and stack and stack[-1].depth == depth:
                stack[-1].from_active = False
            elif low in _INTO_KW and stack and stack[-1].depth == depth:
                i += 2 if i + 1 < n and toks[i + 1][0] == "word" else 1
                continue
            elif (
                _is_ident(text_i)
                and i + 2 < n
                and toks[i + 1][1] == "."
                and toks[i + 2][0] == "word"
                and not (i > 0 and toks[i - 1][1] == ".")
            ):
                cur.refs.append(_Ref(head=text_i, name=toks[i + 2][1], line=line))
        i += 1

    while pend:
        finalize(None)
    return blocks, declared


# ---------------------------------------------------------------------------
# Сверка
# ---------------------------------------------------------------------------


def _close(name: str, candidates: list[str], n: int = 3) -> list[str]:
    if not candidates:
        return []
    by_lower = {c.lower(): c for c in candidates}
    hits = difflib.get_close_matches(name.lower(), list(by_lower), n=n, cutoff=0.6)
    return [by_lower[h] for h in hits]


def _vt_fields(info: ObjInfo, vt: str) -> "tuple[set[str], list[str]] | None":
    """Допустимые (нижний регистр) поля виртуальной таблицы; None — не разбирается."""
    cat = info.category
    dims = {k: v for k, v in info.fields.items() if v[1] == "dimension"}
    res = {k: v for k, v in info.fields.items() if v[1] == "resource"}
    names = [v[0] for v in info.fields.values()]
    if cat == "InformationRegisters":
        if vt in ("СрезПервых", "СрезПоследних"):
            allowed = set(info.fields) | _REG_STD
            return allowed, names
        return None
    if cat == "AccumulationRegisters":
        allowed = set(dims)
        if vt == "Остатки":
            suffixes = _RES_SUFFIX_BALANCE
        elif vt == "Обороты":
            suffixes = _RES_SUFFIX_TURNOVER
            allowed |= _VT_EXTRA
        elif vt == "ОстаткиИОбороты":
            suffixes = _RES_SUFFIX_TURNOVER + _RES_SUFFIX_OPENING + _RES_SUFFIX_BALANCE
            allowed |= _VT_EXTRA
        else:
            return None
        for rk in res:
            for suf in suffixes:
                allowed.add(rk + suf)
        return allowed, names + [f"{v[0]}{s}" for v in res.values() for s in ("Остаток", "Оборот", "Приход", "Расход")]
    return None


class _Checker:
    def __init__(self, env: QueryEnv, base_line: int, query_index: int) -> None:
        self.env = env
        self.base_line = base_line
        self.query_index = query_index
        self.out = QueryCheck()
        self._declared: set[str] = set()
        self._obj_cache: dict[tuple[str, str], "ObjInfo | None"] = {}
        self._reported: set[tuple] = set()
        self._tables_seen: set[str] = set()
        self._objects_seen: set[str] = set()
        self._fields_seen: set[tuple[str, str]] = set()
        self._skip_seen: set[tuple] = set()

    # --- служебное
    def _lookup(self, category: str, name: str) -> "ObjInfo | None":
        key = (category, name.lower())
        if key not in self._obj_cache:
            self._obj_cache[key] = self.env.lookup(category, name)
        return self._obj_cache[key]

    def _line(self, rel: int) -> int:
        return self.base_line + rel

    def _finding(self, kind: str, *, obj: str, table: str, alias: str, field_: str, line: int, owner, message: str):
        key = (kind, table.lower(), field_.lower())
        if key in self._reported:
            return
        self._reported.add(key)
        self.out.findings.append(
            {
                "kind": kind,
                "severity": "warning" if (self.env.uncertain and kind != "missing_field") else "error",
                "object": obj,
                "table": table,
                "alias": alias,
                "field": field_,
                "line": self._line(line),
                "query_index": self.query_index,
                "owner": owner,
                "message": message,
                "uncertain": bool(self.env.uncertain and kind != "missing_field"),
            }
        )

    def _skip(self, reason: str, target: str, line: int, field_: str = "") -> None:
        key = (reason, target.lower(), field_.lower())
        if key in self._skip_seen:
            return
        self._skip_seen.add(key)
        self.out.skipped.append(
            {
                "reason": reason,
                "alias_or_table": target,
                "field": field_,
                "line": self._line(line),
                "query_index": self.query_index,
            }
        )

    # --- объект
    def _check_object(self, category: str, name: str, kind_text: str, line: int) -> "ObjInfo | None":
        shown = f"{kind_text}.{name}"
        info = self._lookup(category, name)
        if info is None:
            self._finding(
                "missing_object",
                obj=shown,
                table=shown,
                alias="",
                field_="",
                line=line,
                owner=None,
                message=self._missing_object_message(category, name, shown),
            )
        return info

    def _missing_object_message(self, category: str, name: str, shown: str) -> str:
        close = _close(name, self.env.names(category))
        msg = f"Объект «{shown}» не найден в конфигурации."
        if close:
            msg += " Ближайшие имена: " + ", ".join(close) + "."
        if self.env.uncertain:
            msg += " Индекс неполон, замечание неуверенное."
        return msg

    def _check_source(self, src: _Source) -> "tuple[ObjInfo | None, str, str]":
        """Проверить метаисточник. Возвращает (info, виртуальная таблица|'', статус).

        Статус: ok | missing_object | bad_third | opaque_third.
        """
        shown_obj = f"{src.kind_text}.{src.name}"
        full = shown_obj + (f".{src.third}" if src.third else "")
        first_time = full.lower() not in self._tables_seen
        self._tables_seen.add(full.lower())
        if first_time:
            self.out.tables += 1
        info = self._check_object(src.category, src.name, src.kind_text, src.line)
        if info is None:
            return None, "", "missing_object"
        if not src.third:
            return info, "", "ok"
        third_l = src.third.lower()
        cat = src.category
        vt = _VT_CANON.get(third_l, "")
        if cat in _TS_CATEGORIES:
            if vt == "Изменения":
                return info, "Изменения", "ok"
            if not info.ts_known:
                return info, "", "opaque_third"
            if third_l in {t.lower() for t in info.tabular_sections}:
                return info, "", "ok"
            close = _close(src.third, info.tabular_sections)
            msg = f"Табличная часть «{src.third}» не найдена у {shown_obj}."
            if close:
                msg += " Ближайшие имена: " + ", ".join(close) + "."
            self._finding(
                "missing_tabular_section",
                obj=shown_obj,
                table=full,
                alias=src.alias,
                field_=src.third,
                line=src.line,
                owner=info.owner,
                message=msg,
            )
            return info, "", "bad_third"
        allowed = _VT_ALLOWED.get(cat)
        if allowed is None:
            return info, "", "opaque_third"
        problem = ""
        if vt not in allowed:
            problem = f"Виртуальной таблицы «{src.third}» у {shown_obj} нет. Допустимы: " + ", ".join(allowed) + "."
        elif cat == "AccumulationRegisters" and vt in ("Остатки", "ОстаткиИОбороты"):
            if info.reg.get("registerType") == "Turnovers":
                problem = f"Регистр {shown_obj} — регистр оборотов, виртуальной таблицы «{src.third}» у него нет."
        elif cat == "InformationRegisters" and vt in ("СрезПервых", "СрезПоследних"):
            if info.reg.get("periodicity") == "Nonperiodical":
                problem = f"Регистр {shown_obj} непериодический, срезов у него нет."
        if problem:
            self._finding(
                "missing_virtual_table",
                obj=shown_obj,
                table=full,
                alias=src.alias,
                field_=src.third,
                line=src.line,
                owner=info.owner,
                message=problem,
            )
            return info, vt, "bad_third"
        return info, vt, "ok"

    # --- поле
    def _check_field(self, src: _Source, info: ObjInfo, vt: str, ref: _Ref, third_status: str) -> None:
        cat = info.category
        alias = ref.head
        table_text = f"{src.kind_text}.{src.name}" + (f".{src.third}" if src.third else "")
        if third_status != "ok":
            return  # таблица уже названа ошибкой или не разбирается — поля отдельно не ругаем
        if cat not in FIELDS_CHECKED or not info.fields_known:
            self._skip("состав полей категории не индексируется", alias, ref.line, ref.name)
            return
        fl = ref.name.lower()
        allowed: set[str]
        candidates: list[str]
        if vt == "Изменения":
            self._skip("таблица изменений не разбирается", alias, ref.line, ref.name)
            return
        if vt:
            got = _vt_fields(info, vt)
            if got is None:
                self._skip("поля виртуальной таблицы не разбираются", alias, ref.line, ref.name)
                return
            allowed, candidates = got
            allowed = allowed | self.env.common_fields
        elif src.third and cat in _TS_CATEGORIES:
            ts_map = info.ts_fields.get(src.third.lower(), {})
            allowed = set(ts_map) | _TS_STD
            candidates = list(ts_map.values())
        else:
            allowed = set(info.fields) | {t.lower() for t in info.tabular_sections} | _STD_ATTRS.get(cat, frozenset())
            allowed |= self.env.common_fields
            candidates = [v[0] for v in info.fields.values()] + list(info.tabular_sections)
        key = (alias.lower(), fl)
        if key not in self._fields_seen:
            self._fields_seen.add(key)
            self.out.fields += 1
            if fl in allowed:
                owner = info.field_owner.get(fl, info.owner)
                self.out.by_owner[owner] = self.out.by_owner.get(owner, 0) + 1
        if fl in allowed:
            return
        close = _close(ref.name, candidates)
        msg = f"Поле «{ref.name}» не найдено в таблице {table_text}."
        if close:
            msg += " Ближайшие имена: " + ", ".join(close) + "."
        self._finding(
            "missing_field",
            obj=f"{src.kind_text}.{src.name}",
            table=table_text,
            alias=alias,
            field_=ref.name,
            line=ref.line,
            owner=info.owner,
            message=msg,
        )

    # --- запуск
    def run(self, text: str) -> QueryCheck:
        blocks, self._declared = _parse(text)
        resolved: dict[int, tuple] = {}  # id(source) -> (info, vt, status)
        for blk in blocks:
            for src in blk.source_list:
                if src.kind != "meta":
                    continue
                resolved[id(src)] = self._check_source(src)
                self.out.aliases += 1
        for blk in blocks:
            for ref in blk.refs:
                self._check_ref(blk, ref, resolved)
        return self.out

    def _find_alias(self, blk: _Block, alias: str) -> "_Source | None":
        b: "_Block | None" = blk
        key = alias.lower()
        while b is not None:
            src = b.sources.get(key)
            if src is not None:
                return src
            b = b.parent
        return None

    def _check_ref(self, blk: _Block, ref: _Ref, resolved: dict) -> None:
        src = self._find_alias(blk, ref.head)
        if src is not None:
            if src.kind == "meta":
                info, vt, status = resolved.get(id(src), (None, "", "missing_object"))
                if info is None:
                    return  # объект уже назван отсутствующим — поля отдельно не ругаем
                self._check_field(src, info, vt, ref, status)
            elif src.kind == "temp":
                self._skip("временная таблица", ref.head, ref.line, ref.name)
            elif src.kind == "subquery":
                self._skip("вложенный запрос", ref.head, ref.line, ref.name)
            else:
                self._skip("параметр запроса", ref.head, ref.line, ref.name)
            return
        category = KIND_PREFIX.get(ref.head.lower())
        if category is not None and ref.head.lower() not in self._declared:
            key = f"{category}.{ref.name}".lower()
            if key not in self._objects_seen:
                self._objects_seen.add(key)
                self.out.objects += 1
            self._check_object(category, ref.name, ref.head, ref.line)
            return
        self._skip("неизвестный псевдоним", ref.head, ref.line, ref.name)


def check_query(text: str, env: QueryEnv, *, base_line: int = 1, query_index: int = 0) -> QueryCheck:
    """Проверить один текст запроса (пакет запросов допустим).

    ``base_line`` — номер строки модуля (или текста), которой соответствует первая строка
    запроса; ``line`` в находках считается от неё.
    """
    return _Checker(env, base_line, query_index).run(text)
