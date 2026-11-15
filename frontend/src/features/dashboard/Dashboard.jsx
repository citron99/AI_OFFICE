import React from "react";
import {activeTaskStates, money, riskSnapshot} from "../../officeUI";
import DailyOwnerDigest from "./DailyOwnerDigest";
import FinanceKpiCards from "./FinanceKpiCards";
import NonPaymentRisks from "./NonPaymentRisks";

export default function Dashboard({tasks, approvals, drafts, processQuality, processControls, finance, onNavigate,
  dataState = {status: processQuality && processControls ? "ready" : "loading"}}) {
  const hasSnapshot = ["ready", "refreshing", "stale"].includes(dataState.status);
  const controlsAvailable = hasSnapshot && processControls && processQuality;
  const riskAvailable = controlsAvailable && finance;
  const snapshotTime = dataState.updatedAt ? new Date(dataState.updatedAt).toLocaleString("ru-RU") : null;
  const dataMessage = dataState.status === "loading" ? "Загружаем данные дашборда…" :
    dataState.status === "error" ? "Не удалось загрузить данные. Повторите запрос кнопкой «Обновить»." :
    dataState.status === "stale" ? `Обновление не удалось. Показан предыдущий снимок${snapshotTime ? ` от ${snapshotTime}` : ""}. Повторите запрос кнопкой «Обновить».` :
    dataState.status === "refreshing" ? "Обновляем данные. Пока показан предыдущий снимок." :
    snapshotTime ? `Данные загружены: ${snapshotTime}.` : "Данные загружены.";
  const active = tasks.filter(task => activeTaskStates.has(task.state)).length;
  const pending = approvals.filter(item => item.status === "pending").length;
  const reviewed = processQuality?.reviewed_results || 0;
  const observedCost = tasks.reduce((total, task) => total + Number(task.run_usage?.observed_cost_rub || 0), 0);
  const risk = riskSnapshot({tasks, approvals, controls: processControls, finance});
  const riskText = {low: "Низкий", medium: "Умеренный", high: "Повышенный", critical: "Критический"}[risk.level];
  const measures = [
    ["Активные процессы", active, "очередь и исполнение", "tasks"],
    ["Ожидают решения", pending, "approval gate", "approvals"],
    ["Проверенные результаты", reviewed, `из ${processQuality?.completed_tasks || 0} завершённых`, "tasks"],
    ["Фактические затраты ИИ", money(observedCost), "по сохранённой телеметрии", "tasks"],
  ];
  return <section className="ops-dashboard" aria-label="Операционный дашборд">
    <header className="ops-hero">
      <div><h2>Операционный контур</h2><p className="muted">Режим чтения</p>
        <p>Метрики собраны только из сохранённых задач, согласований, контроля процесса и бухгалтерского отчёта.</p></div>
      <button className="ops-hero-action" onClick={() => onNavigate("tasks")}>Новая проверка</button>
    </header>
    <p className="muted" role="status">{dataMessage}</p>
    <div className="ops-kpis">{measures.map(([label, value, hint, tab]) => <button className="ops-kpi" key={label} onClick={() => onNavigate(tab)}>
      <span>{label}</span><strong>{hasSnapshot ? value : "—"}</strong><small>{hasSnapshot ? hint : "Нет загруженных данных"}</small></button>)}</div>
    <div className="ops-grid">
      <section className={`ops-risk${riskAvailable ? ` ops-risk-${risk.level}` : ""}`}>
        <div className="ops-panel-head"><div><span className="ops-icon" aria-hidden="true">◒</span><h3>Индекс операционного риска</h3>
          </div>{riskAvailable && <strong className="ops-score">{risk.score}<small>/100</small></strong>}</div>
        {riskAvailable ? <><div className="risk-meter" aria-label={`Индекс риска ${risk.score} из 100`}><span style={{width: `${risk.score}%`}} /></div>
        <p><b>{riskText} риск.</b> Формула учитывает только факты: ошибки задач, ожидающие решения, policy-deny и просроченную дебиторку.</p>
        <dl className="ops-factors"><div><dt>Ожидают контекста или решения</dt><dd>{risk.attention}</dd></div>
          <div><dt>Ошибки процесса</dt><dd>{risk.failed}</dd></div><div><dt>Policy deny</dt><dd>{risk.denied}</dd></div>
          <div><dt>Просроченная дебиторка</dt><dd>{money(risk.overdue)}</dd></div></dl></> :
          <p>Нет данных для оценки. {controlsAvailable ? "Сформируйте финансовый отчёт в разделе «Бухгалтерия»." : "Дождитесь загрузки данных процессов или повторите запрос кнопкой «Обновить»."}</p>}
        <button className="quiet" onClick={() => onNavigate("finance")}>Открыть финансовые риски</button>
      </section>
      <section className="ops-panel">
        <div className="ops-panel-head"><div><h3>Контроль исполнения</h3></div>
          {controlsAvailable && <span className="muted">{dataState.status === "stale" ? "Предыдущий снимок" : "Загруженный снимок"}</span>}</div>
        {controlsAvailable ? <><div className="ops-progress"><span>Postflight контроль</span><strong>{Math.round((processControls?.postflight_coverage || 0) * 100)}%</strong><div><i style={{width: `${Math.round((processControls?.postflight_coverage || 0) * 100)}%`}} /></div></div>
        <div className="ops-progress"><span>Review результата</span><strong>{Math.round((processQuality?.review_rate || 0) * 100)}%</strong><div><i style={{width: `${Math.round((processQuality?.review_rate || 0) * 100)}%`}} /></div></div>
        <div className="ops-mini-grid"><div><span>Черновики</span><b>{drafts.length}</b><small>не отправлены</small></div>
          <div><span>Флаги контролей</span><b>{Object.keys(processControls?.control_flags || {}).length}</b><small>за период</small></div></div></> : <p className="muted">Нет загруженных данных контроля исполнения.</p>}
        <button className="quiet" onClick={() => onNavigate("activity")}>Открыть журнал активности</button>
      </section>
    </div>
    <section aria-label="Финансовый контур" className="ops-dashboard" style={{gap: "18px"}}>
      {hasSnapshot ? <DailyOwnerDigest tasks={tasks} /> : <p className="muted">Ежедневная сводка будет доступна после загрузки задач.</p>}
      <FinanceKpiCards report={hasSnapshot ? finance : null} onNavigate={onNavigate} />
      <NonPaymentRisks report={hasSnapshot ? finance : null} />
    </section>
  </section>;
}
