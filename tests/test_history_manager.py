"""Unit tests for history document conversion (ObjectId serialization)."""
from bson import ObjectId
from src.services.history_manager import convert_history_doc, _build_user_filter


def test_converts_top_level_objectid():
    oid = ObjectId()
    result = convert_history_doc({"_id": oid, "subject": "test"})
    assert result["_id"] == str(oid)


def test_converts_nested_objectids():
    oid = ObjectId()
    doc = {"_id": oid, "meta": {"ref": oid}, "items": [oid, {"deep": oid}]}
    result = convert_history_doc(doc)
    assert result["meta"]["ref"] == str(oid)
    assert result["items"][0] == str(oid)
    assert result["items"][1]["deep"] == str(oid)


def test_none_doc_returns_none():
    assert convert_history_doc(None) is None


def test_user_filter_admin_view():
    assert _build_user_filter(None) == {}


def test_user_filter_includes_system_entries():
    clause = _build_user_filter("user-1", include_system=True)
    assert "$or" in clause


def test_user_filter_exact_match():
    assert _build_user_filter("user-1", include_system=False) == {"user_id": "user-1"}
