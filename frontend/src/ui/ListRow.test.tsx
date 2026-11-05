import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ListRow } from "./ListRow";
import { ShellContext } from "./shell";

afterEach(cleanup);

describe("a row you tap to open what it names", () => {
  it("is one button named for what the tap does, with a chevron", () => {
    const onClick = vi.fn();
    render(
      <ShellContext.Provider value="display">
        <ListRow
          label="Edit Mia"
          title="Mia"
          subtitle="Child · Pink"
          value="2 phones"
          onClick={onClick}
        />
      </ShellContext.Provider>,
    );
    // What a tap does, then what else it shows: voice control goes by what's on the screen.
    const row = screen.getByRole("button", { name: "Edit Mia, Child · Pink, 2 phones" });
    expect(row.textContent).toContain("Mia");
    expect(row.textContent).toContain("2 phones");
    expect(row.hasAttribute("aria-describedby")).toBe(false);
    expect(row.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
    // 64 px on the wall, whatever the text size.
    expect(row.className).toContain("min-h-tap-primary");
    fireEvent.click(row);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("is 56 px on a phone, and needs no line under its title", () => {
    render(<ListRow label="Edit Home" title="Home" />);
    const row = screen.getByRole("button", { name: "Edit Home" });
    expect(row.className).toContain("min-h-14");
  });
});
