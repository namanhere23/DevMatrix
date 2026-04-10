"""
Tests for SwarmMemory decision-driving capabilities.
Verifies file conflict detection, actionable constraints,
thread safety, and context summarization.
"""

import pytest
import threading
from nexussentry.utils.swarm_memory import SwarmMemory


class TestFileConflictDetection:
    """Tests for has_file_conflict()."""

    def test_no_conflict_when_no_files_modified(self):
        """No conflicts if nothing has been modified yet."""
        memory = SwarmMemory()
        assert memory.has_file_conflict(["auth.py", "db.py"]) == []

    def test_no_conflict_with_disjoint_files(self):
        """No conflicts when proposed files don't overlap with modified."""
        memory = SwarmMemory()
        memory.mark_file_modified("config.py")
        memory.mark_file_modified("utils.py")
        assert memory.has_file_conflict(["auth.py", "db.py"]) == []

    def test_detects_single_conflict(self):
        """Should detect when one proposed file was already modified."""
        memory = SwarmMemory()
        memory.mark_file_modified("auth.py")
        memory.mark_file_modified("config.py")

        conflicts = memory.has_file_conflict(["auth.py", "db.py"])
        assert conflicts == ["auth.py"]

    def test_detects_multiple_conflicts(self):
        """Should detect when multiple proposed files conflict."""
        memory = SwarmMemory()
        memory.mark_file_modified("auth.py")
        memory.mark_file_modified("db.py")

        conflicts = memory.has_file_conflict(["auth.py", "db.py", "api.py"])
        assert set(conflicts) == {"auth.py", "db.py"}

    def test_empty_proposed_files(self):
        """Empty proposed list should return no conflicts."""
        memory = SwarmMemory()
        memory.mark_file_modified("auth.py")
        assert memory.has_file_conflict([]) == []

    def test_none_proposed_files(self):
        """None proposed files should return empty list."""
        memory = SwarmMemory()
        memory.mark_file_modified("auth.py")
        assert memory.has_file_conflict(None) == []


class TestActionableConstraints:
    """Tests for get_actionable_constraints()."""

    def test_no_constraints_when_empty(self):
        """Empty memory should produce no constraints."""
        memory = SwarmMemory()
        assert memory.get_actionable_constraints() == ""

    def test_constraints_include_modified_files(self):
        """Modified files should appear in constraints."""
        memory = SwarmMemory()
        memory.mark_file_modified("auth.py")
        memory.mark_file_modified("db.py")

        constraints = memory.get_actionable_constraints()
        assert "ALREADY MODIFIED FILES" in constraints
        assert "auth.py" in constraints
        assert "db.py" in constraints

    def test_constraints_include_file_conflict_warning(self):
        """Should warn when proposed files conflict."""
        memory = SwarmMemory()
        memory.mark_file_modified("auth.py")

        constraints = memory.get_actionable_constraints(proposed_files=["auth.py"])
        assert "FILE CONFLICT WARNING" in constraints
        assert "auth.py" in constraints

    def test_constraints_include_critic_feedback(self):
        """Critic feedback should surface as planning rules."""
        memory = SwarmMemory()
        memory.record_critic_feedback("Missing input validation")
        memory.record_critic_feedback("Error messages leak table names")

        constraints = memory.get_actionable_constraints()
        assert "LESSONS FROM PREVIOUS REJECTIONS" in constraints
        assert "Missing input validation" in constraints
        assert "Error messages leak table names" in constraints

    def test_constraints_limit_feedback_to_last_3(self):
        """Only the last 3 critic feedbacks should be included."""
        memory = SwarmMemory()
        for i in range(5):
            memory.record_critic_feedback(f"Feedback {i}")

        constraints = memory.get_actionable_constraints()
        assert "Feedback 2" in constraints
        assert "Feedback 3" in constraints
        assert "Feedback 4" in constraints
        assert "Feedback 0" not in constraints


class TestThreadSafety:
    """Tests for thread safety of concurrent operations."""

    def test_concurrent_writes_dont_crash(self):
        """Multiple threads writing concurrently should not raise."""
        memory = SwarmMemory()
        errors = []

        def writer(thread_id):
            try:
                for i in range(50):
                    memory.record_task_result(thread_id * 100 + i, f"Task {thread_id}-{i}", "OK")
                    memory.mark_file_modified(f"file_{thread_id}_{i}.py")
                    memory.record_fact(f"fact_{thread_id}_{i}", f"value_{i}")
                    memory.record_critic_feedback(f"Feedback from thread {thread_id}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(memory.get_task_history()) == 200  # 4 threads * 50 tasks

    def test_concurrent_reads_dont_crash(self):
        """Reading while writing shouldn't cause issues."""
        memory = SwarmMemory()
        memory.record_task_result(1, "Setup", "Done")
        memory.mark_file_modified("base.py")
        errors = []

        def reader():
            try:
                for _ in range(50):
                    memory.summarize_context()
                    memory.get_actionable_constraints(["base.py"])
                    memory.has_file_conflict(["test.py"])
                    memory.get_modified_files()
            except Exception as e:
                errors.append(e)

        def writer():
            try:
                for i in range(50):
                    memory.mark_file_modified(f"new_{i}.py")
                    memory.record_critic_feedback(f"Issue {i}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestSummarizeContext:
    """Tests for context summarization."""

    def test_empty_memory_returns_empty_string(self):
        """Empty memory should return empty string."""
        memory = SwarmMemory()
        assert memory.summarize_context() == ""

    def test_includes_all_sections(self):
        """Summary should include all memory sections when populated."""
        memory = SwarmMemory()
        memory.record_task_result(1, "Fix auth", "Done")
        memory.mark_file_modified("auth.py")
        memory.record_fact("project_type", "web_app")
        memory.record_critic_feedback("Missing tests")

        ctx = memory.summarize_context()
        assert "Fix auth" in ctx
        assert "auth.py" in ctx
        assert "project_type" in ctx
        assert "Missing tests" in ctx
