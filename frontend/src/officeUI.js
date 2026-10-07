export const money = value => new Intl.NumberFormat("ru-RU", {
  style: "currency", currency: "RUB", maximumFractionDigits: 0,
}).format(Number(value || 0));

export const stateLabels = {
  queued: "В очереди", classifying: "Маршрутизация", planning: "Планирование",
  running: "В работе", waiting_input: "Нужны сведения", waiting_approval: "На согласовании",
  completed: "Завершено", failed: "Ошибка", cancelled: "Отменено", pending: "Ожидает",
  approved: "Одобрено", rejected: "Отклонено", expired: "Срок истёк",
};

export const agentLabels = {
  accountant: "Бухгалтер", lawyer: "Юрист", security: "Безопасность", orchestrator: "Оркестратор",
};

export const agentAccent = {
  accountant: "emerald", lawyer: "sky", security: "violet", orchestrator: "indigo",
};

export const activeTaskStates = new Set(["queued", "classifying", "planning", "running"]);

export function stateLabel(value) {
  return stateLabels[value] || value || "Нет статуса";
}

export function formatDate(value, options = {dateStyle: "medium", timeStyle: "short"}) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("ru-RU", options);
}

export function riskSnapshot({tasks = [], approvals = [], controls = null, finance = null}) {
  const failed = tasks.filter(task => task.state === "failed").length;
  const attention = tasks.filter(task => ["waiting_input", "waiting_approval"].includes(task.state)).length;
  const pendingApprovals = approvals.filter(item => item.status === "pending").length;
  const denied = Number(controls?.policy_decisions?.deny || 0);
  const outstanding = Number(finance?.total_receivable || 0) + Number(finance?.total_outstanding || 0);
  const overdue = Object.entries(finance?.receivable_aging || {})
    .filter(([bucket]) => bucket !== "not_due")
    .reduce((total, [, amount]) => total + Number(amount || 0), 0);
  const overdueWeight = outstanding > 0 ? Math.min(25, Math.round((overdue / outstanding) * 25)) : 0;
  const score = Math.min(100, failed * 28 + attention * 9 + pendingApprovals * 7 + denied * 12 + overdueWeight);
  const level = score >= 70 ? "critical" : score >= 40 ? "high" : score >= 20 ? "medium" : "low";
  return {score, level, failed, attention, pendingApprovals, denied, overdue, outstanding};
}
