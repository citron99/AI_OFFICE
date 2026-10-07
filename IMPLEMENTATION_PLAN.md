# План реализации MVP «AI-офис собственника»

Версия плана: 0.1  
Основание: ТЗ V2.1 и Software Design / Technical Design v0.1  
Стартовое состояние: рабочая папка пуста, реализация начинается с нуля  
Плановый горизонт: 14 недель, 7 итераций по 2 недели  

## 1. Цель релиза

Реализовать внутреннее web-приложение, в котором собственник ставит задачу естественным языком, а оркестратор подключает AI-Бухгалтера, AI-Юриста и AI-Безопасника, собирает проверяемый результат и требует подтверждения для значимых действий.

Главный сквозной сценарий MVP:

> «Проверь договор и счёт нового подрядчика и скажи, можно ли готовить оплату».

Результат MVP должен содержать бухгалтерскую, юридическую и security-части, общий риск, источники, рекомендации и признак необходимости подтверждения. После approval разрешено создать только подтверждённый черновик действия; реальный платёж запрещён.

## 2. Границы MVP

В релиз входят:

- единый Web UI и API;
- Task Service, оркестратор и три агента;
- PostgreSQL 16+, pgvector, Redis и фоновый worker;
- загрузка PDF, DOCX, TXT, CSV и XLSX;
- Legal RAG на тестовых источниках;
- детерминированные финансовые расчёты;
- `AccountingProvider` и `Mock1CConnector` на синтетических данных;
- Validator, Policy Gate, approval workflow и аудит;
- журналирование LLM/tool-вызовов, токенов, стоимости и latency;
- Docker Compose, автоматические тесты и eval-наборы.

Не входят:

- реальные бухгалтерские и персональные данные;
- production-подключение к 1С;
- автономные платежи и иные необратимые действия;
- подписание договоров и юридическое представительство;
- инвестиционные агенты, брокеры и торговля.

## 3. Базовые технические решения

| Область | Решение для MVP |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2 |
| Persistence | PostgreSQL 16+, SQLAlchemy 2, Alembic, pgvector |
| Очередь | Redis + Celery worker |
| Frontend | React/Next.js; Streamlit допустим только для временного spike |
| Оркестрация | Собственная детерминированная state machine и DAG шагов |
| LLM | Claude через интерфейс `LLMProvider`; fake provider для тестов |
| Бухгалтерия | `AccountingProvider` + `Mock1CConnector` |
| Файлы | Локальное хранилище в dev с абстракцией под MinIO/S3 |
| RAG | pgvector, metadata filtering; hybrid search и reranker после базового retrieval |
| Наблюдаемость | Structured JSON logs, `trace_id` / `task_id` / `step_id`; OpenTelemetry по возможности |
| Развёртывание | Docker Compose и CI pipeline |

Правила, которые нельзя делегировать LLM:

- финансовая арифметика;
- права доступа и ACL;
- решения `ALLOW`, `DENY`, `REQUIRE_APPROVAL`;
- преобразование данных 1С в канонические модели;
- проверка допустимости переходов state machine;
- маскирование секретов и чувствительных значений в логах.

## 4. План по итерациям

### Итерация 0. Архитектурный baseline и критерии приёмки — недели 1–2

Задачи:

- `PLAN-001`: согласовать решения из раздела 5;
- `ARCH-001`: создать репозиторий, правила ветвления, линтеры, type-checking и pre-commit;
- `ARCH-002`: зафиксировать ADR по оркестрации, очереди, хранилищу файлов и LLM abstraction;
- `ARCH-003`: утвердить доменные enum, Pydantic-контракты, error codes и OpenAPI baseline;
- `ARCH-004`: описать state machine и таблицу разрешённых переходов;
- `SEC-001`: подготовить threat model, классы данных, RBAC и правила redaction;
- `QA-001`: превратить 17 критериев приёмки из ТЗ в трассируемую acceptance matrix;
- `DATA-001`: определить форматы и генераторы всех синтетических наборов.

Результат: согласованный технический baseline, пустой каркас проекта проходит CI, спорные решения не блокируют разработку.

### Итерация 1. Platform Core — недели 3–4

Задачи:

