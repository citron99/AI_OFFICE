import React from "react";
import KpiCard from "../../components/ui/KpiCard";
import {money} from "../../officeUI";

/**
 * Карточки финансовых KPI (перенос из дизайн-проекта: Financial KPI Cards +
 * AccountingView «1С:Предприятие 8.3», переложено на токены и watermark Mock1C).
 *
 * Источник данных — только FinanceReport из POST /api/v1/accounting/financial-report.
 * Деньги считает бэкенд: фронтенд лишь отображает поля отчёта.
 *
 * @param {{report: object|null, onNavigate?: (tab: string) => void}} props
 */
export default function FinanceKpiCards({report, onNavigate}) {
  if (!report) return <div className="ops-empty">
    Финансовые показатели появятся после расчёта отчёта в разделе «Бухгалтерия».
    Значения не подменяются демонстрационными данными.
    {onNavigate && <div className="actions" style={{justifyContent: "center"}}>
      <button type="button" className="quiet" onClick={() => onNavigate("finance")}>Сформировать отчёт →</button>
    </div>}
  </div>;

  const aging = report.receivable_aging || {};
  const overdue = Object.entries(aging)
    .filter(([bucket]) => bucket !== "not_due")
    .reduce((total, [, amount]) => total + Number(amount || 0), 0);
  const receivable = Number(report.total_receivable || 0);
  const overdueShare = receivable > 0 ? Math.round((overdue / receivable) * 100) : 0;
  const hasBalances = Boolean(report.balances_as_of);
  const cards = [
    {
      label: "Доступные деньги", icon: "wallet", tone: "emerald",
      value: hasBalances ? money(report.total_bank_balance) : "—",
      hint: hasBalances ? `остатки по счётам на ${report.balances_as_of}` : "снимка банковских остатков на дату нет",
      negative: false,
    },
    {
      label: "Ожидаемые поступления", icon: "arrowDown", tone: "sky",
      value: money(report.total_receivable),
      hint: `дебиторская задолженность на ${report.receivables_as_of || "—"}`,
    },
    {
      label: "Обязательства", icon: "file", tone: "amber",
      value: money(report.total_outstanding),
      hint: `долги поставщикам на ${report.payables_as_of || "—"} (без переплат)`,
    },
    {
      label: "Просроченная дебиторка", icon: "alert", tone: "rose",
      value: money(overdue), negative: overdue > 0,
      hint: `${overdueShare}% ожидаемых поступлений · реестр Mock1C`,
    },
  ];
  return <div className="finance-kpis" aria-label="Финансовые показатели">
    {cards.map(card => <KpiCard key={card.label} watermark="Mock1C" {...card} />)}
  </div>;
}
