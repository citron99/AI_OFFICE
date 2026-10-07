# Security model (D-08, ТЗ V2.1 разделы 10, 13.1)

## 1. RBAC-матрица

Роли назначаются только сервером (конфиг принципалов / приглашения);
публичная саморегистрация OWNER/ADMIN отсутствует. Для сессионного доступа
проверяется цепочка `user → membership → company → object → capability`.
Для `token`/`oidc` активные user, membership, company и refresh-сессия
проверяются при каждом защищённом API-запросе; logout и отключение членства
отзывают уже выданный access token. В `demo`/`api_key` источником прав остаётся
серверная конфигурация, а не refresh-сессия.

| Роль | Чтение | Изменение | Бизнес-approval | Проверено тестами |
| --- | --- | --- | --- | --- |
| OWNER | Все данные своей компании | Политики, процессы, расписания | Да (единственный) | test_office_workflow, test_company_isolation |
| ADMIN | Технические метаданные | Пользователи, конфигурация | **Нет** (APR-006) | test_admin_cannot_decide_business_approvals |
| ACCOUNTANT | Финансовый контур | Комментарии, черновики | Нет | grant matrix tests |
| LAWYER | Договоры, Legal RAG | Заключения, черновики | Нет | capability grants tests |
| SECURITY | Security metadata | Классификация, блокировки | Нет финансового approval | principals matrix |
| AUDITOR | Назначенный read-only | Нет | Нет | test_auth_isolation_and_read_only_role |

Гранты агентов: machine principals (`agt_*`) с матрицей least-privilege,
короткоживущие grants (TTL 15 мин) с scope company/task/step/policy_version;
проверка перед каждым обращением к данным. Бухгалтер никогда не получает
knowledge/attachments; postflight читает только структурированные результаты.

## 2. Карта потоков данных

```
1С (read-only) ──▶ AccountingProvider ──▶ Бухгалтер ─┐
КонсультантПлюс ─▶ ConsultantPlusProvider ──▶ Юрист ──┼─▶ Policy Gate ─▶ Owner UI
Вложения ────────▶ DLP+AV ─▶ Object storage ─▶ RAG ──┘        │
Пользовательский текст ─▶ Security preflight ─────────────────┤
                              Security postflight ────────────┘
Внешний LLM ◀── Data Egress Gateway (PUBLIC/INTERNAL only) ──┘
Журналы: audit_events, provider_calls, capability_grants,
consultant_plus_search_events, dead_letter_entries (PostgreSQL, append-only)
```

Единственный источник истины — PostgreSQL; Redis только очереди/локи.
Право и юриспруденция: КонсультантПлюс первичен, Legal RAG вспомогательный.

## 3. Классы данных и маршруты (ТЗ 10.2)

| Класс | Пример | Внешний LLM | Где проверяется |
| --- | --- | --- | --- |
| PUBLIC | Публичные нормы | Разрешён | egress allow |
| INTERNAL | Регламент без ПДн | Разрешён | egress allow |
| CONFIDENTIAL | Договор, аналитика | **Блок** (локальный контур) | test_egress_gateway |
| PERSONAL | ФИО, контакты | **Блок** (нужен утверждённый маршрут) | egress + classifier |
| RESTRICTED | Пароли, ключи, карты | **DENY + инцидент**, хранение запрещено | upload DLP, egress |

## 4. Threat model и контрмеры

| Угроза | Контрмера | Тест |
| --- | --- | --- |
| Prompt injection из текста/документов/RAG | Недоверенный контент сканируется preflight; инструкции из данных не расширяют инструменты; external analysis блокируется при detections | test_legal_analysis, SEC-API-* |
| Cross-company доступ (IDOR) | company scope в каждом запросе и каждой таблице; 404 через границу | test_company_isolation |
| Самоназначение OWNER/ADMIN | Роли из серверного конфига/IdP; для сессий роль и membership проверяются на каждый запрос | test_sessions, test_company_isolation |
| Утечка секретов во внешний LLM | Классификатор + Egress Gateway; блок до вызова; провайдер не вызывается | test_egress_gateway |
| Секреты в логах | redact/redact_payload; журналы хранят метаданные и хеши, не контент | test_accounting_policy |
| Replay approval / подмена payload | payload_hash, идемпотентное решение, INVALIDATED при изменении, срок действия | test_invalid_approval_never_creates_draft |
| Повторное проведение платежа | real_payment → OWNER_ONLY_OUTSIDE_AGENT; черновик ≠ платёж; API отклоняет действие | policy matrix, ACC-API-10 |
| Незаметная смена правил | Immutable snapshot процесса/политики в задаче; версии политики в грантах и approvals | process snapshot tests |
| Бесконечные повторы / silent fallback | Bounded retry/backoff, FAILED_SAFE, DLQ | test_graph_executor, test_reliability |
| Официоз из памяти модели | Обязательный КонсультантПлюс; WAITING_SOURCE/LEGAL_SOURCE_NOT_FOUND | test_consultant_plus_route |
| Вредоносные файлы | MIME/signature/zip-гейты, EICAR/исполняемые сигнатуры, DLP до записи | test_file_validation, test_artifact_lifecycle |

## 5. Ограничения MVP

- Полноценный SIEM/SOC и внешний антивирус вне MVP (ТЗ 1.4); интеграция — за
  интерфейсом `content_scan`/DLP.
- DLP извлекает текст XML из DOCX/XLSX с пределом 20 МиБ распакованного XML.
  PDF по-прежнему требует отдельного надёжного извлечения текста/OCR перед
  использованием с реальными конфиденциальными вложениями.
- Шифрование бакета — настройка инфраструктуры (SSE на MinIO/S3).
- Статические API-ключи отзываются заменой `AUTH_TOKEN_HASHES` и перезапуском;
  access token в режимах `token`/`oidc` привязан к активной refresh-сессии.
