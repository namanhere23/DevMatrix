"""Agents — Specialized AI agents that form the NexusSentry swarm.

This package supports agent files with non-module filenames (e.g. ``AGENT-A_scout.py``)
by loading them dynamically and re-exporting stable symbols.
"""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from .optimizer import OptimizerAgent

_AGENTS_DIR = Path(__file__).resolve().parent
_MODULE_CACHE: dict[str, ModuleType] = {}


def _load_agent_module(filename: str) -> ModuleType:
	cached = _MODULE_CACHE.get(filename)
	if cached is not None:
		return cached

	module_path = _AGENTS_DIR / filename
	module_name = f"nexussentry.agents._dynamic_{filename.replace('-', '_').replace('.', '_')}"
	spec = spec_from_file_location(module_name, module_path)
	if spec is None or spec.loader is None:
		raise ImportError(f"Unable to load agent module from {module_path}")

	module = module_from_spec(spec)
	spec.loader.exec_module(module)
	_MODULE_CACHE[filename] = module
	return module


def _load_attr(filename: str, attr: str):
	module = _load_agent_module(filename)
	try:
		return getattr(module, attr)
	except AttributeError as exc:
		raise ImportError(f"{attr} not found in {filename}") from exc


ScoutAgent = _load_attr("AGENT-A_scout.py", "ScoutAgent")
ArchitectAgent = _load_attr("AGENT-B_architect.py", "ArchitectAgent")
BuilderAgent = _load_attr("AGENT-C_builder.py", "BuilderAgent")
QAVerifierAgent = _load_attr("AGENT-D_qa_verifier.py", "QAVerifierAgent")
run_deterministic_qa = _load_attr("AGENT-D_qa_verifier.py", "run_deterministic_qa")
CriticAgent = _load_attr("AGENT-E_critic.py", "CriticAgent")
IntegratorAgent = _load_attr("AGENT-F_integrator.py", "IntegratorAgent")

__all__ = [
	"ScoutAgent",
	"ArchitectAgent",
	"BuilderAgent",
	"QAVerifierAgent",
	"run_deterministic_qa",
	"CriticAgent",
	"IntegratorAgent",
	"OptimizerAgent",
]
