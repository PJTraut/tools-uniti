"""Representative LTR interaction scenario, measured against existing UI gates.

Run: QT_QPA_PLATFORM=offscreen python -m benchmarks.multilingual
Native platform IME qualification is separate from this synthetic scenario.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile
import time
import tomllib

SAMPLE = "Latin Ж क्षि ক্কি ક્કિ ਕਿ ಕ್ಕಿ ക്കി କ୍କି க்கி క్కి 汉字 漢字 한국어 👩‍💻 é\tX\u200bY"


def run():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    app = QApplication.instance() or QApplication([])
    timings = []
    with tempfile.TemporaryDirectory(prefix="uniti-multilingual-") as directory:
        path = Path(directory) / "mixed.txt"
        path.write_text((SAMPLE + "\n") * 500, encoding="utf-8")
        with Document.open(path, encoding="utf-8") as document:
            view = UNITITextView(EditorState(document))
            view.resize(800, 400)
            view.show()
            app.processEvents()
            for zoom in (100, 150, 200):
                view.set_zoom_percent(zoom)
                for wrapped in (False, True):
                    view.set_soft_wrap(wrapped)
                    for _ in range(12):
                        start = time.perf_counter()
                        view.state.move_right()
                        view._state_changed()
                        view.viewport().repaint()
                        app.processEvents()
                        timings.append((time.perf_counter() - start) * 1000)
            view.dispose()
            view.close()
            app.processEvents()
    ordered = sorted(timings)
    p95 = ordered[int(len(ordered) * 0.95) - 1]
    maximum = max(ordered)
    policy = tomllib.loads(
        (
            Path(__file__).parents[1] / "src/uniti/resources/performance_policy.toml"
        ).read_text()
    )["gates"]
    passed = (
        p95 < policy["interaction_p95_ms"]["fail"]
        and maximum < policy["interaction_max_ms"]["fail"]
    )
    return {
        "scenario": "mixed_script_navigation",
        "interactions": len(timings),
        "interaction_p95_ms": p95,
        "interaction_max_ms": maximum,
        "state": "PASS" if passed else "FAIL",
        "native_ime_qualified": False,
    }


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["state"] == "PASS" else 1)
