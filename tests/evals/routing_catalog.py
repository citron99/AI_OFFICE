"""Routing evaluation set (TZ 13.1 ACC-02).

Closed table of realistic task inputs with the expected routing category.
Threshold: >=90% accuracy and zero critical misroutes, where a critical
misroute is a clearly single-domain message routed to a *different* single
domain (e.g. a payment request classified as LEGAL). Run standalone via
scripts/run_evals.py or as the parametrized pytest module.
"""

from app.models.enums import TaskCategory

# (id, text, requested_agent|None, expected_category, critical)
ROUTING_CASES: list[tuple[str, str, object, TaskCategory, bool]] = [
    # --- Accounting single-domain ---
    ("R-001", "Оплатить счёт 45 от поставщика", None, TaskCategory.ACCOUNTING, True),
    ("R-002", "Проверь счёт на дубли перед оплатой", None, TaskCategory.ACCOUNTING, True),
    ("R-003", "Сверь платежи по счёту за июль", None, TaskCategory.ACCOUNTING, True),
    ("R-004", "Доходы и расходы за квартал", None, TaskCategory.ACCOUNTING, True),
    ("R-005", "invoice 12 needs a duplicate check", None, TaskCategory.ACCOUNTING, True),
    ("R-006", "Найди платёж без счёта", None, TaskCategory.ACCOUNTING, True),
    ("R-007", "Какой расход самый большой за месяц", None, TaskCategory.ACCOUNTING, True),
    ("R-008", "Сверка поступлений по счетам", None, TaskCategory.ACCOUNTING, True),
    ("R-009", "Платёж завис в банке, проверь статус", None, TaskCategory.ACCOUNTING, True),
    ("R-010", "Проверить счёт и платежи по договору", None, TaskCategory.MIXED, False),
    # --- Legal single-domain ---
    ("R-011", "Проверь договор перед подписанием", None, TaskCategory.LEGAL, True),
    ("R-012", "Какое право применяется к договору", None, TaskCategory.LEGAL, True),
    ("R-013", "Юрист нужен: риск в договоре аренды", None, TaskCategory.LEGAL, True),
    ("R-014", "Проверь NDA на риски", None, TaskCategory.LEGAL, True),
    ("R-015", "contract needs a compliance review", None, TaskCategory.LEGAL, True),
    ("R-016", "Договор не соответствует закону?", None, TaskCategory.LEGAL, True),
    ("R-017", "Права и обязанности сторон по договору", None, TaskCategory.LEGAL, True),
    ("R-018", "Проверь договор с новым контрагентом", None, TaskCategory.LEGAL, True),
    ("R-019", "Согласуй пункт договора о неустойке", None, TaskCategory.LEGAL, True),
    ("R-020", "Счёт по договору: проверить оплату и условия", None, TaskCategory.MIXED, False),
    # --- Security single-domain ---
    ("R-021", "Проверь текст на секреты перед отправкой", None, TaskCategory.SECURITY, True),
    ("R-022", "Есть утечка персональных данных?", None, TaskCategory.SECURITY, True),
    ("R-023", "Проверь письмо на конфиденциальные данные", None, TaskCategory.SECURITY, True),
    ("R-024", "Проверить небезопасный шаблон договора", None, TaskCategory.MIXED, False),
    ("R-025", "Проверь на утечку номеров карт", None, TaskCategory.SECURITY, True),
    ("R-026", "Проверь файл на секреты и ключи", None, TaskCategory.SECURITY, True),
    ("R-027", "Проверь переписку на персональные данные", None, TaskCategory.SECURITY, True),
    ("R-028", "Есть ли секрет в отчёте", None, TaskCategory.SECURITY, True),
    ("R-029", "Проверь выгрузку на утечку ПДн", None, TaskCategory.SECURITY, True),
    ("R-030", "Проверь протокол на чувствительные данные", None, TaskCategory.SECURITY, True),
    # --- Mixed (multi-domain wording) ---
    ("R-031", "Проверь счёт и договор: оплата против условий", None, TaskCategory.MIXED, False),
    ("R-032", "Договор и платёж: сверить условия с суммой", None, TaskCategory.MIXED, False),
    ("R-033", "Проверь договор на риски и счёт на ошибки", None, TaskCategory.MIXED, False),
    ("R-034", "Право и платёж: законна ли задержка оплаты", None, TaskCategory.MIXED, False),
    ("R-035", "Юрист и бухгалтер: проверьте договор и счёт", None, TaskCategory.MIXED, False),
    ("R-036", "Секрет в счёте: проверить утечку", None, TaskCategory.MIXED, False),
    ("R-037", "Проверь договор и письмо на секреты", None, TaskCategory.MIXED, False),
    ("R-038", "Счёт с ошибкой и утечкой данных", None, TaskCategory.MIXED, False),
    ("R-039", "Договор плюс платёжка: полный аудит", None, TaskCategory.MIXED, False),
    ("R-040", "Проверить платёж, договор и безопасность данных", None, TaskCategory.MIXED, False),
    # --- Unsupported (no domain wording) ---
    ("R-041", "Привет", None, TaskCategory.UNSUPPORTED, False),
    ("R-042", "Что нового", None, TaskCategory.UNSUPPORTED, False),
    ("R-043", "Расскажи анекдот", None, TaskCategory.UNSUPPORTED, False),
    ("R-044", "Как погода", None, TaskCategory.UNSUPPORTED, False),
    ("R-045", "", None, TaskCategory.UNSUPPORTED, False),
    ("R-046", "спасибо", None, TaskCategory.UNSUPPORTED, False),
    ("R-047", "12345", None, TaskCategory.UNSUPPORTED, False),
    ("R-048", "напомни мне о встрече", None, TaskCategory.UNSUPPORTED, False),
    # --- Explicit agent selection overrides keywords ---
    ("R-049", "Счёт и договор", "accountant", TaskCategory.ACCOUNTING, False),
    ("R-050", "Счёт и договор", "lawyer", TaskCategory.LEGAL, False),
    ("R-051", "Счёт и договор", "security", TaskCategory.SECURITY, False),
    ("R-052", "Любой текст", "accountant", TaskCategory.ACCOUNTING, False),
    ("R-053", "Любой текст", "lawyer", TaskCategory.LEGAL, False),
    ("R-054", "Любой текст", "security", TaskCategory.SECURITY, False),
]


def routing_case_rows() -> list[dict]:
    return [
        {
            "id": case_id,
            "text": text,
            "requested_agent": requested_agent,
            "expected": expected.value,
            "critical": critical,
        }
        for case_id, text, requested_agent, expected, critical in ROUTING_CASES
    ]
