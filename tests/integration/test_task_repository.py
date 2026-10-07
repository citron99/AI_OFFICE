from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import create_session_factory
from app.models.enums import TaskState
from app.models.task import TaskCreate
from app.repositories.tasks import TaskRepository


async def test_task_repository_round_trip(engine: AsyncEngine) -> None:
    factory = create_session_factory(engine)
    async with factory() as session:
        repository = TaskRepository(session)
        task = await repository.create(
            user_id="usr_test",
            payload=TaskCreate(message="Проверь договор"),
            company_id="comp_demo",
        )
        await session.commit()
        loaded = await repository.get(task.id)
        assert loaded is not None
        assert loaded.state == TaskState.QUEUED.value
        assert loaded.input_text == "Проверь договор"
