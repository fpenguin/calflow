"""Validate CLI requests before importing calendar or desktop dependencies."""

from __future__ import annotations

import argparse

from core.version import version_string

__all__ = ["validate_arguments"]


def validate_arguments(args: list[str]) -> list[str]:
    args = list(args)
    if args and args[0] in {"--setup", "--uninstall"}:
        args[0] = args[0][2:]
    parser = argparse.ArgumentParser(prog="calflow", description="Calendar-driven Mac automation")
    parser.add_argument("--version", "-V", action="version", version=f"CalFlow {version_string()}")
    subparsers = parser.add_subparsers(dest="command")
    commands = (
        "setup uninstall start stop restart status display test stats recipes save-recipe "
        "delete-recipe run-script settings edit-settings-file apply-settings targets apply-targets "
        "migrate-settings daemon-start daemon-stop daemon-restart menubar-install menubar-start "
        "menubar-stop menubar-restart menubar-status menubar-uninstall open-system-prefs "
        "popover-feed upcoming missed run-event pause resume menubar version submit-event "
        "submit-script job-worker job-status job-cancel jobs"
    ).split()
    for command in commands:
        sub = subparsers.add_parser(command)
        sub.add_argument("--json", action="store_true")
        if command in {"run-event", "submit-event", "delete-recipe", "job-worker", "job-status", "job-cancel"}:
            sub.add_argument("id")
        if command in {"popover-feed", "upcoming", "missed"}:
            sub.add_argument("--hours", type=int)
        if command == "uninstall":
            sub.add_argument("--full", action="store_true")
        if command == "open-system-prefs":
            sub.add_argument("pane", nargs="?", default="accessibility")
    parsed = parser.parse_args(args)
    if hasattr(parsed, "id"):
        return [parsed.command, parsed.id] + (["--json"] if parsed.json else [])
    return args
