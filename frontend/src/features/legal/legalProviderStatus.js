function listText(value) {
  if (!Array.isArray(value)) return "";
  return value.filter(item => typeof item === "string" && item.trim()).join(", ");
}

/** Convert every supported API shape to text React can render safely. */
export function formatLicenseScope(scope) {
  if (scope == null || scope === "") return null;
  if (Array.isArray(scope)) return listText(scope) || null;
  if (typeof scope === "string" || typeof scope === "number") return String(scope);
  if (typeof scope !== "object") return null;

  const parts = [];
  const jurisdictions = listText(scope.jurisdictions);
  const channels = listText(scope.allowed_channels);
  if (jurisdictions) parts.push(`юрисдикции: ${jurisdictions}`);
  if (channels) parts.push(`каналы: ${channels}`);
  if (typeof scope.scope_owner === "string" && scope.scope_owner.trim()) {
    parts.push(`контур: ${scope.scope_owner}`);
  }
  if (typeof scope.valid_until === "string" && scope.valid_until.trim()) {
    parts.push(`действует до: ${scope.valid_until}`);
  }
  return parts.join(" · ") || "ограничения заданы провайдером";
}

export function providerIsActive(status) {
  return status === "active" || status === "ok";
}
