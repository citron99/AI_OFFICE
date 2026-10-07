from app.core.exceptions import InvalidStateTransitionError
from app.models.enums import TaskState

ALLOWED_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.DRAFT: {TaskState.QUEUED, TaskState.CANCELLED},
    TaskState.QUEUED: {TaskState.CLASSIFYING, TaskState.CANCELLED, TaskState.FAILED},
    TaskState.CLASSIFYING: {
        TaskState.PLANNING,
        TaskState.WAITING_INPUT,
        TaskState.CANCELLED,
        TaskState.FAILED,
    },
    TaskState.PLANNING: {TaskState.RUNNING, TaskState.CANCELLED, TaskState.FAILED},
    TaskState.RUNNING: {
        TaskState.WAITING_INPUT,
        TaskState.WAITING_SOURCE,
        TaskState.WAITING_APPROVAL,
        TaskState.COMPLETED,
        TaskState.CANCELLED,
        TaskState.FAILED,
        TaskState.FAILED_SAFE,
    },
    TaskState.WAITING_INPUT: {TaskState.QUEUED, TaskState.CANCELLED, TaskState.FAILED},
    # A missing external source is resumable: retry re-enters the queue.
    TaskState.WAITING_SOURCE: {TaskState.QUEUED, TaskState.CANCELLED, TaskState.FAILED},
    TaskState.WAITING_APPROVAL: {
        TaskState.RUNNING,
        TaskState.COMPLETED,
        TaskState.CANCELLED,
        TaskState.FAILED,
    },
    # A controlled safe stop keeps the run resumable from its checkpoint.
    TaskState.FAILED_SAFE: {TaskState.QUEUED, TaskState.CANCELLED},
    TaskState.COMPLETED: set(),
    TaskState.FAILED: set(),
    TaskState.CANCELLED: set(),
}


def validate_transition(current: TaskState, target: TaskState) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidStateTransitionError(current.value, target.value)
