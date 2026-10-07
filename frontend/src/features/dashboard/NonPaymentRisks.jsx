import React, {useMemo} from "react";
import {money} from "../../officeUI";

const DAY = 24 * 60 * 60 * 1000;

/**
 * «Top non-payment risks» — топ просроченной дебиторской задолженности.
 * Перенос идеи RiskAssessmentPanel/aging-реестра дизайн-проекта, но данные
 * только фактические: позиции FinanceReport.receivables с остатком и истёкшим
 * сроком оплаты. Ранжирование и уровень риска считаются из дат и сумм отчёта,
 * демо-значения не используются.
 *
 * @param {{report: object|null, limit?: number}} props
 */
export default function NonPaymentRisks({report, limit = 5}) {
  const risks = useMemo(() => {
    const asOf = report?.receivables_as_of ? new Date(report.receivables_as_of) : new Date();
    if (!asOf || Number.isNaN(asOf.getTime())) return [];
    return (report?.receivables || [])
      .map(item => {
        const outstanding = Number(item.outstanding || 0);
        const due = item.due_on ? new Date(item.due_on) : null;
        const daysOverdue = due && !Number.isNaN(due.getTime())
          ? Math.floor((asOf.getTime() - due.getTime()) / DAY) : null;
        return {...item, outstanding, daysOverdue};
      })
      .filter(item => item.outstanding > 0 && item.daysOverdue != null && item.daysOverdue > 0)
      .sort((a, b) => b.outstanding - a.outstanding)
      .slice(0, limit);
  }, [report, limit]);

  return <section className="ops-panel" aria-label="Топ рисков неплатежа">
    <div className="ops-panel-head"><div><span className="eyebrow">TOP NON-PAYMENT RISKS</span>
      <h3>Топ рисков неплатежа</h3>
      <p>Просроченные требования из финансового отчёта: остаток к получению и срок просрочки.</p>
    </div></div>
    {!risks.length ? <div className="ops-empty">Просроченной дебиторской задолженности нет
      {report ? "." : " — сформируйте финансовый отчёт в разделе «Бухгалтерия»."}</div> :
      <div className="risk-list">{risks.map(item => {
        const level = item.daysOverdue >= 60 ? "critical" : "high";
        return <div className="risk-row" key={item.receivable_id}>
          <div><b>{item.counterparty_id}</b>
            <small>Срок оплаты: {item.due_on} · просрочка {item.daysOverdue} дн.
              {Number(item.received) > 0 && ` · получено ${money(item.received)}`}</small>
            <span className={`risk-tag risk-${level}`}>{level === "critical" ? "60+ ДНЕЙ" : "ПРОСРОЧЕНО"}</span></div>
          <strong>{money(item.outstanding)}</strong>
        </div>;
      })}</div>}
    <p className="warning">Перечень не является прогнозом неплатежа и не запускает никаких
      действий: решение о работе с должником остаётся за собственником.</p>
  </section>;
}
