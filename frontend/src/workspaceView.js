export const categories = {
  accounting: "Бухгалтерская проверка", legal: "Юридический анализ",
  security: "Проверка безопасности", mixed: "Комплексная проверка",
  general: "Общая задача", unknown: "Задача",
};
export const activeStates = ["queued", "classifying", "planning", "running"];
export function filterTasks(tasks, query, filter) {
  const needle = query.trim().toLocaleLowerCase("ru");
  return tasks.filter(task => {
    const group = filter === "all" ||
      (filter === "active" && activeStates.includes(task.state)) ||
      (filter === "attention" && ["waiting_input", "waiting_approval", "failed"].includes(task.state));
    const text = [task.task_id, task.category, categories[task.category]].join(" ").toLocaleLowerCase("ru");
    return group && text.includes(needle);
  });
}
export function filterInvoices(invoices, query) {
  const needle = query.trim().toLocaleLowerCase("ru");
  return invoices.filter(i => [i.id, i.number, i.counterparty_id].join(" ").toLocaleLowerCase("ru").includes(needle));
}