- `CORE-001`: структура приложения, конфигурация и dependency injection;
- `CORE-002`: Docker Compose: API, PostgreSQL/pgvector, Redis, worker и frontend;
- `DB-001`: миграции для `users`, `tasks`, `task_steps`, `messages`, `artifacts`, `agent_runs`, `tool_calls`, `model_calls`, `audit_events`;
- `API-001`: `/health`, `/ready`, Tasks API и унифицированные ошибки;
- `FILE-001`: безопасная загрузка файлов, MIME/signature validation, размерные лимиты, SHA-256 и storage abstraction;
- `TASK-001`: Task Service, persistence, cancellation, retry и идемпотентность;
- `ORCH-001`: router, planner, executor, aggregator и state machine skeleton;
- `LLM-001`: `LLMProvider`, `AnthropicProvider`, `FakeLLMProvider`, structured output validation;
- `AGENT-001`: `BaseAgent`, `DummyAgent`, единый `AgentResult`;
- `OBS-001`: correlation IDs, structured logs и учёт базовых метрик вызова.

Контрольная точка: `User -> API -> Task Service -> Orchestrator -> DummyAgent -> Result` работает через UI и E2E-тест.

### Итерация 2. AI-Юрист и Legal RAG — недели 5–6

Задачи:

- `RAG-001`: паспорт источника, статусы, версия, jurisdiction, effective dates, ACL и classification;
- `RAG-002`: парсеры PDF/DOCX/TXT и обработка ошибок извлечения;
- `RAG-003`: структурный chunking по разделу/статье/пункту с сохранением locator;
- `RAG-004`: embeddings, pgvector index, metadata filtering и vector retrieval;
- `RAG-005`: ingestion/search API и управление источниками;
- `LEGAL-001`: определение юрисдикции и переход в `WAITING_INPUT`, если её нельзя установить;
- `LEGAL-002`: `LawyerAgent`, `LegalResult`, цитирование и `LEGAL_SOURCE_NOT_FOUND`;
- `LEGAL-003`: защита от prompt injection в загруженных документах;
- `DATA-002`: 10–20 тестовых источников и минимум 10 договоров разных типов;
- `EVAL-001`: не менее 20 legal RAG вопросов с ожидаемыми source и locator.

Контрольная точка: UC-02 анализирует тестовый договор, показывает юрисдикцию, риски и проверяемые источники; при отсутствии источника не генерирует уверенный правовой вывод.

### Итерация 3. AI-Бухгалтер и абстракция 1С — недели 7–8

Задачи:

- `ACC-001`: канонические модели `Counterparty`, `Contract`, `Invoice`, `Payment`, `Transaction`, `AccountBalance`, `Receivable`, `Payable`;
- `ACC-002`: стабильный контракт `AccountingProvider` и capability flags для read/draft/write;
- `ACC-003`: `Mock1CConnector` и contract test suite, пригодный для будущего `Real1CConnector`;
- `ACC-004`: ON_DEMAND sync и журнал `accounting_sync_runs`;
- `FIN-001`: детерминированные P&L, Cash Flow, plan/fact, aging, compare periods и anomaly checks;
- `ACC-005`: `AccountantAgent` и `AccountingResult` с record IDs и методом расчёта;
- `API-002`: status, sync, counterparties, invoices и payments endpoints;
- `DATA-003`: 30 контрагентов, 20 договоров, 100 счетов, 100 платежей и 300 операций;
- `DATA-004`: сценарии duplicate invoice, overdue, changed bank details, incorrect VAT, missing contract и unusual amount.

Контрольная точка: UC-01 отвечает по синтетической бухгалтерии; все суммы воспроизводимы кодом, а замена mock-провайдера не требует изменения агента.

### Итерация 4. AI-Безопасник, Validator и Policy Gate — недели 9–10

Задачи:

- `SEC-002`: классификация данных, поиск ПДн и типов секретов без сохранения самих секретов;
- `SEC-003`: проверки получателя, внешней передачи, доступа и аномалий транзакций;
- `POL-001`: versioned policy rules с решениями `ALLOW`, `DENY`, `REQUIRE_APPROVAL`;
- `AGENT-002`: `SecurityAgent` как domain agent и control agent;
- `VAL-001`: проверка JSON schema, обязательных полей, citations, арифметики, risk и запрещённых действий;
- `SEC-004`: redaction во входах/выходах LLM, tool logs и audit metadata;
- `AUDIT-001`: append-only audit events и запрет прикладного редактирования;
- `DATA-005`: тесты с API key, паролем, ПДн, внешним e-mail, prompt injection и необычным платежом.

