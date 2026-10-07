import React, {useEffect, useMemo, useRef, useState} from "react";

const labels = {dashboard: "Дашборд", tasks: "Рабочий стол", finance: "Бухгалтерия", approvals: "Согласования", knowledge: "Legal RAG", dag: "Граф выполнения", thread: "Стенограмма агентов", activity: "Журнал активности", consultation: "Консилиум"};

export default function CommandPalette({open, onClose, onNavigate, tasks, approvals, onOpenTask, onRefresh}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef(null);
  const items = useMemo(() => {
    const navigation = Object.entries(labels).map(([id, title]) => ({id: `nav-${id}`, group: "Навигация", title, hint: "Открыть раздел", run: () => onNavigate(id)}));
    const actions = [{id: "refresh", group: "Действия", title: "Обновить данные", hint: "Текущие API", run: onRefresh}];
    const taskItems = tasks.slice(0, 12).map(task => ({id: task.task_id, group: "Задачи", title: task.result?.summary || task.category || "Задача", hint: `…${task.task_id.slice(-8)} · ${task.state}`, run: () => onOpenTask(task)}));
    const approvalItems = approvals.filter(item => item.status === "pending").map(item => ({id: `approval-${item.id}`, group: "Согласования", title: `Согласование ${item.payload?.invoice_id || item.id}`, hint: "Открыть очередь решений", run: () => onNavigate("approvals")}));
    const needle = query.trim().toLocaleLowerCase("ru");
    return [...actions, ...navigation, ...taskItems, ...approvalItems].filter(item => `${item.title} ${item.hint} ${item.group}`.toLocaleLowerCase("ru").includes(needle));
  }, [query, tasks, approvals, onNavigate, onOpenTask, onRefresh]);
  useEffect(() => { if (!open) return undefined; setQuery(""); setActive(0); const timer = window.setTimeout(() => inputRef.current?.focus(), 0); return () => window.clearTimeout(timer); }, [open]);
  useEffect(() => { if (!open) return undefined; function keydown(event) { if (event.key === "Escape") { event.preventDefault(); onClose(); } if (event.key === "ArrowDown") { event.preventDefault(); setActive(index => Math.min(index + 1, Math.max(items.length - 1, 0))); } if (event.key === "ArrowUp") { event.preventDefault(); setActive(index => Math.max(index - 1, 0)); } if (event.key === "Enter" && items[active]) { event.preventDefault(); items[active].run(); onClose(); } } window.addEventListener("keydown", keydown); return () => window.removeEventListener("keydown", keydown); }, [open, active, items, onClose]);
  if (!open) return null;
  return <div className="palette-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}><section className="command-palette" role="dialog" aria-modal="true" aria-label="Палитра команд">
    <header><span>⌘</span><input ref={inputRef} value={query} onChange={event => {setQuery(event.target.value); setActive(0);}} placeholder="Команда, раздел или задача…" /><kbd>Esc</kbd></header>
    <div className="palette-list">{items.map((item, index) => <button key={item.id} className={active === index ? "is-active" : ""} onMouseEnter={() => setActive(index)} onClick={() => {item.run(); onClose();}}><small>{item.group}</small><b>{item.title}</b><span>{item.hint}</span></button>)}
      {!items.length && <div className="ops-empty">Команд не найдено.</div>}</div><footer><span>↑↓ выбрать</span><span>↵ открыть</span><span>Ctrl/Cmd + K</span></footer>
  </section></div>;
}
