import React, {useMemo} from "react";
import {money} from "../../officeUI";

const AGING_LABELS = {
  not_due: "Не просрочено",
  "1_30": "1–30 дней",
  "31_60": "31–60 дней",
  "61_90": "61–90 дней",
  "90_plus": "90+ дней",
};

/**
 * DailyOwnerDigest — принятый результат ежедневного процесса (TZ 6.2).
 * Показывается последняя завершённая задача процесса
 * daily_cash_and_receivable_risk; все значения приходят из результата задачи
 * (mode === "daily_owner_digest_v1"), никаких вычислений на клиенте.
 *
 * @param {{tasks: Array<object>}} props
 */
export default function DailyOwnerDigest({tasks}) {
  const digest = useMemo(() => {
    const daily = (tasks || [])
      .filter(t => t.process?.id === "daily_cash_and_receivable_risk"
        && t.state === "completed"
        && t.result?.mode === "daily_owner_digest_v1")
      .sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
    return daily[0]?.result || null;
  }, [tasks]);

  if (!digest) {
    return <section className="ops-panel" aria-label="Ежедневная сводка">
      <div className="ops-panel-head"><div><span className="eyebrow">DAILY OWNER DIGEST</span>
        <h3>Ежедневная сводка</h3>
        <p>Принятый результат процесса «Ежедневный контроль денег» появится здесь.</p></div></div>
      <div className="ops-empty">Ежедневный процесс ещё не завершался —
        запустите его через API или дождитесь расписания.</div>
    </section>;
  }

  const riskList = digest.top_nonpayment_risks || [];
  return <section className="ops-panel daily-digest" aria-label="Ежедневная сводка">
    <div className="ops-panel-head"><div><span className="eyebrow">DAILY OWNER DIGEST · {digest.digest_date}</span>
      <h3>Ежедневная сводка</h3>
      <p>Watermark 1С: <code>{digest.watermark}</code></p></div></div>
    <div className="digest-kpis">
      <div className="digest-kpi"><small>Доступно денег</small><strong>{money(digest.cash_available)}</strong></div>
      <div className="digest-kpi"><small>Приток за день</small><strong>{money(digest.cash_in)}</strong></div>
      <div className="digest-kpi"><small>Отток за день</small><strong>{money(digest.cash_out)}</strong></div>
      <div className="digest-kpi"><small>Нетто поток</small><strong>{money(digest.net_cash_flow)}</strong></div>
      <div className="digest-kpi"><small>Ожидается к получению</small><strong>{money(digest.expected_receipts)}</strong></div>
      <div className="digest-kpi"><small>Дебиторка всего</small><strong>{money(digest.receivable_total)}</strong></div>
    </div>
    <div className="digest-aging">
      {Object.entries(digest.receivable_aging || {}).map(([bucket, value]) => (
        <div className="digest-bucket" key={bucket}>
          <small>{AGING_LABELS[bucket] || bucket}</small><strong>{money(value)}</strong>
        </div>
      ))}
    </div>
    {riskList.length > 0 && <>
      <h4>Топ рисков неплатежа</h4>
      <div className="risk-list">{riskList.map(risk => (
        <div className="risk-row" key={risk.counterparty_id + risk.days_overdue}>
          <div><b>{risk.counterparty_name}</b>
            <small>{risk.explanation}</small>
            <span className="risk-tag risk-high">ПРОСРОЧЕНО {risk.days_overdue} ДН.</span></div>
          <div className="risk-action"><strong>{money(risk.outstanding)}</strong>
            <small>{risk.recommended_action}</small></div>
        </div>
      ))}</div>
    </>}
    {digest.anomaly_count > 0
      ? <p className="warning">Аномалий в счетах: {digest.anomaly_count} из {digest.invoice_count}.</p>
      : <p className="warning">Аномалий в счетах не обнаружено ({digest.invoice_count} проверено).</p>}
  </section>;
}
