"""Task service composition root: lifecycle, runner and rework collaborators."""

from app.services.task_lifecycle import TaskLifecycleMixin
from app.services.task_rework import TaskReworkMixin
from app.services.task_runner import TaskRunnerMixin


class TaskService(TaskLifecycleMixin, TaskRunnerMixin, TaskReworkMixin):
    """Public task API used by HTTP handlers, the scheduler and Celery workers."""