Контрольная точка: UC-03 обнаруживает все заложенные тестовые утечки; окончательное решение принимает Policy Gate, а не LLM.

### Итерация 5. Multi-agent flow и approvals — недели 11–12

Задачи:

- `ORCH-002`: DAG выполнения, зависимости, параллельный запуск и минимально необходимый контекст;
- `ORCH-003`: Lawyer и Accountant выполняются параллельно, Security получает их структурированные результаты;
- `ORCH-004`: aggregator формирует единый ответ без раскрытия chain-of-thought;
- `APR-001`: approval entity, payload hash, TTL, approve/reject и защита от повторного исполнения;
- `APR-002`: approval UI с описанием действия, изменениями, риском и инициатором;
- `ACC-006`: после approval создаётся только mock draft; реальный платёж отсутствует;
- `E2E-001..005`: отдельные сценарии Accountant, Lawyer, Security, Lawyer+Security и все три агента;
- `EVAL-002`: routing-набор: 20 accounting, 20 legal, 20 security, 20 mixed и 10 unsupported запросов.

Контрольная точка: главный сквозной сценарий проходит от загрузки договора и счёта до `WAITING_APPROVAL`, approve/reject и финального аудита.

### Итерация 6. UI, hardening и UAT — недели 13–14

Задачи:

- `UI-001`: Dashboard, Chat/Task, Task Trace и Approval screens;
- `UI-002`: источники, риски, предупреждения и статусы фонового выполнения;
- `OPS-001`: timeouts, retry policy, circuit breakers, dead-letter handling и graceful cancellation;
- `OPS-002`: метрики latency, error rate, token usage, cost и readiness;
- `QA-002`: unit, contract, integration, E2E, security и regression suites;
- `QA-003`: RAG/routing/agent eval gates в CI;
- `DOC-001`: README, runbook, API docs, data dictionary и инструкция по demo;
- `UAT-001`: демонстрация четырёх обязательных сценариев и закрытие acceptance matrix.

Результат: воспроизводимый MVP запускается одной командой через Docker Compose, проходит CI и готов к демонстрации на синтетических данных.

## 5. Решения, которые нужно принять до конца итерации 0

Блокирующие MVP:

1. Выбрать рабочий frontend: React/Next.js или сокращённый Streamlit-прототип.
2. Определить способ аутентификации и роли; минимально нужны `OWNER`, `ADMIN`, `SERVICE`.
3. Утвердить перечень test legal sources, правила их приоритета и владельца обновлений.
4. Утвердить первую версию policy matrix: классы данных, внешние получатели, финансовые пороги и approval rules.
5. Утвердить сроки хранения файлов, промптов, LLM payloads и audit logs.
6. Определить допустимые модели embeddings и требования к локализации данных.

Не блокируют MVP, но нужны до production-интеграции:

1. Версия, редакция и конфигурация 1С:Бухгалтерия.
2. Наличие тестового контура и способ интеграции: HTTP, OData, корпоративный сервис или файлы.
3. Размещение 1С и будущей рабочей инфраструктуры.
4. Нужны ли write-операции в первой рабочей версии после MVP.
5. Перечень стран СНГ и источники реальной нормативной базы.

## 6. Устранение расхождений между ТЗ и Software Design

1. **Интерфейс 1С.** ТЗ перечисляет balances, turnover и write-методы, а дизайн фиксирует более узкий read-контракт. Решение: общий versioned `AccountingProvider`, обязательный read-only профиль MVP и отдельные capability flags. Draft/write не смешивать с чтением.
2. **Frontend.** ТЗ допускает Streamlit или React/Next.js, дизайн не закрепляет выбор. Решение: React/Next.js для рабочего MVP; Streamlit использовать только как временный spike.
3. **Фоновые задачи.** ТЗ указывает Redis/Celery, а дизайн откладывает worker на следующую итерацию Docker Compose. Решение: включить worker в Platform Core, поскольку retry, cancellation и параллельные шаги являются частью MVP.
4. **Оркестрация.** ТЗ допускает LangGraph или собственную state machine; дизайн уже задаёт собственные модули. Решение: начать с собственной state machine и не вводить framework dependency без подтверждённой необходимости.
5. **Approval.** ТЗ допускает write-команды после approval, а дизайн запрещает реальный платёж в MVP. Решение: более безопасное ограничение дизайна имеет приоритет — approval создаёт только draft.
6. **API знаний.** В документах используются названия `documents` и `sources`. Решение: публично закрепить `/knowledge/sources`, а документ считать artifact, связанный с source.

