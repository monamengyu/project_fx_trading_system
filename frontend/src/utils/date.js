export function addBusinessDays(start, days) {
  const d = new Date(start);
  let added = 0;
  while (added < days) {
    d.setDate(d.getDate() + 1);
    const day = d.getDay();
    if (day !== 0 && day !== 6) added += 1; // skip weekends
  }
  return d;
}

export function spotValueDate(start) {
  return addBusinessDays(start, 2);
}

export function toISODate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function nextBusinessDay(d) {
  const date = new Date(d);
  while (date.getDay() === 0 || date.getDay() === 6) {
    date.setDate(date.getDate() + 1);
  }
  return date;
}

export function todayISO() {
  // trade_date is always a business day on the backend (weekends roll forward)
  return toISODate(nextBusinessDay(new Date()));
}
