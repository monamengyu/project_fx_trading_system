import { useEffect, useRef, useState } from "react";
import { DayPicker } from "react-day-picker";
import "react-day-picker/style.css";

function toISODate(d) {
  if (!d) return "";
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function parseISODate(s) {
  return s ? new Date(`${s}T00:00:00`) : undefined;
}

export function DateRangePicker({ label, value, onChange }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);

  useEffect(() => {
    function onDocClick(e) {
      if (rootRef.current && !rootRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  const range =
    value?.from != null
      ? { from: parseISODate(value.from), to: parseISODate(value.to) }
      : undefined;

  function handleSelect(selected) {
    onChange({
      from: selected?.from ? toISODate(selected.from) : "",
      to: selected?.to ? toISODate(selected.to) : "",
    });
    if (selected?.from && selected?.to) {
      setOpen(false);
    }
  }

  const summary =
    value?.from && value?.to ? `${value.from} → ${value.to}` : "Select range";

  return (
    <div className="date-range-picker" ref={rootRef}>
      <button
        type="button"
        className="date-range-picker__trigger"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="date-range-picker__label">{label}</span>
        <span className="date-range-picker__value">{summary}</span>
      </button>
      {open && (
        <div className="date-range-picker__popover">
          <DayPicker
            mode="range"
            selected={range}
            onSelect={handleSelect}
            numberOfMonths={1}
          />
        </div>
      )}
    </div>
  );
}
