from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SchemaConversionResult:
    parameters: dict[str, object] | None
    required: list[str]
    warnings: tuple[str, ...] = ()


def convert_input_schema(raw_schema: object) -> SchemaConversionResult:
    warnings: list[str] = []
    if raw_schema is None:
        raw_schema = {}
    if not isinstance(raw_schema, dict):
        return SchemaConversionResult(parameters=None, required=[], warnings=("MCP inputSchema must be an object.",))

    schema = dict(raw_schema)
    schema_type = schema.get("type", "object")
    if schema_type != "object":
        warnings.append(f"Unsupported MCP inputSchema type '{schema_type}'; treating as object.")

    properties = schema.get("properties", {})
    if properties is None:
        properties = {}
    if not isinstance(properties, dict):
        return SchemaConversionResult(parameters=None, required=[], warnings=("MCP inputSchema properties must be an object.",))

    required_raw = schema.get("required", [])
    if required_raw is None:
        required: list[str] = []
    elif isinstance(required_raw, list) and all(isinstance(item, str) for item in required_raw):
        required = list(required_raw)
    else:
        required = []
        warnings.append("MCP inputSchema required must be a string array; clearing required.")

    try:
        json.dumps(properties)
    except (TypeError, ValueError):
        return SchemaConversionResult(parameters=None, required=[], warnings=("MCP inputSchema properties are not JSON serializable.",))

    return SchemaConversionResult(parameters=dict(properties), required=required, warnings=tuple(warnings))
