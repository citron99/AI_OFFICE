import pytest

from app.core.exceptions import InvalidStateTransitionError
from app.models.enums import TaskState
from app.orchestrator.state_machine import validate_transition


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskState.QUEUED, TaskState.CLASSIFYING),
        (TaskState.CLASSIFYING, TaskState.PLANNING),
        (TaskState.PLANNING, TaskState.RUNNING),
        (TaskState.RUNNING, TaskState.COMPLETED),
    ],
)
def test_valid_transition(current: TaskState, target: TaskState) -> None:
    validate_transition(current, target)


def test_invalid_transition_is_blocked() -> None:
    with pytest.raises(InvalidStateTransitionError):
        validate_transition(TaskState.QUEUED, TaskState.COMPLETED)
