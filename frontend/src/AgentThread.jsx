import React, {useMemo, useState} from "react";
import {agentLabels, formatDate, stateLabel} from "./officeUI";

export default function AgentThread({trace}) {
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const messages = useMemo(() => {
    if (!trace) return [];
    const steps = (trace.steps || []).map(step => ({
      id: `step-${step.id}`, kind: "agent", agent: step.agent, title: step.node_id || agentLabels[step.agent] || step.agent,
      detail: `${stateLabel(step.state)} · попытка ${step.attempt || 0}`, timestamp: step.completed_at || step.started_at,
      raw: `${step.node_id || ""} ${step.agent || ""} ${step.state || ""}`,
    }));
    const audit = (trace.audit || []).map(event => ({
      id: `audit-${event.id}`, kind: "audit", agent: "orchestrator", title: event.event,
      detail: Object.keys(event.details || {}).length ? JSON.stringify(event.details) : "Событие сохранено в журнале",
      timestamp: event.created_at, raw: `${event.event} ${JSON.stringify(event.details || {})}`,
    }));
    return [...steps, ...audit].sort((a, b) => new Date(a.timestamp || 0) - new Date(b.timestamp || 0));
  }, [trace]);
  const visible = messages.filter(message => (filter === "all" || message.agent === filter) && message.raw.toLocaleLowerCase("ru").includes(query.toLocaleLowerCase("ru")));
  if (!trace) return <div className="ops-empty">Выберите задачу, чтобы открыть стенограмму её исполнения.</div>;
  return <section className="ops-panel agent-thread" aria-label="Стенограмма агентов">
    <div className="ops-panel-head"><div><span className="eyebrow">AGENT THREAD · TRACE {trace.trace_id?.slice(-8)}</span><h3>Диалог агентов и системы</h3>
      <p>Хронология основана на сохранённых шагах и audit events; это не сгенерированная демонстрация.</p></div><span className="pill">{messages.length} событий</span></div>
    <div className="thread-tools"><div className="segmented" role="group" aria-label="Фильтр агентов">
      {["all", "accountant", "lawyer", "security", "orchestrator"].map(key => <button key={key} aria-pressed={filter === key} onClick={() => setFilter(key)}>{key === "all" ? "Все" : agentLabels[key]}</button>)}</div>
      <label className="thread-search"><span className="sr-only">Поиск в протоколе</span><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Поиск по протоколу" /></label></div>
    <ol className="thread-list">{visible.map(message => <li key={message.id} className={`thread-message agent-${message.agent}`}>
      <span className="thread-avatar">{message.kind === "audit" ? "◌" : (agentLabels[message.agent] || "А").slice(0, 1)}</span>
      <article><header><b>{message.kind === "audit" ? "Система аудита" : agentLabels[message.agent] || message.agent}</b><time>{formatDate(message.timestamp)}</time></header>
        <strong>{message.title}</strong><p>{message.detail}</p></article></li>)}</ol>
    {!visible.length && <div className="ops-empty">В этой части протокола совпадений нет.</div>}
  </section>;
}
