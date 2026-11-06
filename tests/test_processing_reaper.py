from unittest.mock import patch

import pytest

from app.services.processing import ProcessingError, _container_descendants, reap_container_children


def test_container_descendants_logic(tmp_path):
    """Test helper _container_descendants with mocked /proc."""
    proc_dir = tmp_path / "proc"
    proc_dir.mkdir()

    # format: {pid} ({comm}) S {ppid} ...
    stats = {
        "2": "2 (child_of_1) S 1",
        "3": "3 (child_of_2) S 2",
        "4": "4 (child_of_1) S 1",
        "5": "5 (injected) S 999",
        "6": "6 (child_of_5) S 5",
        "7": "7 (child_of_1) S 1",
        "8": "8 (other) S 999",
        "999": "999 (external) S 0",
    }

    for pid, content in stats.items():
        pid_dir = proc_dir / pid
        pid_dir.mkdir()
        (pid_dir / "stat").write_text(content)

    descendants = _container_descendants(proc_dir)

    assert 2 in descendants
    assert 3 in descendants
    assert 4 in descendants
    assert 7 in descendants
    assert 1 not in descendants
    assert 5 not in descendants
    assert 6 not in descendants
    assert 8 not in descendants
    assert 999 not in descendants


def test_container_descendants_comm_parsing(tmp_path):
    """Test comm name with spaces and parentheses."""
    proc_dir = tmp_path / "proc"
    proc_dir.mkdir()

    pid_dir = proc_dir / "10"
    pid_dir.mkdir()
    (pid_dir / "stat").write_text("10 (my process (with nested parens)) S 1")

    descendants = _container_descendants(proc_dir)
    assert 10 in descendants


def test_container_descendants_vanishing_stat(tmp_path):
    """Test vanishing stat during iteration."""
    proc_dir = tmp_path / "proc"
    proc_dir.mkdir()

    pid1_dir = proc_dir / "1"
    pid1_dir.mkdir()
    (pid1_dir / "stat").write_text("1 (root) S 0")

    (proc_dir / "11").mkdir()

    descendants = _container_descendants(proc_dir)
    assert 11 not in descendants


def test_reap_container_children_no_env_guard(monkeypatch):
    """Test reap_container_children without PROCESSING_CONTAINER_ISOLATED=1."""
    monkeypatch.setenv("PROCESSING_CONTAINER_ISOLATED", "0")
    with patch("os.kill") as mock_kill:
        reap_container_children()
        mock_kill.assert_not_called()


def test_reap_container_children_not_pid_1(monkeypatch):
    """Test reap_container_children when os.getpid() != 1."""
    monkeypatch.setenv("PROCESSING_CONTAINER_ISOLATED", "1")
    monkeypatch.setattr("os.getpid", lambda: 100)
    with patch("os.kill") as mock_kill:
        with pytest.raises(ProcessingError, match="Isolated processing must run as container PID 1."):
            reap_container_children()
        mock_kill.assert_not_called()


def test_reap_container_children_with_helper(tmp_path, monkeypatch):
    """Integration test for reap_container_children with helper and mocked os calls."""
    proc_dir = tmp_path / "proc"
    proc_dir.mkdir()

    stats = {
        "2": "2 (child_of_1) S 1",
        "3": "3 (child_of_2) S 2",
        "4": "4 (child_of_1) S 1",
        "5": "5 (injected) S 999",
        "6": "6 (child_of_5) S 5",
        "7": "7 (child_of_1) S 1",
        "8": "8 (other) S 999",
        "999": "999 (external) S 0",
    }
    for pid, content in stats.items():
        pid_dir = proc_dir / pid
        pid_dir.mkdir()
        (pid_dir / "stat").write_text(content)

    monkeypatch.setenv("PROCESSING_CONTAINER_ISOLATED", "1")
    monkeypatch.setattr("os.getpid", lambda: 1)

    with patch("app.services.processing.Path", return_value=proc_dir):
        with patch("os.kill") as mock_kill:
            with patch("os.waitpid") as mock_wait:
                mock_wait.side_effect = [(0, 0), ChildProcessError("No children")]

                reap_container_children()

                called_pids = [call.args[0] for call in mock_kill.call_args_list]
                assert set(called_pids) == {2, 3, 4, 7}
                assert 5 not in called_pids
                assert 6 not in called_pids
                assert 8 not in called_pids
                assert 999 not in called_pids


def test_reap_container_children_process_lookup_error(monkeypatch):
    """Test that ProcessLookupError during os.kill is ignored."""
    monkeypatch.setenv("PROCESSING_CONTAINER_ISOLATED", "1")
    monkeypatch.setattr("os.getpid", lambda: 1)

    with patch("app.services.processing._container_descendants", return_value={2}):
        with patch("os.kill") as mock_kill:
            mock_kill.side_effect = ProcessLookupError
            with patch("os.waitpid", side_effect=ChildProcessError("No children")):
                reap_container_children()
                mock_kill.assert_called()
