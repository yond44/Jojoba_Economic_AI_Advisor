"""Unit tests for password hashing utilities."""
from src.utils.security import hash_password, verify_password


def test_hash_and_verify_roundtrip():
    hashed = hash_password("s3cret-password")
    assert hashed != "s3cret-password"
    assert verify_password("s3cret-password", hashed)


def test_wrong_password_fails():
    hashed = hash_password("correct-password")
    assert not verify_password("wrong-password", hashed)


def test_invalid_hash_returns_false_instead_of_raising():
    assert verify_password("anything", "not-a-valid-bcrypt-hash") is False


def test_same_password_produces_different_hashes():
    assert hash_password("password") != hash_password("password")
