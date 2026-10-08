"""Built-in isolated file-type environments (ADR-0013 Phase E3-E6, ADR-0014).

Each module here is a self-contained `Environment` implementation;
`catalog.py` lists them all with their labels, default syntax profile and
extension assignment. This package intentionally does not know about
`FileEnvironmentManager` (`app/file_environment_manager.py`) — that
composition happens at the app layer, keeping the dependency direction
app -> core, not core -> app.
"""

from __future__ import annotations

from .delimited_environment import CsvEnvironment, TsvEnvironment
from .json_environment import JsonEnvironment
from .markdown_environment import MarkdownEnvironment
from .usfm_environment import UsfmEnvironment
from .xml_environment import XmlEnvironment
from .yaml_environment import YamlEnvironment

__all__ = [
    "CsvEnvironment",
    "JsonEnvironment",
    "MarkdownEnvironment",
    "TsvEnvironment",
    "UsfmEnvironment",
    "XmlEnvironment",
    "YamlEnvironment",
]
