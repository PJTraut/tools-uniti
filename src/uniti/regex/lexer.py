"""Lightweight lexical analysis for regex and replacement input highlighting."""

from __future__ import annotations

from dataclasses import dataclass, replace
import regex as _syntax_re
from typing import Mapping


@dataclass(frozen=True, slots=True)
class RegexToken:
    kind: str
    start: int
    end: int
    text: str
    group_number: int | None = None
    group_name: str | None = None
    valid: bool = True


@dataclass(frozen=True, slots=True)
class ReplacementToken:
    kind: str
    start: int
    end: int
    text: str
    reference: int | str | None = None
    valid: bool = True


_QUANTIFIER = _syntax_re.compile(r"\{\d+(?:,\d*)?\}[?+]?")
_FLAG_ONLY = _syntax_re.compile(r"\(\?[aiLmsuxwfbV0V1-]+\)")
_FLAG_GROUP = _syntax_re.compile(r"\(\?[aiLmsuxwfbV0V1-]+:")


def _consume_class(pattern: str, start: int) -> tuple[int, bool]:
    i = start + 1
    escaped = False
    while i < len(pattern):
        char = pattern[i]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "]":
            return i + 1, True
        i += 1
    return len(pattern), False


def _consume_property(pattern: str, start: int) -> int | None:
    if start + 3 >= len(pattern) or pattern[start] != "\\" or pattern[start + 1] not in "pP":
        return None
    if pattern[start + 2] != "{":
        return None
    close = pattern.find("}", start + 3)
    return None if close < 0 else close + 1


def tokenize_pattern(pattern: str) -> tuple[RegexToken, ...]:
    if not isinstance(pattern, str):
        raise TypeError("pattern must be a string")

    tokens: list[RegexToken] = []
    group_stack: list[int] = []
    group_number = 0
    i = 0
    n = len(pattern)

    while i < n:
        char = pattern[i]

        if char == "\\":
            if i + 1 >= n:
                tokens.append(RegexToken("invalid", i, n, pattern[i:], valid=False))
                break
            property_end = _consume_property(pattern, i)
            if property_end is not None:
                tokens.append(RegexToken("unicode_property", i, property_end, pattern[i:property_end]))
                i = property_end
                continue
            if pattern[i + 1] in "pP" and i + 2 < n and pattern[i + 2] == "{":
                tokens.append(RegexToken("invalid", i, n, pattern[i:], valid=False))
                break
            if pattern[i + 1] == "g" and i + 2 < n and pattern[i + 2] == "<":
                close = pattern.find(">", i + 3)
                if close < 0:
                    tokens.append(RegexToken("invalid", i, n, pattern[i:], valid=False))
                    break
                end = close + 1
                tokens.append(RegexToken("backreference", i, end, pattern[i:end]))
                i = end
                continue
            if pattern[i + 1].isdigit():
                end = i + 2
                while end < n and pattern[end].isdigit():
                    end += 1
                tokens.append(RegexToken("backreference", i, end, pattern[i:end]))
                i = end
                continue
            tokens.append(RegexToken("escape", i, i + 2, pattern[i : i + 2]))
            i += 2
            continue

        if char == "[":
            end, valid = _consume_class(pattern, i)
            tokens.append(
                RegexToken(
                    "char_class" if valid else "invalid",
                    i,
                    end,
                    pattern[i:end],
                    valid=valid,
                )
            )
            i = end
            continue

        if char == "(":
            flag_only = _FLAG_ONLY.match(pattern, i)
            if flag_only is not None:
                end = flag_only.end()
                tokens.append(RegexToken("flag", i, end, pattern[i:end]))
                i = end
                continue

            flag_group = _FLAG_GROUP.match(pattern, i)
            name: str | None = None
            number: int | None = None
            end = i + 1
            if pattern.startswith("(?P<", i):
                close = pattern.find(">", i + 4)
                if close < 0:
                    tokens.append(RegexToken("invalid", i, n, pattern[i:], valid=False))
                    break
                name = pattern[i + 4 : close]
                group_number += 1
                number = group_number
                end = close + 1
            elif pattern.startswith("(?<", i) and not (
                pattern.startswith("(?<=", i) or pattern.startswith("(?<!", i)
            ):
                close = pattern.find(">", i + 3)
                if close < 0:
                    tokens.append(RegexToken("invalid", i, n, pattern[i:], valid=False))
                    break
                name = pattern[i + 3 : close]
                group_number += 1
                number = group_number
                end = close + 1
            elif flag_group is not None:
                end = flag_group.end()
            elif any(
                pattern.startswith(prefix, i)
                for prefix in ("(?:", "(?=", "(?!", "(?<=", "(?<!", "(?>", "(?|")
            ):
                if pattern.startswith(("(?<=", "(?<!"), i):
                    end = i + 4
                else:
                    end = i + 3
            else:
                group_number += 1
                number = group_number

            token_index = len(tokens)
            tokens.append(
                RegexToken(
                    "group_open",
                    i,
                    end,
                    pattern[i:end],
                    group_number=number,
                    group_name=name,
                )
            )
            group_stack.append(token_index)
            i = end
            continue

        if char == ")":
            if group_stack:
                group_stack.pop()
                tokens.append(RegexToken("group_close", i, i + 1, char))
            else:
                tokens.append(RegexToken("invalid", i, i + 1, char, valid=False))
            i += 1
            continue

        if char in "*+?":
            end = i + 1
            if end < n and pattern[end] in "?+":
                end += 1
            tokens.append(RegexToken("quantifier", i, end, pattern[i:end]))
            i = end
            continue

        if char == "{":
            match = _QUANTIFIER.match(pattern, i)
            if match is not None:
                end = match.end()
                tokens.append(RegexToken("quantifier", i, end, pattern[i:end]))
                i = end
                continue

        if char in "^$":
            tokens.append(RegexToken("anchor", i, i + 1, char))
            i += 1
            continue

        if char == "|":
            tokens.append(RegexToken("alternation", i, i + 1, char))
            i += 1
            continue

        start = i
        while i < n and pattern[i] not in r"\[](){}*+?|^$":
            i += 1
        if i == start:
            i += 1
        tokens.append(RegexToken("literal", start, i, pattern[start:i]))

    for token_index in group_stack:
        tokens[token_index] = replace(tokens[token_index], valid=False)
    return tuple(tokens)


