"""Generate docs/NODES.md from the live node registry (the doc cannot drift from the code).

Usage (from backend/): ``python ../scripts/gen_nodes_doc.py``"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.api.nodes import CATEGORY_TITLES  # noqa: E402
from app.nodes.base import get_registry  # noqa: E402

INTRO = """# Ноды AI Security Workflow

> Файл сгенерирован `scripts/gen_nodes_doc.py` из реестра нод (`make nodes-doc`). Не редактируйте вручную.

## Как устроены ноды

Нода — один класс-плагин в одном файле внутри `backend/app/nodes/**`, помеченный `@register_node`. Реестр находит
модули автоматически; движок, API (`GET /api/nodes`) и редактор (форма строится из `config_schema`) менять не нужно.

```python
from app.nodes.base import BaseNode, Envelope, Port, register_node
from app.nodes.schema import obj, prop


@register_node
class Shout(BaseNode):
    type = "logic.shout"
    category = "logic"
    title = {"ru": "Крик", "en": "Shout"}
    description = {"ru": "Переводит текст в верхний регистр", "en": "Upper-cases text"}
    inputs = [Port("in", "text")]
    outputs = [Port("out", "text")]
    config_schema = obj({"suffix": prop("string", "Суффикс", "Suffix", default="!")})

    async def execute(self, ctx, inputs, config):
        text = inputs["in"].data["text"].upper() + config["suffix"]
        return {"out": Envelope.make("text", {"text": text}, ctx.node_id, "готово")}
```

### Пользовательские ноды

В палитре редактора откройте «Ноды» → «Создать ноду». Введите название и добавьте поля результата.
Для каждого укажите путь во входном JSON или условие с префиксом `=`. Например, после группировки по критичности
поле `high` с путём `counts.HIGH` получит число, а поле `review` с условием `=counts.HIGH > 0` получит
логическое значение. Путь к отсутствующему полю, объекту или массиву даёт `null`.

После сохранения нода появляется в группе «Ноды пространства». Администратор и разработчик могут создавать
определения, все участники могут просматривать библиотеку. При добавлении на холст граф получает название
и собственную копию правил. Это позволяет экспортировать сценарий и запускать его в другом пространстве.

### Данные между нодами

Каждое ребро передаёт конверт `Envelope`:

```json
{"type": "findings", "data": {"findings": [...]}, "meta": {"node_id": "sast", "produced_at": "…", "summary": "найдено 5"}}
```

| Тип порта | Содержимое `data` |
|---|---|
| `trigger` | параметры запуска: `trigger_type`, `source` (переопределение источника из CI/вебхука), событие |
| `repo` | `root` (рабочая копия), `files`, `loc`, `source` (`mode`, `url`, `ref`, `commit`), `project_name`, `diff_context` |
| `findings` | `findings[]` — единая модель `Finding` (секреты только маскированные) |
| `report` | `artifacts[]` (имя, ссылка, тип), `summary`, `exported` |
| `json` | произвольный объект (вердикт gate/diff, значения `set_value`, результат regex) |
| `text` | `text` |
| `bool` | `value` |
| `any` | принимает/отдаёт любой тип |

Совместимость: тип выхода должен совпадать с типом входа, `any` совместим со всем. Вход с `multiple` принимает
несколько рёбер (например, `logic.merge`). У IF/ELSE активна только одна ветка: невыбранная ветка и всё, что
зависит только от неё, получают статус `skipped`; нода-слияние ждёт только активные входы.

### Выражения `logic.if_else`

Собственный безопасный парсер (без `eval`): `findings.count`, `severity.max`, `severity.critical|high|medium|low`,
`category`/`categories`, `classes`, `new_findings.count`, `existing_findings.count`, `verdict`, `gate`,
`score.value`, `score.delta`, `data.<поле>` (JSON-входы). Операторы: `== != > >= < <= in contains`, `and or not`,
скобки. Уровни критичности сравниваются по рангу: `severity.max >= HIGH`.

### Шаблоны сообщений

`{{findings.count}}`, `{{severity.critical}}`, `{{new_findings.count}}`, `{{verdict}}`, `{{score.value}}`,
`{{score.delta}}`, `{{run.url}}`, `{{ai.summary}}`, `{{project.name}}`, `{{workflow.name}}` — только подстановка
значений из подготовленного контекста; значения секретов в контекст не попадают, результат дополнительно маскируется.
"""


def _type(p: dict) -> str:
    t = p.get("type", "")
    if t == "array" and isinstance(p.get("items"), dict):
        it = p["items"]
        inner = " / ".join(it["enum"]) if "enum" in it else it.get("type", "")
        return f"array<{inner}>"
    if "enum" in p:
        return " \\| ".join(str(x) for x in p["enum"])
    if p.get("credential_ref"):
        return "credential"
    return str(t)


def main() -> None:
    reg = get_registry()
    out = [INTRO, "## Каталог", ""]
    by_cat: dict[str, list] = {}
    for cls in reg.all():
        by_cat.setdefault(cls.category, []).append(cls)
    for cat, items in by_cat.items():
        out.append(f"- **{CATEGORY_TITLES[cat]['ru']}**: " + ", ".join(f"`{c.type}`" for c in items))
    out.append("")
    for cat, items in by_cat.items():
        out += [f"## {CATEGORY_TITLES[cat]['ru']}", ""]
        for cls in items:
            spec = cls.spec()
            out += [f"### `{spec['type']}` — {spec['title']['ru']}", "", spec["description"]["ru"], ""]
            if spec["inputs"] or spec["outputs"]:
                out += ["| Порт | Направление | Тип | Обязательный | Несколько |", "|---|---|---|---|---|"]
                for p in spec["inputs"]:
                    out.append(f"| `{p['name']}` ({p['title']['ru']}) | вход | `{p['type']}` | "
                               f"{'да' if p['required'] else 'нет'} | {'да' if p['multiple'] else 'нет'} |")
                for p in spec["outputs"]:
                    branch = " (ветка)" if p["name"] in spec["branch_outputs"] else ""
                    out.append(f"| `{p['name']}` ({p['title']['ru']}){branch} | выход | `{p['type']}` | — | — |")
                out.append("")
            props = spec["config_schema"].get("properties", {})
            required = set(spec["config_schema"].get("required", []))
            if props:
                out += ["| Параметр | Тип | По умолчанию | Описание |", "|---|---|---|---|"]
                for name, p in props.items():
                    default = json.dumps(p["default"], ensure_ascii=False) if "default" in p else ""
                    req = " **обязательный**" if name in required else ""
                    secret = " (ссылка на секрет хранилища)" if p.get("credential_ref") else ""
                    desc = (p.get("title", "") + (". " + p["description"] if p.get("description") else "")
                            + secret + req).replace("|", "\\|")
                    out.append(f"| `{name}` | {_type(p)} | {default.replace('|', chr(92) + '|')} | {desc} |")
                out.append("")
            else:
                out += ["Параметров нет.", ""]
    (ROOT / "docs" / "NODES.md").write_text("\n".join(out), encoding="utf-8")
    print(f"docs/NODES.md: {len(reg.all())} nodes")


if __name__ == "__main__":
    main()
