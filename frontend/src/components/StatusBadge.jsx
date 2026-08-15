const CLASS_BY_STATUS = {
  BOOKED: "badge--success",
  PENDING_CONFIRMATION: "badge--warn",
  CANCELLED: "badge--danger",
  MATURED: "badge--muted",
};

export function StatusBadge({ status }) {
  const className = CLASS_BY_STATUS[status] ?? "badge--muted";
  return <span className={`badge ${className}`}>{status}</span>;
}
