import {createServer} from "node:http";

const now = "2026-08-29T09:30:00Z";
const task = {
  task_id: "task_visual_review_001", state: "waiting_approval", category: "mixed",
  risk_level: "high", created_at: now, updated_at: now, completed_at: null,
  result: {
    mode: "office", summary: "Проверка завершена: найдено два риска, действие ожидает решения собственника.",
    requires_approval: true, approval_id: "approval_visual_001", policy_decision: "require_approval",
    policy_reasons: ["Новый контрагент", "Запрошен черновик платежа"], warnings: ["Данные синтетические."],
    accounting: {paid: "0.00", outstanding: "1331.00"},
    findings: [{risk_level: "high", title: "Не подтверждены реквизиты контрагента",
      description: "Перед подготовкой черновика требуется независимая сверка банковских реквизитов.",
      citations: [{title: "Правило проверки поставщика", locator: "раздел 3"}]}],
    legal: {summary: "Представленного источника достаточно только для тестового вывода.",
      evidence_assessment: {status: "sufficient"}, unresolved_questions: [], warnings: ["Не юридическая консультация."],
      evidence: [{chunk_id: "chunk_1", title: "Тестовый регламент", locator: "п. 3.2",
        text: "Банковские реквизиты нового поставщика проверяются до подготовки черновика.",
        jurisdiction: "LV", version: "demo-v1"}]},
  },
};
const responses = {
  "/api/v1/me": {user_id: "owner_visual", role: "owner"},
  "/api/v1/tasks": [task,
    {...task, task_id: "task_visual_review_002", state: "completed", category: "accounting",
      risk_level: "low", result: {summary: "Счёт проверен, критических отклонений нет.", warnings: []}}],
  "/api/v1/accounting/invoices": [
    {id: "inv_100", number: "SYN-2026-100", counterparty_id: "vendor_north", due_on: "2026-09-05", gross: "1331.00"},
    {id: "inv_004", number: "SYN-2026-004", counterparty_id: "vendor_changed_bank", due_on: "2026-08-15", gross: "8275.00"},
  ],
  "/api/v1/approvals": [{id: "approval_visual_001", task_id: task.task_id, status: "pending",
    expires_at: "2099-08-29T12:00:00Z", payload_hash: "f".repeat(64),
    payload: {invoice_id: "inv_100", amount: "1331.00"}}],
  "/api/v1/drafts": [],
  "/api/v1/knowledge/sources": [{id: "source_visual_001", title: "Тестовый регламент проверки поставщика",
    jurisdiction: "LV", version: "demo-v1", chunk_count: 8, embedding_model: "mock-hash-v1"}],
  "/api/v1/processes/quality": {completed_tasks: 2, reviewed_results: 1, review_rate: 0.5, pending_reviews: 1},
  "/api/v1/processes/controls": {postflight_completed: 1, office_results: 2, postflight_coverage: 0.5,
    control_flags: {}, policy_decisions: {allow: 2, deny: 0, require_approval: 1}},
  "/api/v1/activity": {
    steps: [{id: "step_1", task_id: task.task_id, agent: "accountant", state: "completed",
      attempt: 0, started_at: now, completed_at: now, error_code: null}],
    audit: [{id: "audit_1", task_id: task.task_id, event: "approval_requested",
      details: {approval_id: "approval_visual_001"}, created_at: now}],
  },
  "/api/v1/legal/provider-status": {mode: "consultant_plus", status: "ok", license_scope: {
    jurisdictions: ["DE", "LV", "RU"], allowed_channels: ["mock_licensed_export"],
    scope_owner: "MVP synthetic integration owner", valid_until: null,
  }},
  [`/api/v1/tasks/${task.task_id}`]: task,
  [`/api/v1/tasks/${task.task_id}/trace`]: {steps: [
    {id: "step_1", agent: "accountant", state: "completed"},
    {id: "step_2", agent: "lawyer", state: "completed"},
    {id: "step_3", agent: "security", state: "completed"}],
    audit: [{id: "audit_1", event: "approval_requested", created_at: now}]},
  [`/api/v1/tasks/${task.task_id}/process-graph`]: {
    process_id: "proc_visual_001", process_version: 3, nodes: [
      {id: "node_classify", kind: "agent_step", agent: "orchestrator", state: "completed",
        readiness: "done", action: "Маршрутизация запроса", depends_on: [], blocked_by: []},
      {id: "node_accounting", kind: "agent_step", agent: "accountant", state: "completed",
        readiness: "done", action: "Сверка счёта и оплаты", depends_on: ["node_classify"], blocked_by: []},
      {id: "node_legal", kind: "agent_step", agent: "lawyer", state: "completed",
        readiness: "done", action: "Проверка договора и оснований", depends_on: ["node_classify"], blocked_by: []},
      {id: "node_security", kind: "agent_step", agent: "security", state: "completed",
        readiness: "done", action: "Проверка контрагента по политике", depends_on: ["node_legal"], blocked_by: []},
      {id: "node_review", kind: "result_review", agent: "orchestrator", state: "waiting_approval",
        readiness: "waiting", action: "Решение собственника", depends_on: ["node_accounting", "node_legal"], blocked_by: []},
    ]},
};
const server = createServer((request, response) => {
  response.setHeader("Content-Type", "application/json; charset=utf-8");
  if (request.method !== "GET" || !(request.url in responses)) {
    response.statusCode = 405;
    response.end(JSON.stringify({code: "VISUAL_FIXTURE_READ_ONLY"}));
    return;
  }
  response.end(JSON.stringify(responses[request.url]));
});
server.listen(5174, "127.0.0.1", () => console.log("UI fixture API: http://127.0.0.1:5174"));
