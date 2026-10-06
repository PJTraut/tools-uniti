"""Generic SFM domain logic (ADR-0013, Phase E5).

Kept as a subpackage, unlike the flat `json_environment.py`-style modules,
because generic SFM needs several small collaborating pieces (a lossless
tokenizer, a permissive source tree, and a `.STY` reader) rather than one
file. `core/environments/sfm_environment.py` is the `Environment`
implementation that wires these together — it sits alongside its JSON/XML/
YAML siblings so `core/environments/__init__.py` keeps exporting one
`Environment` class per file type from a flat, predictable surface.
"""

from __future__ import annotations
