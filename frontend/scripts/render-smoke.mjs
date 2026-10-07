/* Смоук-тест рендеринга: App и feature-модули должны отрисоваться без исключений
   (пустые данные и данные фикстуры). Запуск: node scripts/render-smoke.mjs */
import {createServer} from "vite";
import {renderToString} from "react-dom/server";
import React from "react";

globalThis.fetch = async () =>
  new Response(JSON.stringify({code: "SMOKE_EMPTY"}), {status: 404});
// Минимальный DOM-стаб: main.jsx монтируется только при наличии #root.
globalThis.document = {getElementById: () => null};
globalThis.localStorage = {getItem: () => null, setItem: () => {}};

const vite = await createServer({
  root: new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"),
  server: {middlewareMode: true}, appType: "custom", logLevel: "error",
});

function assertTokens(html, tokens, label) {
  const missing = tokens.filter(token => !html.includes(token));
  if (missing.length) throw new Error(`${label}: не найдено в разметке — ${missing.join(", ")}`);
}

try {
  const api = async (path, options) => {
    if (path === "/legal/provider-status") {
      return {mode: "consultant_plus", status: "inactive", license_scope: []};
    }
    return {code: "SMOKE_EMPTY"};
  };
  const m = await vite.ssrLoadModule("/src/main.jsx");
  const app = renderToString(React.createElement(m.App));
  assertTokens(app, ["navbar", "AI-Офис собственника", "Рабочий стол", "skip-link"], "App (пустые данные)");

  const dashboard = await vite.ssrLoadModule("/src/features/dashboard/Dashboard.jsx");
  const financeReport = {
    currency: "RUB", current: {start: "2026-07-01", end: "2026-07-31", incoming: "1000", outgoing: "400", net: "600"},
    previous: {start: "2026-06-01", end: "2026-06-30", incoming: "900", outgoing: "500", net: "400"},
    total_receivable: "5000.00", total_outstanding: "2000.00", receivables_as_of: "2026-08-01",
    payables_as_of: "2026-08-01", receivable_aging: {not_due: "4400.00", "1_30": "600.00"},
    balances_as_of: "2026-08-01", total_bank_balance: "12000.00",
    receivables: [
      {receivable_id: "rec_1", counterparty_id: "vendor_north", due_on: "2026-06-01", received: "0", outstanding: "8275.00"},
      {receivable_id: "rec_2", counterparty_id: "vendor_old", due_on: "2026-05-01", received: "100", outstanding: "900.00"},
    ],
  };
  const dash = renderToString(React.createElement(dashboard.default, {
    tasks: [{task_id: "t", state: "running", run_usage: {observed_cost_rub: "1.5"}}],
    approvals: [{status: "pending"}], drafts: [], processQuality: {review_rate: 0.5, completed_tasks: 2},
    processControls: {postflight_coverage: 0.5, control_flags: {}, policy_decisions: {deny: 0}},
    finance: financeReport, onNavigate: () => {},
  }));
  assertTokens(dash, ["Доступные деньги", "Ожидаемые поступления", "Обязательства",
    "Просроченная дебиторка", "Mock1C", "vendor_north", "60+ ДНЕЙ"], "Dashboard");

  const approvalModal = await vite.ssrLoadModule("/src/features/approvals/ApprovalModal.jsx");
  const dialogElement = {showModal() {}, close() {}};
  const modal = renderToString(React.createElement(approvalModal.default, {
    record: {id: "a1", payload: {invoice_id: "inv_100", amount: "1331.00"}, payload_hash: "f".repeat(64),
      expires_at: "2099-01-01T00:00:00Z"},
    decision: "approve", busy: false,
    invoice: {id: "inv_100", number: "SYN-2026-100", counterparty_id: "vendor_north"},
    onClose: () => {}, onConfirm: () => {},
  }));
  assertTokens(modal, ["Payload Diff", "vendor_north", "не реальный платёж", "1331"], "ApprovalModal");

  const dag = await vite.ssrLoadModule("/src/features/tasks/TaskDagView.jsx");
  const dagHtml = renderToString(React.createElement(dag.default, {
    graph: {process_id: "proc_1", process_version: 3, nodes: [
      {id: "n1", kind: "agent_step", agent: "lawyer", state: "completed", readiness: "done",
        action: "Проверка договора", depends_on: [], blocked_by: []},
      {id: "n2", kind: "result_review", agent: "orchestrator", state: "waiting_approval",
        readiness: "waiting", action: "Решение собственника", depends_on: ["n1"], blocked_by: []},
    ]},
  }));
  assertTokens(dagHtml, ["Граф исполнения", "Проверка результата", "Юрист", "выполнено"], "TaskDagView");

  const legal = await vite.ssrLoadModule("/src/features/legal/LegalRagView.jsx");
  const legalHtml = renderToString(React.createElement(legal.default, {
    api, sources: [{id: "s1", title: "Тестовый регламент", jurisdiction: "LV", document_type: "test_norm",
      version: "demo-v1", chunk_count: 8, embedding_model: "mock-hash-v1", classification: "INTERNAL"}],
    writable: true,
  }));
  assertTokens(legalHtml, ["Юридический провайдер", "проверяем…", "Тестовый регламент"], "LegalRagView");

  const activity = await vite.ssrLoadModule("/src/features/activity/ActivityAuditView.jsx");
    const digestMod = await vite.ssrLoadModule("/src/features/dashboard/DailyOwnerDigest.jsx");
  const emptyDigestHtml = renderToString(React.createElement(digestMod.default, {tasks: []}));
  assertTokens(emptyDigestHtml, ["Ежедневная сводка", "ещё не завершался"], "DailyOwnerDigest(empty)");
  const digestHtml = renderToString(React.createElement(digestMod.default, {tasks: [{
    process: {id: "daily_cash_and_receivable_risk"},
    state: "completed",
    updated_at: "2026-09-12T09:00:00Z",
    result: {
      mode: "daily_owner_digest_v1",
      digest_date: "2026-09-12",
      watermark: "synthetic-accounting-rub-v7 @ 2026-09-12T09:00:00+00:00",
      cash_available: "3200000.00",
      cash_in: "151500", cash_out: "300000", net_cash_flow: "-148500",
      expected_receipts: "1215000", receivable_total: "1425000",
      receivable_aging: {"1_30": "945000", "not_due": "210000"},
      top_nonpayment_risks: [{
        counterparty_id: "cp_012", counterparty_name: "Supplier 12",
        outstanding: "945000", days_overdue: 12,
        explanation: "Просрочка 12 дн.", recommended_action: "Связаться с контрагентом",
      }],
      anomaly_count: 2, invoice_count: 102,
    },
  }]}));
  assertTokens(digestHtml,
    ["Доступно денег", "Топ рисков неплатежа", "Аномалий в счетах", "Связаться с контрагентом"],
    "DailyOwnerDigest(data)");

  const processes = await vite.ssrLoadModule("/src/features/processes/ProcessControlsView.jsx");
  const controlsHtml = renderToString(React.createElement(processes.default, {
    api: async () => { throw new Error("не должен вызываться при SSR"); },
    writable: false,
  }));
  assertTokens(controlsHtml,
    ["Управление процессами", "Загрузка…", "Процесс"],
    "ProcessControlsView (SSR до загрузки данных)");

const activityHtml = renderToString(React.createElement(activity.default, {
    trace: {steps: [{id: "s1", agent: "accountant", state: "completed", started_at: "2026-08-29T09:00:00Z"}],
      audit: [{id: "a1", event: "approval_requested", created_at: "2026-08-29T09:30:00Z"}]},
    activity: null, onRefresh: () => {},
  }));
  assertTokens(activityHtml, ["Журнал активности", "approval_requested"], "ActivityAuditView");

  console.log("SMOKE OK");
} catch (error) {
  console.error("SMOKE FAILED:", error.message);
  process.exitCode = 1;
} finally {
  await vite.close();
}
