"""密码哈希测试。"""

from __future__ import annotations

from toolhive.services.security.password import (
    generate_temp_password,
    hash_password,
    validate_password_strength,
    verify_password,
)


class TestHashAndVerify:
    """哈希与校验。"""

    def test_hash_returns_different_from_input(self) -> None:
        h = hash_password("MySecurePassword123")
        assert h != "MySecurePassword123"
        assert h.startswith("$argon2id$")

    def test_verify_correct_password(self) -> None:
        h = hash_password("CorrectPassword456")
        is_valid, _ = verify_password("CorrectPassword456", h)
        assert is_valid is True

    def test_verify_wrong_password(self) -> None:
        h = hash_password("CorrectPassword456")
        is_valid, _ = verify_password("WrongPassword", h)
        assert is_valid is False

    def test_verify_different_hashes_for_same_password(self) -> None:
        """独立随机盐：相同密码应产生不同哈希。"""
        h1 = hash_password("SamePassword")
        h2 = hash_password("SamePassword")
        assert h1 != h2

    def test_needs_rehash_default_false(self) -> None:
        """默认 Argon2id 参数应通过检查（不触发 rehash）。"""
        h = hash_password("ValidPassword")
        _, needs_rehash = verify_password("ValidPassword", h)
        assert needs_rehash is False


class TestPasswordStrength:
    """密码强度校验。"""

    def test_too_short(self) -> None:
        violations = validate_password_strength("Abc1", "testuser")
        assert any("长度" in v for v in violations)

    def test_contains_account(self) -> None:
        violations = validate_password_strength("MyTestuser123!", "testuser")
        assert any("账号" in v for v in violations)

    def test_contains_external_id(self) -> None:
        violations = validate_password_strength(
            "EMP999Secret!", "testuser", "EMP999",
        )
        assert any("工号" in v for v in violations)

    def test_common_password(self) -> None:
        violations = validate_password_strength("password", "testuser")
        assert any("常见" in v for v in violations)

    def test_valid_password(self) -> None:
        violations = validate_password_strength("Str0ng!Unique$Pass", "testuser")
        assert len(violations) == 0


class TestTempPassword:
    """临时密码生成。"""

    def test_generate_length(self) -> None:
        pwd = generate_temp_password()
        assert len(pwd) >= 12

    def test_generate_randomness(self) -> None:
        """连续生成的密码应不同。"""
        pwds = {generate_temp_password() for _ in range(10)}
        assert len(pwds) == 10
