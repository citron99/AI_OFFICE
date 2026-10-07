# Исполняемый граф процесса (ProcessDefinition V2)

Офис организован вокруг зависимостей задачи, а не фиксированной очереди
«отделов». `ProcessDefinitionV2` — серверный, неизменяемый контракт: он
задаёт node ID, исполнителя, тип результата, retry-политику и `RunBudget`.
Его JSON-снимок сохраняется в `TaskRecord` до первого шага.

`TaskStepRecord` — материализованный узел одного запуска: в нём есть
стабильный `node_id`, зависимости, номер попытки и безопасно отредактированный
результат. `GraphExecutor` выбирает все готовые узлы слоя, сервис атомарно
переводит их из `queued` в `running`, а независимые корни выполняются
параллельно. Так бухгалтерский снимок и security preflight не зависят друг от
друга; Юрист зависит от preflight; postflight всегда замыкает ветвь до Policy
Engine.

The office payment-draft flow includes two distinct security nodes:

- `security_preflight` scans untrusted request and attachment content before a
  legal provider can receive it;
- `security_postflight` depends on accountant, preflight, and lawyer nodes. It
  scans only selected structured control fields (never raw document text),
  records bank-detail and counterparty control flags, and completes before the
  policy decision and any draft creation.

До записи плана валидатор отклоняет повторяющиеся ID, неизвестные зависимости
и циклы. Исполнитель дополнительно проверяет, что выход агента соответствует
контракту `AccountingResult`, `LegalResult`, `SecurityResult` или `AgentResult`.

## Бюджет и остановка

`RunBudget` лимитирует число шагов, LLM-вызовов, циклов доработки, секунды
выполнения, входные/выходные токены и стоимость в рублях. До старта узла
резервируются объявленные LLM-вызовы и рублёвая оценка; после него фиксируется
фактическая telemetry. Если достигнут стоп-лимит, задача переходит в
`waiting_input` с результатом `waiting_human`, а не маскируется под ошибку.
Это решение может принять только владелец.

## ResultReview и доработка

`ResultReview` неизменяем и отделён от технического состояния запуска.
Для `rework_required` владелец обязан выбрать `target_node_ids`. Система
создаёт новый дочерний task с ссылкой на исходный, номером цикла и тем же
снимком процесса. Повторно запускаются выбранные узлы, их downstream и только
те upstream security/data-узлы, без которых ветвь нельзя безопасно выполнить.
Исходный результат и его review никогда не переписываются.

Первый регулярный процесс — `daily_cash_and_receivable_risk`; он доступен
через `POST /api/v1/tasks/daily-cash-and-receivable-risk`. После
`accounting_snapshot` параллельно выполняются `cash_control` и
`receivable_risk`; затем проходит security postflight и review владельца.

`GET /api/v1/tasks/{task_id}/process-graph` projects the stored graph for its
owner. Each node has a state and a derived readiness:

- `ready` — all dependencies are completed;
- `blocked` — at least one dependency is incomplete, with `blocked_by` IDs;
- `running`, `completed`, `failed`, and `cancelled` mirror durable execution
  state.

For tasks with a `ProcessDefinition`, the projection also includes the virtual
`result_review` node. It becomes `ready` only once the task has a completed
result, and becomes `completed` only after the immutable ResultReview is
stored. It is a human gate: it never executes a payment, creates a draft, or
changes the task result.

UI показывает этот граф вместе с результатом и audit trace. Очередь Celery по-
прежнему доставляет только ID задачи; логика готовности графа не привязана к
FastAPI, Celery или конкретному LLM-провайдеру.

`GET /api/v1/processes/controls` is the owner-scoped operational read-model for
the same flow. It reports completed office results, postflight coverage, policy
decisions, and aggregate control flags for a bounded time window. It never
returns source text, credentials, accounting requisites, or task payloads.
