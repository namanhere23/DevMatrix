import pytest
from nexussentry.agents.qa_verifier import run_deterministic_qa
from nexussentry.contracts import GoalContract

def test_mismatched_selectors_fail():
    html_content = """
<html>
    <head><style>body { color: red; }</style></head>
    <body id="main">
        <script>
            document.getElementById('missing_id');
            document.querySelector('#another_missing');
        </script>
    </body>
</html>
"""
    result = run_deterministic_qa({"index.html": html_content})
    assert result["passed"] is False
    assert len(result["issues"]) == 2
    assert "missing_id" in result["issues"][0]
    assert "another_missing" in result["issues"][1]

def test_truncated_html_rejected():
    result = run_deterministic_qa({"index.html": "<html><body><div>"})
    assert result["passed"] is False
    assert any("unclosed <body>" in i for i in result["issues"])
    assert any("unclosed <html>" in i for i in result["issues"])

def test_sidecar_references_rejected():
    html_content = '<link rel="stylesheet" href="style.css">'
    contract = GoalContract(
        single_file=True,
        requires_inline_assets=True,
        allow_sidecar_assets=False,
        allowed_output_files=["index.html"]
    )
    result = run_deterministic_qa({"index.html": html_content}, goal_contract=contract)
    assert result["passed"] is False
    assert any("external sidecar reference" in i for i in result["issues"])

def test_static_single_file_without_script_or_style_passes():
    html_content = "<html><body>Hello</body></html>"
    contract = GoalContract(
        single_file=True,
        requires_inline_assets=True,
        allow_sidecar_assets=False,
        allowed_output_files=["index.html"]
    )
    result = run_deterministic_qa({"index.html": html_content}, goal_contract=contract)
    assert result["passed"] is True

def test_valid_single_file_passes():
    html_content = """
<html>
    <head><style>body { color: red; }</style></head>
    <body id="main">
        <script>
           console.log("no refs to check");
        </script>
    </body>
</html>
"""
    contract = GoalContract(
        single_file=True,
        requires_inline_assets=True,
        allow_sidecar_assets=False,
        allowed_output_files=["index.html"]
    )
    result = run_deterministic_qa({"index.html": html_content}, goal_contract=contract)
    assert result["passed"] is True
