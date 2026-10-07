import React, {useMemo, useState} from "react";
import {formatDate} from "../../officeUI";

/**
 * Activity/Audit view — журнал активности и audit events (GET /api/v1/activity
 * и trace выбранной задачи). Оформление усилено токенами дизайн-проекта.
 */
export default function ActivityAuditView({trace, activity, onRefresh}) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("all");
  const events = useMemo(() => {
    const source = activity || (trace ? {
      steps: trace.steps || [], audit: trace.audit || [],
    } : null);
    if (!source) return [];
    return [
      ...(source.steps || []).map(step => ({id: `step-${step.id}`, kind: "agent", actor: step.agent, action: step.node_id || step.agent, details: {task_id: step.task_id, state: step.state, attempt: step.attempt, error_code: step.error_code}, at: step.completed_at || step.started_at})),
      ...(source.audit || []).map(event => ({id: `audit-${event.id}`, kind: "audit", actor: "system", action: event.event, details: {...(event.details || {}), task_id: event.task_id}, at: event.created_at})),
    ].sort((a, b) => new Date(b.at || 0) - new Date(a.at || 0));
  }, [trace, activity]);
  const visible = events.filter(event => (kind === "all" || event.kind === kind) && `${event.actor} ${event.action} ${JSON.stringify(event.details)}`.toLocaleLowerCase("ru").includes(query.toLocaleLowerCase("ru")));
  return <section className="ops-panel activity-view" aria-label="Журнал активности и аудит">
    <div className="ops-panel-head"><div><span className="eyebrow">ACTIVITY LOG · PERSISTED AUDIT</span><h3>Журнал активности</h3><p>События хранятся в PostgreSQL и ограничены текущим владельцем.</p></div>
      <button className="quiet" onClick={onRefresh}>Обновить</button></div>
    <div className="activity-summary"><div><b>{events.length}</b><span>событий</span></div><div><b>{events.filter(event => event.kind === "agent").length}</b><span>шагов агентов</span></div><div><b>{events.filter(event => event.kind === "audit").length}</b><span>audit events</span></div></div>
    <div className="thread-tools"><div className="segmented" role="group" aria-label="Фильтр журнала">
      {["all", "agent", "audit"].map(value => <button key={value} aria-pressed={kind === value} onClick={() => setKind(value)}>{value === "all" ? "Все" : value === "agent" ? "Агенты" : "Аудит"}</button>)}</div>
      <label className="thread-search"><span className="sr-only">Поиск событий</span><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Действие или параметр" /></label></div>
    <div className="audit-table"><table><thead><tr><th>Время</th><th>Источник</th><th>Событие</th><th>Детали</th></tr></thead><tbody>{visible.map(event => <tr key={event.id}><td>{formatDate(event.at)}</td><td><span className={`actor-chip actor-${event.actor}`}>{event.actor}</span></td><td><strong>{event.action}</strong></td><td><code>{Object.keys(event.details).length ? JSON.stringify(event.details) : "—"}</code></td></tr>)}</tbody></table></div>
    {!visible.length && <div className="ops-empty">Событий с таким фильтром нет.</div>}
  </section>;
}
