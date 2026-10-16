"""Console output: coloured steps, a report collected for the final summary, and prompts."""
from __future__ import annotations

import getpass
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field


class StepFailed(Exception):
    """A step cannot continue; the message says what is wrong and what to do."""

    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


@dataclass
class Report:
    changed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)       # lines for the summary


class UI:
    def __init__(self, *, color: bool | None = None, interactive: bool = True, out: Callable[[str], None] | None = None,
                 reader: Callable[[str], str] | None = None, secret_reader: Callable[[str], str] | None = None) -> None:
        self.color = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None if color is None else color
        self.interactive = interactive
        self._out = out or (lambda s: print(s, flush=True))
        self._reader = reader or input
        self._secret_reader = secret_reader or getpass.getpass
        self.report = Report()
        self.lines: list[str] = []                    # everything printed (for tests and the log file)

    # ---------------------------------------------------------------- output
    def _c(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def _print(self, text: str) -> None:
        self.lines.append(text)
        self._out(text)

    def step(self, number: int, total: int, title: str) -> None:
        self._print("")
        self._print(self._c("1;36", f"[{number}/{total}] {title}"))

    def ok(self, message: str) -> None:
        self.report.changed.append(message)
        self._print(f"  {self._c('32', 'done')}     {message}")

    def already(self, message: str) -> None:
        self.report.skipped.append(message)
        self._print(f"  {self._c('2', 'already')}  {message}")

    def info(self, message: str) -> None:
        self._print(f"  {message}")

    def plan(self, message: str) -> None:
        self._print(f"  {self._c('35', 'would')}    {message}")

    def warn(self, message: str) -> None:
        self.report.warnings.append(message)
        self._print(f"  {self._c('33', 'warning')}  {message}")

    def fail(self, message: str, hint: str = "") -> None:
        self._print(f"\n{self._c('1;31', 'Stopped: ' + message)}")
        if hint:
            self._print(hint)

    def note(self, line: str) -> None:
        """A line for the final summary."""
        self.report.notes.append(line)

    # ---------------------------------------------------------------- input
    def ask(self, question: str, default: str = "", *, secret: bool = False,
            validate: Callable[[str], str | None] | None = None) -> str:
        """Ask until `validate` (returns an error text or None) accepts. Non-interactive: the default, or a failure."""
        while True:
            if not self.interactive:
                value = default
            else:
                suffix = f" [{default}]" if default and not secret else ""
                prompt = f"  {question}{suffix}: "
                value = (self._secret_reader(prompt) if secret else self._reader(prompt)).strip() or default
            problem = validate(value) if validate else None
            if problem is None:
                return value
            if not self.interactive:
                raise StepFailed(f"{question}: {problem}")
            self._print(self._c("31", f"  {problem}"))

    def confirm(self, question: str, default: bool = False) -> bool:
        if not self.interactive:
            return default
        answer = self._reader(f"  {question} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
        return default if not answer else answer in ("y", "yes")
