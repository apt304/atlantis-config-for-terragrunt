#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

import fileinput
import json
import pathlib
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import chain
from operator import contains
from typing import TypedDict

# USAGE:
#
# terragrunt find --json --dependencies --include | ./atlantis-config-for-terragrunt.py > atlantis.yaml


class AutoPlanDict(TypedDict):
    enabled: bool
    when_modified: Iterable[str]


class AtlantisProjectDict(TypedDict):
    autoplan: AutoPlanDict
    execution_order_group: int
    dir: str


class AtlantisConfigDict(TypedDict):
    version: int
    automerge: bool
    parallel_apply: bool
    parallel_plan: bool
    projects: Iterable[AtlantisProjectDict]


@dataclass
class Unit:
    type: str
    path: pathlib.PurePath
    include: list[pathlib.PurePath]
    dependencies: list[pathlib.PurePath]
    reading: list[pathlib.PurePath]
    execution_order_group: int | None

    def get_execution_order_group(self) -> int:
        """Calculate execution_order_group so atlantis know which units to apply first.

        If a unit has no dependencies, the order must be 1 (the first to be applied).
        For all of a given units' dependencies, a unit must have a group higher than its dependencies.

        Therefore, we can calculate this value out relatively easily by adding one to the highest value returned for all of the dependencies.
        """
        if self.execution_order_group:
            return self.execution_order_group

        if len(self.dependencies) == 0:
            self.execution_order_group = 1
            return self.execution_order_group

        computed_deps = [d.get_execution_order_group() for d in self.dependency_units()]
        if len(computed_deps) == 0:
            # max fails if len == 0. This only really happens if there's a broken dependency, and it's not in all_units
            computed_deps.append(0)
        self.execution_order_group = max(computed_deps) + 1
        return self.execution_order_group

    def get_when_modified(self) -> Iterable[str]:
        """Return a set of file patterns that, when modified, should trigger an autoplan."""
        out = {"*.tf*", "*.hcl"}
        for dep in chain(self.dependencies, self.include, self.reading):
            if dep.name == "root.hcl":
                continue
            out.add(str(dep.relative_to(self.path, walk_up=True)))

        for parent in self.path.parents:
            if parent.name != ".terragrunt-stack":
                continue
            stack_path = parent.with_name("terragrunt.stack.hcl")
            if any(s.path == stack_path.parent for s in ALL_STACKS):
                out.add(str(stack_path.relative_to(self.path, walk_up=True)))

        return list(out)  # sets are not json serializable

    def atlantis_project_format(self) -> AtlantisProjectDict:
        """Return the Atlantis project configuration for this unit."""
        autoplan: AutoPlanDict = {
            "enabled": True,
            "when_modified": self.get_when_modified(),
        }

        return {
            "autoplan": autoplan,
            "execution_order_group": self.get_execution_order_group(),
            "dir": str(self.path),
        }

    def dependency_units(self) -> Iterable["Unit"]:
        """Return dependencies as Units, pulling from all_units global"""
        return [unit for unit in ALL_UNITS if unit.path in self.dependencies]

    @classmethod
    def from_dict(cls, unit: dict) -> "Unit":
        """Create a Unit instance from a dictionary representation."""
        return cls(
            type=unit["type"],
            path=pathlib.PurePath(unit["path"]),
            include=[pathlib.PurePath(p) for p in unit.get("include", {}).values()],
            dependencies=[pathlib.PurePath(p) for p in unit.get("dependencies", [])],
            reading=[pathlib.PurePath(p) for p in unit.get("reading", [])],
            execution_order_group=None,
        )


ALL_STACKS: list[Unit] = []
ALL_UNITS: list[Unit] = []


def generate_atlantis_config(terragrunt_find_output: list[Unit]) -> str:
    "Take deserialized output from `terragrunt find --json --dependencies --include --reading` and print out the Atlantis config for it"

    # Remove files in "terragrunt-units" dir
    no_terragrunt_units = list(
        filter(
            lambda u: (
                not any(
                    contains(p, "terragrunt-units") for p in map(str, u.path.parents)
                )
            ),
            terragrunt_find_output,
        )
    )
    # Ensure it's only units; no stacks
    no_stacks = filter(lambda u: u.type == "unit", no_terragrunt_units)

    global ALL_UNITS
    global ALL_STACKS
    ALL_UNITS = list(no_stacks)  # eagerly load the list
    ALL_STACKS = list(filter(lambda u: u.type == "stack", no_terragrunt_units))

    # the thing we're outputting
    out: AtlantisConfigDict = {
        "version": 3,
        "automerge": False,
        "parallel_apply": True,
        "parallel_plan": True,
        "projects": [unit.atlantis_project_format() for unit in ALL_UNITS],
    }

    # print atlantis.yaml
    return json.dumps(out, indent=4)


if __name__ == "__main__":
    with fileinput.FileInput(encoding="utf-8") as terragrunt_find_output:
        # readin stdin or first argument, deserializing json
        body = "".join(terragrunt_find_output)
        deser_tg_find = [Unit.from_dict(d) for d in json.loads(body)]
    print(generate_atlantis_config(deser_tg_find))
