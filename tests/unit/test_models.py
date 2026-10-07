import pytest
from pydantic import ValidationError

from app.models.enums import AgentType, TaskState
from app.models.task import TaskCreate


def test_task_create_has_safe_defaults() -> None:
    task = TaskCreate(message="Проверь договор")
    assert task.attachment_ids == []
    assert task.requested_agent is None


def test_task_create_rejects_empty_message() -> None:
    with pytest.raises(ValidationError):
        TaskCreate(message="")


def test_task_create_rejects_whitespace() -> None:
    with pytest.raises(ValidationError):
        TaskCreate(message="  \n  ")


def test_public_enums_are_stable_strings() -> None:
    assert AgentType.LAWYER.value == "lawyer"
    assert TaskState.WAITING_APPROVAL.value == "waiting_approval"
