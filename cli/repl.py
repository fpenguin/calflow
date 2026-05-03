"""
CalFlow REPL (v2.0 — Smart Mode + Plus Mode).

Purpose:
- Interactive testing environment for both modes.
- Mirrors the real pipeline: parse → route → execute.
- Detects `+CalFlow+` blocks (multi-line input via heredoc-style EOF).
- Displays the parsed structure for debugging.

Usage:
    python -m cli.repl

Meta commands:
    :help     show help
    :exit     exit REPL
    :quit     exit REPL
    :clear    clear terminal
    :debug    toggle debug logging
    :plus     enter multi-line Plus block (terminate with `EOF` on its own line)
    :ast      print AST/entries of the last parsed input without executing

Design:
- never crashes (every error is caught and surfaced)
- non-blocking (each command applies the same delays as production)
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional

from core.models import MODE_NONE, MODE_PLUS, MODE_SMART, ParseResult
from core.parser.parser import parse
from core.utils import log
from runtime.command_executor import execute_commands
from runtime.executor import execute_entries


# =========================================================
# 🧠 REPL
# =========================================================

class CalFlowREPL:
    """
    Interactive REPL for CalFlow v2.0.

    Smart Mode lines run immediately; multi-line Plus Mode blocks
    are entered via `:plus` and terminated with `EOF`.
    """

    def __init__(self) -> None:
        self.running: bool = True
        self.debug: bool = False
        self.last_result: Optional[ParseResult] = None

    # =====================================================
    # 🚀 ENTRY
    # =====================================================

    def run(self) -> None:
        self._print_banner()

        while self.running:
            try:
                line = input("calflow> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not line:
                continue

            try:
                if line.startswith(":"):
                    self._handle_meta(line)
                else:
                    self._process_input(line)
            except Exception as exc:
                # REPL must never crash.
                print(f"[ERROR] {exc}")

    # =====================================================
    # 🧾 META COMMANDS
    # =====================================================

    def _handle_meta(self, command: str) -> None:
        cmd = command.strip().lower()

        if cmd in (":exit", ":quit"):
            self.running = False
            print("Goodbye.")
            return

        if cmd == ":help":
            self._print_help()
            return

        if cmd == ":clear":
            os.system("cls" if os.name == "nt" else "clear")
            return

        if cmd == ":debug":
            self.debug = not self.debug
            print(f"[INFO] Debug {'on' if self.debug else 'off'}")
            return

        if cmd == ":plus":
            block = self._read_multiline_block()
            self._process_input(block)
            return

        if cmd == ":ast":
            if self.last_result is None:
                print("[INFO] No previous parse to show.")
                return
            self._print_result(self.last_result)
            return

        print(f"[WARN] Unknown command: {command}")

    # =====================================================
    # ⚙️ CORE PROCESSING
    # =====================================================

    def _process_input(self, text: str) -> None:
        """Parse, display, and route to the right executor."""
        parsed = parse(text)
        self.last_result = parsed
        self._print_result(parsed)

        if parsed.has_errors:
            for err in parsed.errors:
                print(f"[VALIDATION] {err}")

        if parsed.mode == MODE_SMART:
            # global_tags here mirrors the production pipeline shape.
            execute_entries(
                entries=parsed.entries,
                global_tags=set(parsed.global_tags),
                debug=self.debug,
            )
        elif parsed.mode == MODE_PLUS:
            execute_commands(
                commands=parsed.commands,
                global_tags=set(parsed.global_tags),
                debug=self.debug,
            )
        elif parsed.mode == MODE_NONE:
            print("[INFO] No executable content")

    # =====================================================
    # 📥 INPUT HELPERS
    # =====================================================

    def _read_multiline_block(self) -> str:
        """
        Read a multi-line Plus block. Terminator is a line whose
        stripped content equals 'EOF' (case-insensitive).
        """
        print("[INFO] Enter Plus block (terminate with 'EOF' on its own line):")
        lines: List[str] = []
        # Auto-prepend the header so users can omit it inside :plus.
        lines.append("+CalFlow+")
        while True:
            try:
                raw = input("plus> ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if raw.strip().lower() == "eof":
                break
            lines.append(raw)
        return "\n".join(lines)

    # =====================================================
    # 🖨️ DISPLAY
    # =====================================================

    def _print_result(self, result: ParseResult) -> None:
        print("─" * 50)
        print(f"mode:    {result.mode}")
        if result.mode == MODE_SMART:
            print(f"entries: {len(result.entries)}")
            for i, entry in enumerate(result.entries, start=1):
                print(f"  [{i}] {entry}")
        elif result.mode == MODE_PLUS:
            print(f"commands: {len(result.commands)}")
            for cmd in result.commands:
                print(f"  L{cmd.line_no:>2} {cmd.name:<10} {cmd.raw}")
        if result.global_tags:
            print(f"tags:    {sorted(result.global_tags)}")
        if result.errors:
            print(f"errors:  {len(result.errors)}")
        print("─" * 50)

    def _print_banner(self) -> None:
        print("=" * 50)
        print(" CalFlow REPL (v2.0 — Smart Mode + Plus Mode)")
        print("=" * 50)
        print("Smart Mode: type a line — `zoom.us @chrome #left(50%)`")
        print("Plus Mode:  type `:plus` to enter a multi-line block.")
        print("Use `:help` for commands.\n")

    def _print_help(self) -> None:
        print(
            """
REPL Commands:
  :help     Show this message
  :exit     Exit REPL
  :quit     Exit REPL
  :clear    Clear screen
  :debug    Toggle debug logging
  :plus     Enter multi-line Plus block (header auto-added)
  :ast      Print parsed structure of the last input

Examples:
  zoom.us
  zoom.us @chrome #left(50%)
  :plus
    OPEN https://example.com @chrome #left(50%)
    WAIT 2
    SCREENSHOT
    EOF
"""
        )


# =========================================================
# 🏁 MAIN
# =========================================================

def main() -> None:
    CalFlowREPL().run()


if __name__ == "__main__":
    main()
