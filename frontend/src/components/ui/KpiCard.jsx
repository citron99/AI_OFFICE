import React from "react";
import Icon from "./icons";

/**
 * KPI-карточка в формате дизайн-проекта (метрики 1С: DashboardView/AccountingView).
 * Поддерживает водяной знак источника данных (data-watermark, например «Mock1C»),
 * чтобы было видно, откуда пришло значение. Значение приходит только из API.
 *
 * @param {{
 *   label: string, value: React.ReactNode, hint?: React.ReactNode,
 *   icon?: string, tone?: "emerald"|"sky"|"amber"|"rose",
 *   watermark?: string, negative?: boolean, onClick?: () => void,
 * }} props
 */
export default function KpiCard({label, value, hint, icon, tone = "emerald", watermark, negative, onClick}) {
  const content = <>
    <span className="finance-kpi-head">
      <span className="finance-kpi-label">{label}</span>
      {icon && <span className={`finance-kpi-icon tone-${tone}`}><Icon name={icon} size={15} /></span>}
    </span>
    <strong className={"finance-kpi-value" + (negative ? " negative" : "")}>{value}</strong>
    {hint != null && <small className="finance-kpi-hint">{hint}</small>}
  </>;
  const props = {
    className: "finance-kpi" + (onClick ? "" : " static"),
    "data-watermark": watermark || "",
  };
  return onClick
    ? <button type="button" {...props} onClick={onClick}>{content}</button>
    : <section {...props}>{content}</section>;
}
