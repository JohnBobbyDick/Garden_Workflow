"""Vulnerability snapshot loader (organizer JSON format), validated against its JSON Schema."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import jsonschema

DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "vulndb" / "vulnerabilities.json"
DEFAULT_SCHEMA_PATH = DEFAULT_DB_PATH.with_name("schema.json")


class VulnDBError(ValueError):
    pass


@dataclass
class VulnDB:
    data: dict
    index: dict[tuple[str, str], list[dict]]
    source: str

    @classmethod
    def load(cls, path: str | Path = DEFAULT_DB_PATH, schema_path: str | Path = DEFAULT_SCHEMA_PATH) -> VulnDB:
        path = Path(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VulnDBError(f"cannot read vulnerability database {path.name}: {exc}") from exc
        return cls.from_data(data, schema_path, str(path.name))

    @classmethod
    def from_data(cls, data: dict, schema_path: str | Path = DEFAULT_SCHEMA_PATH, source: str = "inline") -> VulnDB:
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        try:
            jsonschema.validate(data, schema)
        except jsonschema.ValidationError as exc:
            loc = "/".join(str(p) for p in exc.absolute_path)
            raise VulnDBError(f"vulnerability database does not match schema at '{loc}': {exc.message}") from exc
        index: dict[tuple[str, str], list[dict]] = {}
        for entry in data["vulnerabilities"]:
            index.setdefault((entry["group"], entry["artifact"]), []).append(entry)
        return cls(data, index, source)

    def entries_for(self, group: str, artifact: str) -> list[dict]:
        return self.index.get((group, artifact), [])

    def all_ids(self) -> set[str]:
        out: set[str] = set()
        for entries in self.index.values():
            for e in entries:
                out.add(e["id"])
                out.update(e.get("aliases", []))
        return out
