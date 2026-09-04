"""Compiler 3.0 entry point with final Registry-v3 normalization."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, cast

from enocean_mqtt.eep.generator.semantic_mapping import normalize_boolean_bindings

Json = dict[str, Any]
_CORE_PATH = Path(__file__).with_name("compile_eep_core.py")
_SPEC = importlib.util.spec_from_file_location("enocean_mqtt_compile_eep_core", _CORE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Cannot load compiler core from {_CORE_PATH}")
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
_core = cast(Any, _MODULE)
_CORE_COMPILE_EEP = _core.compile_eep
_COMPILER_DIAGNOSTIC = re.compile(r"^(?:WARNING|ERROR) [A-Z0-9-]+ [A-Z0-9_]+(?: |$)")

for _name in dir(_core):
    if not _name.startswith("__") and _name not in globals():
        globals()[_name] = getattr(_core, _name)


def _finalize_compiled_registry(output_file: Path, issues: list[str]) -> list[str]:
    """Normalize the fully merged registry and return fresh validation issues."""

    definition: Json = json.loads(output_file.read_text(encoding="utf-8"))
    normalize_boolean_bindings(definition)
    output_file.write_text(
        json.dumps(
            _core.ordered_dict(definition, _core.TOP_LEVEL_ORDER),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    compiler_diagnostics = [
        issue for issue in issues if _COMPILER_DIAGNOSTIC.match(issue)
    ]
    return [*_core.validate_eep_definition(definition), *compiler_diagnostics]


def compile_eep(
    xml_path: Path,
    eep_id: str,
    output_dir: Path,
    ip_json_path: Path | None,
    semantic_mapping_path: Path,
    eep_list_path: Path,
) -> tuple[Path, list[str]]:
    """Compile one EEP and normalize booleans after all merge stages."""

    output_file, issues = _CORE_COMPILE_EEP(
        xml_path,
        eep_id,
        output_dir,
        ip_json_path,
        semantic_mapping_path,
        eep_list_path,
    )
    return output_file, _finalize_compiled_registry(output_file, issues)


def main() -> None:
    """Run the existing CLI with the finalized compiler function."""

    original = _core.compile_eep
    _core.compile_eep = compile_eep
    try:
        _core.main()
    finally:
        _core.compile_eep = original


if __name__ == "__main__":
    main()
