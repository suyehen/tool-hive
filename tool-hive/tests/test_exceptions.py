"""异常体系测试。"""

from __future__ import annotations

import pytest

from toolhive.core.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ServiceUnavailableError,
    ToolHiveError,
    ValidationError,
)


class TestToolHiveError:
    """基类异常测试。"""

    def test_is_exception(self) -> None:
        assert issubclass(ToolHiveError, Exception)

    def test_can_raise_and_catch(self) -> None:
        with pytest.raises(ToolHiveError):
            raise ToolHiveError("base error")

    def test_message_accessible(self) -> None:
        err = ToolHiveError("test message")
        assert str(err) == "test message"


class TestExceptionHierarchy:
    """所有异常应是 ToolHiveError 的子类。"""

    @pytest.mark.parametrize(
        "exc_class",
        [
            AuthenticationError,
            PermissionDeniedError,
            ValidationError,
            NotFoundError,
            ConflictError,
            ServiceUnavailableError,
        ],
    )
    def test_is_subclass_of_toolhive_error(self, exc_class: type) -> None:
        assert issubclass(exc_class, ToolHiveError)


class TestExceptionSpecificity:
    """兄弟异常之间不应是父子关系。"""

    def test_auth_not_catch_validation(self) -> None:
        try:
            raise ValidationError("bad")
        except AuthenticationError:
            pytest.fail("AuthenticationError should not catch ValidationError")
        except ValidationError:
            pass

    def test_not_found_not_catch_conflict(self) -> None:
        try:
            raise ConflictError("dup")
        except NotFoundError:
            pytest.fail("NotFoundError should not catch ConflictError")
        except ConflictError:
            pass
