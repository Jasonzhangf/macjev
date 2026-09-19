"""Load and validate labelled evaluation rows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class DatasetError(ValueError):
    """The evaluation dataset violates its declared contract."""


SPLITS = {"calibration", "test", "ood"}
TYPES = {"noul", "choice", "score"}


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise DatasetError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise DatasetError(f"{path}:{line_number}: row must be an object")
        row_id = row.get("id")
        if not isinstance(row_id, str) or not row_id:
            raise DatasetError(f"{path}:{line_number}: id must be non-empty")
        if row_id in seen:
            raise DatasetError(f"{path}:{line_number}: duplicate id {row_id!r}")
        seen.add(row_id)
        if row.get("split") not in SPLITS:
            raise DatasetError(f"{path}:{line_number}: invalid split")
        if row.get("type") not in TYPES:
            raise DatasetError(f"{path}:{line_number}: invalid type")
        if not isinstance(row.get("cardinality"), int) or row["cardinality"] < 2:
            raise DatasetError(f"{path}:{line_number}: invalid cardinality")
        if "state" not in row:
            raise DatasetError(f"{path}:{line_number}: state is required")
        if not isinstance(row.get("question"), dict):
            raise DatasetError(f"{path}:{line_number}: question must be an object")
        if "label" not in row:
            raise DatasetError(f"{path}:{line_number}: label is required")
        if not isinstance(row.get("source"), str) or not row["source"]:
            raise DatasetError(f"{path}:{line_number}: source must be non-empty")
        if not isinstance(row.get("scenario"), str) or not row["scenario"]:
            raise DatasetError(f"{path}:{line_number}: scenario must be non-empty")
        rows.append(row)
    if not rows:
        raise DatasetError(f"{path}: dataset is empty")
    return rows
