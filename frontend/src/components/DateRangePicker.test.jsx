import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DateRangePicker } from "./DateRangePicker.jsx";

describe("DateRangePicker", () => {
  it("opens a calendar and reports the selected range as ISO dates", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { container } = render(
      <DateRangePicker label="Trade Date" value={{}} onChange={onChange} />,
    );

    await user.click(screen.getByRole("button", { name: /Trade Date/ }));

    const days = container.querySelectorAll("button.rdp-day_button");
    expect(days.length).toBeGreaterThan(0);
    await user.click(days[1]);
    await user.click(days[10]);

    expect(onChange).toHaveBeenCalled();
    const last = onChange.mock.calls.at(-1)[0];
    expect(last.from).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(last.to).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("shows the chosen range in the trigger", () => {
    render(
      <DateRangePicker
        label="Settlement Date"
        value={{ from: "2026-08-01", to: "2026-08-15" }}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText("2026-08-01 → 2026-08-15")).toBeInTheDocument();
  });
});
