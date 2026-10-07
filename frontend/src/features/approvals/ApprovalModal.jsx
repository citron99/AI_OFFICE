import React from "react";
import DecisionDialog from "../../DecisionDialog";
import Icon from "../../components/ui/icons";
import {formatDate, money} from "../../officeUI";

/**
 * ApprovalModal — перенос дизайн-проекта (src/components/ApprovalModal.tsx):
 * блок «Параметры операции (Payload Diff)» с колонками «до/после», raw-payload,
 * SHA-256 хеш и предупреждение, что это не реальный платёж.
 *
 * Данные согласования приходят из GET /api/v1/approvals; информация о счёте
 * (контрагент, номер) — из уже загруженного реестра /accounting/invoices.
 * Никаких расчётов и демо-значений: отсутствующие поля честно помечаются «—».
 *
 * @param {{
 *   record: object, decision: "approve"|"reject", busy: boolean,
 *   invoice?: object|null,
 *   onClose: () => void, onConfirm: () => void,
 * }} props
 */
export default function ApprovalModal({record, decision, busy, invoice, onClose, onConfirm}) {
  const approve = decision === "approve";
  const payload = record.payload || {};
  const diffRows = [
    {
      field: "Сумма",
      before: "Запись в 1С без черновика платежа",
      after: money(payload.amount),
    },
    {
      field: "Контрагент",
      before: invoice?.counterparty_id ? `${invoice.counterparty_id} · новый для проверки` : "Контрагент из реестра Mock1C",
      after: invoice?.counterparty_id || payload.counterparty_id || "—",
    },
    {
      field: "Счёт",
      before: payload.invoice_id ? `${payload.invoice_id}${invoice?.number ? ` · №${invoice.number}` : ""}` : "Без счёта",
      after: approve ? "Создание mock-черновика платежа" : "Черновик не создаётся",
    },
  ];
  return <DecisionDialog busy={busy} onClose={onClose} title={approve ? "Подтвердить создание mock-черновика?" : "Отклонить запрос?"}>
    <section className="approval-modal-summary"><span className="eyebrow">APPROVAL GATE · {approve ? "CONFIRM" : "REJECT"}</span>
      <h3>{payload.invoice_id || "Без номера счёта"} · {money(payload.amount)}</h3>
      <dl><div><dt>Срок действия</dt><dd>{formatDate(record.expires_at)}</dd></div><div><dt>Хеш полезной нагрузки</dt><dd><code>{record.payload_hash}</code></dd></div></dl>
      <div className="approval-diff" role="table" aria-label="Параметры операции (Payload Diff)">
        <span className="approval-diff-title">Параметры операции (Payload Diff)</span>
        {diffRows.map(row => <div className="approval-diff-row" role="row" key={row.field}>
          <span role="rowheader">{row.field}</span>
          <span role="cell" className="approval-diff-before">{row.before}</span>
          <Icon name="chevronRight" size={12} className="approval-diff-arrow" />
          <span role="cell" className="approval-diff-after">{row.after}</span>
        </div>)}
      </div>
      <details className="approval-payload"><summary>Данные платежа / счёта (JSON)</summary>
        <pre>{JSON.stringify(payload, null, 2)}</pre></details>
      <p className="approval-warning"><Icon name="alert" size={13} className="icon" />
        Это не реальный платёж. Решение создаёт или отклоняет только синтетический
        черновик: банковское исполнение, изменение счёта в 1С и юридическое
        разрешение не выполняются.</p></section>
    <div className="actions"><button autoFocus disabled={busy} onClick={onClose}>Назад</button><button className={approve ? "primary" : "danger"} disabled={busy} onClick={onConfirm}>{busy ? "Сохраняем…" : approve ? "Подтвердить решение" : "Отклонить запрос"}</button></div>
  </DecisionDialog>;
}
