import React from "react";
import {money, riskSnapshot} from "./officeUI";

const bucketLabels = {not_due: "Срок не наступил", "1_30": "1–30 дней", "31_60": "31–60 дней", "61_90": "61–90 дней", over_90: "Более 90 дней"};

export default function FinancialRiskView({report, tasks, approvals, controls}) {
  if (!report) return <section className="ops-panel"><span className="eyebrow">FINANCIAL RISK</span><h3>Риск-панель появится после расчёта отчёта</h3><p className="muted">Используйте период выше: показатели не подменяются демонстрационными значениями.</p></section>;
  const risk = riskSnapshot({tasks, approvals, controls, finance: report});
  const receivableOverdue = Object.entries(report.receivable_aging || {}).filter(([bucket]) => bucket !== "not_due");
  const maximum = Math.max(1, ...receivableOverdue.map(([, amount]) => Number(amount)));
  return <section className={`ops-panel financial-risk risk-${risk.level}`} aria-label="Визуализация финансовых рисков"><div className="ops-panel-head"><div><span className="eyebrow">FINANCIAL RISK · {report.currency}</span><h3>Визуализация денежного риска</h3>
    <p>Сигналы рассчитаны из выбранного финансового периода и статусов процессов, не являются прогнозом.</p></div><strong className="ops-score">{risk.score}<small>/100</small></strong></div>
    <div className="financial-risk-grid"><section><span className="risk-label">Чистый денежный поток</span><strong className={Number(report.current.net) < 0 ? "negative" : "positive"}>{money(report.current.net)}</strong><small>за {report.current.start} — {report.current.end}</small></section>
      <section><span className="risk-label">К получению</span><strong>{money(report.total_receivable)}</strong><small>дебиторская задолженность</small></section><section><span className="risk-label">К оплате</span><strong>{money(report.total_outstanding)}</strong><small>без учёта переплат</small></section></div>
    <div className="aging-chart"><div className="aging-head"><b>Возраст дебиторской задолженности</b><span>суммы в RUB</span></div>{receivableOverdue.map(([bucket, amount]) => <div className="aging-bar" key={bucket}><label>{bucketLabels[bucket] || bucket}</label><div><i style={{width: `${Math.max(3, Number(amount) / maximum * 100)}%`}} /></div><strong>{money(amount)}</strong></div>)}</div>
    <p className="warning">Порог риска: просроченные корзины, pending approval, ошибки процесса и policy deny. Переплаты и реальные банковские платежи не включаются как автоматическое действие.</p>
  </section>;
}
