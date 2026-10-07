import React, {useMemo, useState} from "react";
import Icon from "../../components/ui/icons";
import {agentAccent, agentLabels, stateLabel} from "../../officeUI";

const readinessLabels = {ready: "готов", blocked: "заблокирован", waiting: "ожидает", done: "выполнен"};

/**
 * TaskDagView — визуализация сохранённого process DAG (GET /api/v1/tasks/{id}/process-graph).
 * Стиль узлов и NODE INSPECTOR перенесены из дизайн-проекта (src/components/TaskDagView.tsx)
 * с сохранением доступного вертикального-layout и токенов. Граф только для чтения:
 * редактирование процесса в UI не предусмотрено архитектурой.
 *
 * @param {{graph: object|null, onSelectNode?: (node: object) => void}} props
 */
export default function TaskDagView({graph, onSelectNode}) {
  const [selected, setSelected] = useState(null);
  const nodes = graph?.nodes || [];
  const byId = useMemo(() => Object.fromEntries(nodes.map(node => [node.id, node])), [nodes]);
  if (!graph) return <div className="ops-empty">Выберите задачу, чтобы увидеть её сохранённый граф выполнения.</div>;
  const choose = node => { setSelected(node.id); onSelectNode?.(node); };
  const done = nodes.filter(node => node.state === "completed").length;
  const blocked = nodes.filter(node => node.readiness === "blocked" || node.state === "failed").length;
  return <section className="ops-panel dag-view" aria-label="Граф выполнения задачи">
    <div className="ops-panel-head"><div><span className="eyebrow">EXECUTABLE DAG · {graph.process_id || "process"}</span><h3>Граф исполнения</h3>
      <p>Отображаются фактически сохранённые узлы и зависимости. Редактирование графа в UI намеренно отключено.</p></div>
      <div className="dag-head-stats">
        <span className="pill">{done}/{nodes.length} выполнено</span>
        {blocked > 0 && <span className="pill dag-pill-blocked">{blocked} заблокировано</span>}
        <span className="pill">v{graph.process_version || "—"}</span>
      </div></div>
    <div className="dag-canvas">{nodes.map((node, index) => {
      const accent = node.kind === "result_review" ? "orchestrator" : node.agent;
      return <React.Fragment key={node.id}>
        <button className={`dag-node state-${node.state} accent-${agentAccent[accent] || "indigo"} ${selected === node.id ? "is-selected" : ""}`}
          onClick={() => choose(node)} aria-pressed={selected === node.id}>
          <span className="dag-index">{String(index + 1).padStart(2, "0")}</span>
          <strong>{node.kind === "result_review"
            ? <><Icon name="shield" size={13} className="dag-node-icon" /> Проверка результата</>
            : <><Icon name={agentIcon(node.agent)} size={13} className="dag-node-icon" /> {agentLabels[node.agent] || node.agent || "Узел"}</>}</strong>
          <small>{node.action || "Решение собственника"}</small>
          <span className="dag-status">{stateLabel(node.state)} · {readinessLabels[node.readiness] || node.readiness}</span>
        </button>
        {index < nodes.length - 1 && <span className="dag-arrow" aria-hidden="true">
          <Icon name="arrowDown" size={13} className="icon" /></span>}
      </React.Fragment>;
    })}</div>
    {selected && <aside className="dag-inspector"><span className="eyebrow">NODE INSPECTOR</span>
      <strong>{byId[selected]?.action || "Проверка результата"}</strong>
      <p>Зависит от: {byId[selected]?.depends_on?.length ? byId[selected].depends_on.map(id => byId[id]?.node_id || id).join(", ") : "нет"}</p>
      {byId[selected]?.blocked_by?.length > 0 && <p className="warning">Блокируют: {byId[selected].blocked_by.join(", ")}</p>}</aside>}
  </section>;
}

function agentIcon(agent) {
  return {accountant: "calculator", lawyer: "scale", security: "shield", orchestrator: "network"}[agent] || "bot";
}
