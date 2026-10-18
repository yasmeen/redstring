import json

from redstring import config
from redstring import extract


def test_reference_import_merges_persists_successes_and_skips_bad_rows(tmp_path, monkeypatch, capsys):
    input_path = tmp_path / "export.json"
    references_path = tmp_path / "references.json"
    proposed_path = tmp_path / "proposed.json"
    input_path.write_text(json.dumps([
        {"url": "https://example.test/existing", "analysis": "existing"},
        {"url": "https://example.test/one", "analysis": "first"},
        {"url": "https://example.test/bad", "analysis": "bad"},
        {"url": "https://example.test/two", "analysis": "second"},
    ]))
    references_path.write_text(json.dumps([{"id": "ref_001", "url": "https://example.test/existing"}]))
    proposed_path.write_text(json.dumps([{"name": "Existing proposal", "reference": "old"}]))
    monkeypatch.setattr(config, "REFERENCES_PATH", references_path)
    monkeypatch.setattr(extract, "PROPOSED_PATH", proposed_path)
    monkeypatch.setattr(extract.references, "load_vocab", lambda: {"techniques": []})
    monkeypatch.setattr(extract, "_models", lambda _: object())

    def fake_extract_one(_client, analysis, _vocab, _schema):
        if analysis == "bad":
            raise ValueError("bad row")
        if analysis == "second":
            assert "https://example.test/one" in references_path.read_text()
        return {
            "technique_ids": ["tr_whip_pan"],
            "proposed": [{"name": f"Proposal for {analysis}", "category": "Kids art", "why": "test"}],
        }

    monkeypatch.setattr(extract, "extract_one", fake_extract_one)
    result = extract.import_references(input_path, limit=4, client=object())

    references = json.loads(references_path.read_text())
    proposed = json.loads(proposed_path.read_text())
    assert result == {"references": 3, "proposed": 3, "added": 2}
    assert [reference["url"] for reference in references] == [
        "https://example.test/existing",
        "https://example.test/one",
        "https://example.test/two",
    ]
    assert references[1]["id"] == "ref_002"
    assert proposed[0]["name"] == "Existing proposal"
    assert "Skipping import row 3 (https://example.test/bad)" in capsys.readouterr().err