## 7. Качество и release gates

Обязательные проверки:

- unit: Pydantic validation, state transitions, financial calculations, mapping, chunking и policy rules;
- contract: `AccountingProvider`, `LLMProvider`, `LegalRAGService`;
- integration: API + PostgreSQL, RAG + pgvector, Mock1C + Accountant, queue + retries;
- E2E: пять сценариев из Software Design;
- security: prompt injection, secret/PII leakage, ACL, external action, duplicate approval и log redaction;
- recovery: повтор после timeout, идемпотентность, cancellation и недоступность LLM/БД/provider.

Предлагаемые числовые пороги, которые нужно утвердить в итерации 0:

- 100% точность детерминированных финансовых расчётов на эталонных fixtures;
- 100% обнаружение заранее размеченных critical security cases;
- не менее 90% корректной маршрутизации на наборе из 90 запросов;
- 100% юридических существенных выводов имеют валидный source и locator;
- 0 разрешённых write-действий без действующего approval;
- 0 секретов и полных платёжных реквизитов в логах.

## 8. Команда и оценка

Оценка 14 недель предполагает:

- 2 backend/AI инженера;
- 1 frontend инженер;
- 1 QA/automation инженер;
- DevOps/Security по 0,25–0,5 ставки;
- бухгалтер и юрист как предметные эксперты на приёмке данных и eval-наборов;
- один владелец продукта, принимающий policy и scope-решения.

Для одного сильного full-stack/AI разработчика реалистичный диапазон — 24–32 недели без production-коннектора 1С.

## 9. Основные риски

| Риск | Мера снижения |
|---|---|
| Неопределённость реальной 1С | Не блокировать MVP; контрактные тесты и mock first |
| Недостоверные юридические ответы | Только контролируемые источники, metadata filter, citations, fail closed |
| Prompt injection в документах | Документы считать недоверенными данными; tool/policy enforcement вне LLM |
| Утечка данных через логи/LLM | Classification, минимальный контекст, redaction и запрет реальных данных |
| Ошибка маршрутизации | Eval-набор, confidence threshold и `WAITING_INPUT`/`UNSUPPORTED` |
| Повтор финансового действия | Idempotency key, payload hash, TTL и проверка результата после timeout |
| Рост стоимости/latency LLM | Лимиты, модель по типу шага, кэш безопасных операций, usage monitoring |
| Слишком широкий MVP | Главный multi-agent сценарий как приоритет; production 1С и инвестиции отдельно |

## 10. Критерий готовности MVP

Релиз разрешён, когда:

1. Все acceptance-критерии ТЗ связаны с тестами и закрыты.
2. Главный multi-agent E2E стабильно проходит на чистом окружении.
3. Каждый юридический вывод имеет источник либо возвращается `LEGAL_SOURCE_NOT_FOUND`.
4. Все бухгалтерские числа воспроизводятся детерминированными функциями.
5. Policy Gate блокирует запрещённые действия, approval нельзя обойти или повторить.
6. Task Trace и audit позволяют восстановить ход выполнения без chain-of-thought и без секретов.
7. Приложение запускается через Docker Compose и имеет рабочие `/health` и `/ready`.
8. Документация, demo dataset, eval-наборы и runbook находятся в репозитории.

## 11. Следующий этап после MVP

Production-коннектор 1С начинается отдельным проектным этапом только после стабилизации `AccountingProvider`, прохождения contract/E2E тестов на mock, получения тестового контура 1С и согласования read/write прав. Сначала реализуется read-only интеграция и mapping, затем — отдельно согласованные draft/write операции под approval. Инвестиционные агенты не должны добавляться до завершения этого этапа и hardening платформенного ядра.
