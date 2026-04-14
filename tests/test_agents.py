import pytest
from nexussentry.agents import ArchitectAgent, ScoutAgent

def test_scout_parse_valid_json():
    scout = ScoutAgent()
    valid_json = '{"goal_summary": "Test", "sub_tasks": [{"id": 1, "task": "Do something"}], "estimated_complexity": "simple"}'
    
    parsed = scout._parse_json_response(valid_json)
    assert parsed["goal_summary"] == "Test"
    assert len(parsed["sub_tasks"]) == 1

def test_scout_parse_markdown_json():
    scout = ScoutAgent()
    markdown_json = '''
    ```json
    {
        "goal_summary": "Test md",
        "sub_tasks": []
    }
    ```
    '''
    
    parsed = scout._parse_json_response(markdown_json)
    assert parsed["goal_summary"] == "Test md"

def test_architect_parse_fails():
    architect = ArchitectAgent()
    invalid_json = 'This is not json at all'
    
    with pytest.raises(ValueError):
        parsed = architect._parse_json_response(invalid_json)


def test_architect_classifies_small_task():
    architect = ArchitectAgent()
    plan = {
        "files_to_modify": ["one_file.py"],
        "commands_to_run": ["pytest tests/test_one.py"],
        "risks": [],
    }

    assert architect._classify_task_size(plan, "low", "simple") == "small"


def test_architect_classifies_medium_task():
    architect = ArchitectAgent()
    plan = {
        "files_to_modify": ["one.py", "two.py"],
        "commands_to_run": ["pytest tests/", "ruff check ."],
        "risks": ["Imports may need updates"],
    }

    assert architect._classify_task_size(plan, "medium", "medium") == "medium"


def test_architect_classifies_large_task_and_builds_dispatch():
    architect = ArchitectAgent()
    plan = {
        "files_to_modify": ["a.py", "b.py", "c.py", "d.py"],
        "commands_to_run": ["pytest", "ruff", "mypy"],
        "risks": ["Schema drift", "Retry complexity", "Cache invalidation"],
    }

    assert architect._classify_task_size(plan, "high", "complex") == "large"

    dispatch = architect._build_builder_dispatch(plan, "high", "complex")
    assert dispatch["task_size"] == "large"
    assert dispatch["builder_count"] == 5
    assert dispatch["builder_slots"] == 5
    assert dispatch["parallel_groups"] == 3
    assert dispatch["execution_profile"] in {"parallel", "sequential"}
