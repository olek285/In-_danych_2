from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from kyb.storage import BronzeStore, make_envelope

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "inspect_sources.py"
spec = importlib.util.spec_from_file_location("inspect_sources", SCRIPT)
inspect_sources = importlib.util.module_from_spec(spec)
sys.modules["inspect_sources"] = inspect_sources
spec.loader.exec_module(inspect_sources)


def test_shape_merges_list_items_and_keeps_examples():
    shape = inspect_sources.Shape()
    shape.observe({"a": [{"x": 1}, {"y": "t"}], "b": None})
    shape.observe({"a": [], "b": "v"})
    out: list[str] = []
    inspect_sources.render_flat(shape, "", 40, out)
    assert "a[].x = int  e.g. 1" in out
    assert "a[].y = str  e.g. 't'" in out
    assert "b = null|str  e.g. 'v'" in out


def test_inspector_reads_bronze_without_network(tmp_path, capsys):
    store = BronzeStore(tmp_path)
    store.write_part("vat_whitelist", [
        make_envelope("vat_whitelist", "1,2", "https://x/1,2", 200, "<html>Request unsuccessful</html>"),
        make_envelope("vat_whitelist", "1,2", "https://x/1,2", 200,
                      json.dumps({"result": {"entries": [{"identifier": "1", "subjects": []}]}})),
    ])
    inspect_sources.main(["--source", "vat_whitelist", "--bronze", str(tmp_path), "--flat"])
    out = capsys.readouterr().out
    assert "NOT JSON (HTML page)" in out  # a WAF page is visible as such
    assert "result.entries[].identifier = str  e.g. '1'" in out
