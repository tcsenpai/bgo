"""Tests for bgo's direct-mode parsing in ``main()``.

Direct mode interprets bare positional args like ``bgo myapp -- cmd``
instead of requiring an explicit ``start`` subcommand. These tests
patch ``sys.argv`` and the command handlers to verify routing.
"""

from __future__ import annotations

import argparse
import sys
from unittest import mock

import pytest


def test_direct_mode_explicit_name(bgo, monkeypatch):
    calls = []
    monkeypatch.setattr(bgo, "cmd_start", lambda args: calls.append(args) or 0)
    monkeypatch.setattr(bgo, "load_proc", lambda _name: None)
    monkeypatch.setattr(sys, "argv", ["bgo", "myapp", "--", "python3", "server.py"])
    bgo.main()
    assert len(calls) == 1
    assert calls[0].name == "myapp"
    assert calls[0].command == ["python3", "server.py"]


def test_direct_mode_auto_name_from_command(bgo, monkeypatch):
    calls = []
    monkeypatch.setattr(bgo, "cmd_start", lambda args: calls.append(args) or 0)
    monkeypatch.setattr(bgo, "load_proc", lambda _name: None)
    monkeypatch.setattr(sys, "argv", ["bgo", "python3", "server.py"])
    bgo.main()
    assert len(calls) == 1
    # first token looks like a command (python3 is on PATH), so the
    # command is the whole argv tail and the name derives from cmd[0].
    assert calls[0].name == "python3"
    assert calls[0].command == ["python3", "server.py"]


def test_direct_mode_name_plus_command(bgo, monkeypatch):
    calls = []
    monkeypatch.setattr(bgo, "cmd_start", lambda args: calls.append(args) or 0)
    monkeypatch.setattr(bgo, "load_proc", lambda _name: None)
    monkeypatch.setattr(sys, "argv", ["bgo", "myapp", "python3", "server.py", "--port", "8080"])
    bgo.main()
    assert len(calls) == 1
    assert calls[0].name == "myapp"
    assert calls[0].command == ["python3", "server.py", "--port", "8080"]


def test_direct_mode_watch_flag(bgo, monkeypatch):
    calls = []
    monkeypatch.setattr(bgo, "cmd_start", lambda args: calls.append(args) or 0)
    monkeypatch.setattr(bgo, "load_proc", lambda _name: None)
    monkeypatch.setattr(sys, "argv", ["bgo", "-w", "myapp", "python3", "server.py"])
    bgo.main()
    assert len(calls) == 1
    assert calls[0].name == "myapp"
    assert calls[0].watch is True


def test_direct_mode_dotted_name_treated_as_name(bgo, monkeypatch):
    calls = []
    monkeypatch.setattr(bgo, "cmd_start", lambda args: calls.append(args) or 0)
    monkeypatch.setattr(bgo, "load_proc", lambda _name: None)
    monkeypatch.setattr(sys, "argv", ["bgo", "my.app", "python3", "server.py"])
    bgo.main()
    assert len(calls) == 1
    assert calls[0].name == "my.app"


def test_direct_mode_single_arg_routes_to_status(bgo, monkeypatch):
    status_calls = []
    monkeypatch.setattr(bgo, "cmd_status", lambda args: status_calls.append(args) or 0)
    monkeypatch.setattr(bgo, "load_proc", lambda name: ({"name": name} if name == "myapp" else None))
    monkeypatch.setattr(sys, "argv", ["bgo", "myapp"])
    bgo.main()
    assert len(status_calls) == 1
    assert status_calls[0].name == "myapp"


def test_direct_mode_unknown_single_arg_prints_error(bgo, monkeypatch, capsys):
    monkeypatch.setattr(bgo, "load_proc", lambda _name: None)
    monkeypatch.setattr(sys, "argv", ["bgo", "unknown"])
    rc = bgo.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "Unknown command or process" in out
    assert "unknown" in out


def test_direct_mode_no_command_after_separator(bgo, monkeypatch, capsys):
    monkeypatch.setattr(bgo, "load_proc", lambda _name: None)
    monkeypatch.setattr(sys, "argv", ["bgo", "myapp", "--"])
    rc = bgo.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "Usage:" in out


def test_direct_mode_unknown_flag_routes_to_argparse(bgo, monkeypatch):
    monkeypatch.setattr(bgo, "load_proc", lambda _name: None)
    monkeypatch.setattr(sys, "argv", ["bgo", "--bogus"])
    # argparse exits on unrecognized flag; main() doesn't swallow it.
    with pytest.raises(SystemExit):
        bgo.main()
