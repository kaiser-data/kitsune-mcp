"""Skeleton runner — interfaces only, no implementation.

Purpose: show the shape a runner should have so that filling it in (or wiring
inspect_ai to the same schemas) is mechanical. Do NOT use this as-is; nothing
here actually runs.

A working runner needs to implement:
  1. load_task   — validate task.yaml against task.schema.json
  2. prepare_workdir — extract fixture into a sandbox
  3. invoke_adapter — drive the system under test
  4. capture_diff   — workdir vs fixture → unified diff
  5. write_result   — emit result.json
  6. run_grader     — invoke grader.py → score.json
  7. aggregate      — collapse n_runs into one summary row
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class TaskSpec:
    """Parsed task.yaml. Mirrors task.schema.json."""
    id: str
    category: str
    version: str
    prompt_instruction: str
    prompt_addendum: str | None
    fixture_path: Path
    grader_script: Path
    required_capabilities: list[str]
    allowed_paths: list[str]
    forbidden_paths: list[str]
    limits: dict
    raw: dict  # the full parsed YAML, for fields not modelled above


@dataclass
class SystemConfig:
    """How to invoke the system under test."""
    adapter: str  # 'api_only' | 'agentic' | 'ide_interactive'
    name: str
    version: str
    model: str | None
    config: dict  # adapter-specific


@dataclass
class RunArtifact:
    """What a single run produces — maps 1:1 to result.schema.json."""
    workdir: Path
    diff: str
    metrics: dict
    transcript: list[dict]
    tool_calls: list[dict]
    errors: list[dict]


class Adapter(Protocol):
    """The interface every adapter implementation satisfies."""

    name: str  # 'api_only' | 'agentic' | 'ide_interactive'

    def supports(self, task: TaskSpec) -> bool:
        """Return False if the adapter cannot satisfy the task's
        required_capabilities; the runner will skip this (system, task) pair."""
        ...

    def run(self, task: TaskSpec, system: SystemConfig, workdir: Path) -> RunArtifact:
        """Execute one run. Must respect task.limits and write nothing outside workdir."""
        ...


def load_task(task_yaml_path: Path) -> TaskSpec:
    """Parse + validate task.yaml against the schema. Raise on invalid."""
    raise NotImplementedError


def prepare_workdir(task: TaskSpec, sandbox_root: Path) -> Path:
    """Copy fixture/ into a fresh sandbox dir; return the path."""
    raise NotImplementedError


def capture_diff(workdir: Path, fixture: Path) -> str:
    """git diff –no-index fixture workdir, return unified diff string."""
    raise NotImplementedError


def write_result(artifact: RunArtifact, task: TaskSpec, system: SystemConfig,
                 run_meta: dict, out_path: Path) -> None:
    """Serialise to result.json, validating against result.schema.json."""
    raise NotImplementedError


def run_grader(task: TaskSpec, result_path: Path, workdir: Path,
               score_out: Path) -> dict:
    """Subprocess: python grader.py --workdir … --result … --out …"""
    raise NotImplementedError


def aggregate(score_paths: list[Path]) -> dict:
    """N×score.json → one summary: pass@1, pass@k, mean, σ, cost stats."""
    raise NotImplementedError


# Entry point sketch ---------------------------------------------------------

def main_sketch(task_yaml: Path, system_yaml: Path, n_runs: int, out_dir: Path) -> None:
    """Pseudo-code only — do not call. Shows the flow."""
    task = load_task(task_yaml)
    # system = load_system(system_yaml)         # YAML matching SystemConfig
    # adapter = ADAPTERS[system.adapter]()      # registry pattern
    # if not adapter.supports(task): skip
    # for i in range(n_runs):
    #     workdir = prepare_workdir(task, out_dir / f"run_{i}/work")
    #     artifact = adapter.run(task, system, workdir)
    #     write_result(artifact, task, system, {"n_in_series": i + 1, ...},
    #                  out_dir / f"run_{i}/result.json")
    #     run_grader(task, out_dir / f"run_{i}/result.json", workdir,
    #                out_dir / f"run_{i}/score.json")
    # summary = aggregate(list((out_dir).glob("run_*/score.json")))
    # (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    raise NotImplementedError
