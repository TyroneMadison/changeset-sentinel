from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sentinel.changeset import ChangeSet, load_changeset, parse_changeset

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = ROOT / "examples" / "scenarios"


def scenario(name: str) -> ChangeSet:
    return load_changeset(SCENARIOS / name / "changeset.json")


def resource_change(**overrides: Any) -> dict[str, Any]:
    rc = {
        "Action": "Modify",
        "LogicalResourceId": "Thing",
        "PhysicalResourceId": "thing-123",
        "ResourceType": "AWS::Lambda::Function",
        "Replacement": "False",
        "Scope": ["Properties"],
        "Details": [
            {
                "Target": {
                    "Attribute": "Properties",
                    "Name": "Timeout",
                    "RequiresRecreation": "Never",
                },
                "Evaluation": "Static",
                "ChangeSource": "DirectModification",
            }
        ],
    }
    rc.update(overrides)
    return {"Type": "Resource", "ResourceChange": rc}


def changeset_of(*changes: dict[str, Any]) -> ChangeSet:
    return parse_changeset(
        {
            "StackName": "unit-stack",
            "ChangeSetName": "unit-cs",
            "Status": "CREATE_COMPLETE",
            "ExecutionStatus": "AVAILABLE",
            "Changes": list(changes),
        }
    )


@pytest.fixture
def scenarios_dir() -> Path:
    return SCENARIOS


@pytest.fixture
def raw_scenario() -> Any:
    def _load(name: str) -> dict[str, Any]:
        return json.loads((SCENARIOS / name / "changeset.json").read_text(encoding="utf-8"))

    return _load
