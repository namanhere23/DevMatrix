import pytest
from nexussentry.agents.scout import ScoutAgent
from nexussentry.agents.architect import ArchitectAgent

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