def tokenize_replacement(
    replacement: str,
    *,
    group_count: int = 0,
    group_names: Mapping[str, int] | None = None,
) -> tuple[ReplacementToken, ...]:
    if not isinstance(replacement, str):
        raise TypeError("replacement must be a string")
    names = {} if group_names is None else dict(group_names)
    tokens: list[ReplacementToken] = []
    i = 0
    while i < len(replacement):
        if replacement[i] != "\\":
            start = i
            while i < len(replacement) and replacement[i] != "\\":
                i += 1
            tokens.append(ReplacementToken("literal", start, i, replacement[start:i]))
            continue

        if i + 1 >= len(replacement):
            tokens.append(ReplacementToken("invalid", i, i + 1, "\\", valid=False))
            i += 1
            continue

        if replacement[i + 1] == "g" and i + 2 < len(replacement) and replacement[i + 2] == "<":
            close = replacement.find(">", i + 3)
            if close < 0:
                tokens.append(
                    ReplacementToken("invalid", i, len(replacement), replacement[i:], valid=False)
                )
                break
            raw_ref = replacement[i + 3 : close]
            reference: int | str = int(raw_ref) if raw_ref.isdigit() else raw_ref
            valid = (
                0 <= reference <= group_count
                if isinstance(reference, int)
                else reference in names
            )
            end = close + 1
            tokens.append(
                ReplacementToken(
                    "backreference",
                    i,
                    end,
                    replacement[i:end],
                    reference=reference,
                    valid=valid,
                )
            )
            i = end
            continue

        if replacement[i + 1].isdigit():
            end = i + 2
            while end < len(replacement) and replacement[end].isdigit():
                end += 1
            reference = int(replacement[i + 1 : end])
            tokens.append(
                ReplacementToken(
                    "backreference",
                    i,
                    end,
                    replacement[i:end],
                    reference=reference,
                    valid=0 <= reference <= group_count,
                )
            )
            i = end
            continue

        end = i + 2
        tokens.append(ReplacementToken("escape", i, end, replacement[i:end]))
        i = end

    return tuple(tokens)
