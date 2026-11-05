"""CSV/TSV light environments (ADR-0014).

Decoration is the existing `CSV`/`TSV` `SyntaxProfile`. `validate()` adds one
narrow capability: flagging a row whose field count differs from the first
row's, the most common way a delimited file silently goes wrong. Parsing uses
the standard library's `csv` module, so quoted CSV fields (including quoted
delimiters and quoted newlines) are counted correctly — something the
line-oriented syntax highlighter deliberately does not attempt (see
`syntax_profiles.py`'s module docstring).
"""

from __future__ import annotations

import csv
import io

from uniti.core.decoration import DecorationProvider, SyntaxProfileDecorationAdapter
from uniti.core.environment import EnvironmentContext
from uniti.core.environment_commands import (
    EnvironmentCommand,
    document_text,
    validate_command,
)
from uniti.core.environment_findings import EnvironmentFinding, FindingSeverity
from uniti.core.syntax_profiles import CSV, TSV, SyntaxProfile

from .settings import CHOICE, FLAG, EnvironmentSetting, environment_settings

_HEADER_SETTING = EnvironmentSetting(
    "header",
    "First row is a header",
    FLAG,
    True,
    "Check Column Counts names the header as the row the others must match.",
    section="Check Column Counts",
)
CSV_SETTINGS: tuple[EnvironmentSetting, ...] = (
    EnvironmentSetting(
        "delimiter",
        "Delimiter",
        CHOICE,
        ",",
        "The character between fields.",
        choices=((",", ", (comma)"), (";", "; (semicolon)"), ("|", "| (pipe)"), ("\t", "Tab")),
        section="Check Column Counts",
    ),
    EnvironmentSetting(
        "quote",
        "Quote character",
        CHOICE,
        '"',
        "The character around a field that holds the delimiter or a line break.",
        choices=(('"', '" (double quote)'), ("'", "' (single quote)")),
        section="Check Column Counts",
    ),
    _HEADER_SETTING,
)
TSV_SETTINGS: tuple[EnvironmentSetting, ...] = (_HEADER_SETTING,)

MAX_FINDINGS = 500


def _line_offsets(text: str) -> list[int]:
    """Line starts, splitting exactly as `StringIO(newline="")` does (on
    `\n`, `\r\n` and lone `\r`) so they agree with `csv.reader.line_num`."""

    offsets = [0]
    length = len(text)
    for index, char in enumerate(text):
        if char == "\n" or char == "\r" and (index + 1 >= length or text[index + 1] != "\n"):
            offsets.append(index + 1)
    return offsets


def column_count_findings(
    text: str,
    delimiter: str,
    code_prefix: str,
    *,
    quotechar: str = '"',
    header: bool = True,
) -> tuple[EnvironmentFinding, ...]:
    if not text:
        return ()
    line_offsets = _line_offsets(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, quotechar=quotechar)
    first = "the header" if header else "the first row"
    findings: list[EnvironmentFinding] = []
    expected: int | None = None
    try:
        row_start_line = 0
        for row in reader:
            row_end_line = reader.line_num
            start = line_offsets[min(row_start_line, len(line_offsets) - 1)]
            row_start_line = row_end_line
            if not row:
                continue
            if expected is None:
                expected = len(row)
                continue
            if len(row) != expected:
                # A row spans its lines up to (not including) the newline
                # that ends its last line.
                end = line_offsets[row_end_line] if row_end_line < len(line_offsets) else len(text)
                if end > start and text[end - 1] == "\n":
                    end -= 1
                if end > start and text[end - 1] == "\r":
                    end -= 1
                findings.append(
                    EnvironmentFinding(
                        start,
                        max(start, end),
                        FindingSeverity.WARNING,
                        f"row {row_end_line} has {len(row)} fields; {first} has {expected}",
                        code=f"{code_prefix}.column-count",
                    )
                )
                if len(findings) >= MAX_FINDINGS:
                    break
    except csv.Error as exc:
        start = line_offsets[min(reader.line_num, len(line_offsets) - 1)]
        findings.append(
            EnvironmentFinding(start, start, FindingSeverity.ERROR, str(exc), code=f"{code_prefix}.parse")
        )
    return tuple(findings)


class _DelimitedEnvironment:
    key: str
    _profile: SyntaxProfile
    _delimiter: str

    def __init__(self) -> None:
        self._decoration_provider = SyntaxProfileDecorationAdapter(self._profile)

    def activate(self, context: EnvironmentContext) -> None:
        del context

    def deactivate(self) -> None:
        pass

    @property
    def decoration_provider(self) -> DecorationProvider | None:
        return self._decoration_provider

    def validate(self, context: EnvironmentContext) -> tuple[EnvironmentFinding, ...]:
        if not context.resource_profile.allow_full_parse:
            return ()
        settings = environment_settings(self.key)
        declared = {setting.key for setting in settings.declarations}
        delimiter = settings.get("delimiter") if "delimiter" in declared else self._delimiter
        quote = settings.get("quote") if "quote" in declared else '"'
        return column_count_findings(
            document_text(context),
            str(delimiter),
            self.key,
            quotechar=str(quote),
            header=settings.get("header") is True,
        )

    def commands(self) -> tuple[EnvironmentCommand, ...]:
        return (validate_command(self, label="Check Column Counts"),)


class CsvEnvironment(_DelimitedEnvironment):
    key = "csv"
    _profile = CSV
    _delimiter = ","

    @staticmethod
    def settings_declarations() -> tuple[EnvironmentSetting, ...]:
        return CSV_SETTINGS


class TsvEnvironment(_DelimitedEnvironment):
    key = "tsv"
    _profile = TSV
    _delimiter = "\t"

    @staticmethod
    def settings_declarations() -> tuple[EnvironmentSetting, ...]:
        return TSV_SETTINGS
