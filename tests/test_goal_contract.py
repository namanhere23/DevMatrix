import pytest
from nexussentry.contracts import derive_goal_contract

def test_shopping_cart_resolves_single_file():
    contract = derive_goal_contract("Generate a shopping cart single page in one file with html")
    assert contract.single_file is True
    assert "index.html" in contract.allowed_output_files
    assert contract.requires_inline_assets is True
    assert contract.allow_sidecar_assets is False
    assert contract.preferred_entrypoint == "index.html"
    assert contract.parallelism_mode == "serialized"

def test_shopping_cart_resolves_single_file_alt_wording():
    contract = derive_goal_contract("Create a standalone HTML file for a shopping cart")
    assert contract.single_file is True
    assert contract.requires_inline_assets is True
    assert contract.allow_sidecar_assets is False
    assert contract.parallelism_mode == "serialized"
    assert contract.preferred_entrypoint == "index.html"

def test_multi_file_project_not_single_file():
    contract = derive_goal_contract("Build a REST API with models and routes")
    assert contract.single_file is False
    assert contract.requires_inline_assets is False
    assert contract.allow_sidecar_assets is True
    assert contract.parallelism_mode == "parallel"

def test_default_is_parallel():
    contract = derive_goal_contract("Fix the login bug")
    assert contract.single_file is False
    assert contract.parallelism_mode == "parallel"

def test_tests_requested():
    contract = derive_goal_contract("Write a sorting algorithm with unit tests")
    assert contract.requires_tests is True
    assert contract.single_file is False
