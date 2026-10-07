import React from "react";
import {agentLabels, stateLabel} from "./officeUI";

function agentResult(task, agent) {
  const result = task?.result || {};
  if (agent === "accountant" && result.accounting) return `Оплачено: ${result.accounting.paid}; остаток: ${result.accounting.outstanding}.`;
  if (agent === "lawyer") {
    const legal = result.legal || (result.mode?.startsWith("legal_") ? result : null);
    return legal?.summary || "Юридический вывод не формировался для этого маршрута.";
  }
  if (agent === "security") return result.security?.summary || result.security?.status || result.policy_reasons?.join("; ") || "Отдельный вывод безопасности отсутствует.";
  return result.summary || "Итог ожидает исполнения.";
}

export default function ConsultationView({task, graph, onOpenThread, onOpenReview}) {
  if (!task) return <div className="ops-empty">Выберите задачу, чтобы открыть консилиум её участников.</div>;
  const nodes = graph?.nodes?.filter(node => node.kind === "agent_step") || [];
  const agents = [...new Set(nodes.map(node => node.agent).filter(Boolean))];
  return <section className="ops-panel consultation-view" aria-label="Консилиум агентов">
    <div className="ops-panel-head"><div><span className="eyebrow">CONSULTATION MODE · READ ONLY</span><h3>Консилиум агентов</h3>
      <p>Представления построены по сохранённым результатам DAG. Новый «раунд дебатов» не запускается из интерфейса без отдельного серверного процесса.</p></div><span className={`consultation-state state-${task.state}`}>{stateLabel(task.state)}</span></div>
    <div className="consultation-flow">{agents.map((agent, index) => <React.Fragment key={agent}><article className={`consultant consultant-${agent}`}><header><span>{String(index + 1).padStart(2, "0")}</span><b>{agentLabels[agent] || agent}</b></header>
      <p>{agentResult(task, agent)}</p></article>{index < agents.length - 1 && <span className="consult-arrow">→</span>}</React.Fragment>)}</div>
    <section className="consultation-consensus"><span className="eyebrow">СОГЛАСОВАННАЯ ПОЗИЦИЯ</span><p>{task.result?.summary || "Результат ещё не сформирован."}</p>
      {task.result?.policy_decision && <p className="muted">Policy gate: <b>{task.result.policy_decision}</b></p>}
      <div className="actions"><button className="quiet" onClick={onOpenThread}>Открыть стенограмму</button><button onClick={onOpenReview}>Проверить результат →</button></div></section>
  </section>;
}
