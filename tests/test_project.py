import json

from splitsville.project import (
    FORMAT,
    apply_lock_map,
    clear_locks,
    load_any,
    loads,
    measure_meta_list,
    new_document,
    pack_zip,
    unpack_zip,
)


def test_new_document_is_versioned_and_open_for_extra_keys():
    doc = new_document(name="Fire", extra={"guitar_pro_file": "/tmp/song.gp"})
    assert doc["format"] == FORMAT
    assert doc["version"] == 1
    assert doc["guitar_pro_file"] == "/tmp/song.gp"
    assert doc["project_meta"] == {}
    assert "meta" in measure_meta_list(1)[0]


def test_zip_roundtrip_preserves_media_and_locks():
    measures = measure_meta_list(2, ["A1", "A2"])
    measures[0]["locked"] = True
    measures[0]["status"] = "done"
    measures[0]["notes"] = "tabbed in GP"
    measures[0]["meta"]["gp_bar"] = 12
    doc = new_document(
        name="Demo",
        settings={"match_threshold": 0.85},
        analysis={"labels": ["A1", "A2"], "n": 2},
        measures=measures,
    )
    raw = pack_zip(doc, markers=b"XSC", stem=b"STEMDATA", markers_name="map.xsc", stem_name="bass.mp3")
    loaded, markers, stem = unpack_zip(raw)
    assert markers == b"XSC"
    assert stem == b"STEMDATA"
    assert loaded["measures"][0]["locked"] is True
    assert loaded["measures"][0]["meta"]["gp_bar"] == 12
    assert loaded["analysis"]["labels"] == ["A1", "A2"]
    again, m2, s2 = load_any(raw)
    assert m2 == markers and s2 == stem
    assert again["name"] == "Demo"


def test_bare_json_load_and_lock_merge():
    doc = new_document(name="N", measures=measure_meta_list(3, ["A", "B", "C"]))
    parsed = loads(json.dumps(doc))
    merged = apply_lock_map(parsed["measures"], {"1": {"locked": True, "status": "done", "notes": "ok"}})
    assert merged[1]["locked"] is True
    assert merged[1]["notes"] == "ok"
    assert merged[1]["label"] == "B"
    assert merged[0]["locked"] is False


def test_clear_locks_resets_done_without_dropping_notes():
    rows = measure_meta_list(2, ["A", "B"])
    rows[0]["locked"] = True
    rows[0]["status"] = "done"
    rows[0]["notes"] = "keep me"
    cleared = clear_locks(rows)
    assert cleared[0]["locked"] is False
    assert cleared[0]["status"] == "open"
    assert cleared[0]["notes"] == "keep me"
    assert cleared[1]["locked"] is False
