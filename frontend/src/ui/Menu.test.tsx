import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Menu, MenuCheck, MenuGroup, MenuRadio } from "./Menu";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  // The swallowed click's window listener lasts a second: let it go before the next test.
  vi.runAllTimers();
  vi.useRealTimers();
});

function Fruit({ onPick = vi.fn() }: { onPick?: (fruit: string) => void }) {
  const [liked, setLiked] = useState<string[]>([]);
  return (
    <>
      <Menu
        label="Fruit"
        trigger={(props) => (
          <button type="button" {...props}>
            Fruit
          </button>
        )}
      >
        <MenuGroup label="Kinds">
          <MenuRadio
            checked={liked.length === 0}
            onChoose={() => {
              setLiked([]);
              onPick("any");
            }}
          >
            Any
          </MenuRadio>
          {["Apple", "Pear"].map((fruit) => (
            <MenuCheck
              key={fruit}
              checked={liked.includes(fruit)}
              onChange={(on) => {
                setLiked(on ? [...liked, fruit] : liked.filter((other) => other !== fruit));
              }}
            >
              {fruit}
            </MenuCheck>
          ))}
        </MenuGroup>
      </Menu>
      <button
        type="button"
        onClick={() => {
          onPick("outside");
        }}
      >
        Elsewhere
      </button>
    </>
  );
}

describe("a menu under its button (ADR 0030)", () => {
  it("opens under its button, named, with focus on the checked row", () => {
    render(<Fruit />);
    const button = screen.getByRole("button", { name: "Fruit" });
    expect(button.getAttribute("aria-haspopup")).toBe("menu");
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(button);
    const menu = screen.getByRole("menu", { name: "Fruit" });
    expect(button.getAttribute("aria-expanded")).toBe("true");
    expect(button.getAttribute("aria-controls")).toBe(menu.id);
    expect(screen.getByRole("group", { name: "Kinds" })).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole("menuitemradio", { name: "Any" }));
  });

  it("walks its rows with the arrows, Home and End, past the group's word", () => {
    render(<Fruit />);
    fireEvent.click(screen.getByRole("button", { name: "Fruit" }));
    const menu = screen.getByRole("menu");
    const [any, apple, pear] = [
      screen.getByRole("menuitemradio", { name: "Any" }),
      screen.getByRole("menuitemcheckbox", { name: "Apple" }),
      screen.getByRole("menuitemcheckbox", { name: "Pear" }),
    ];
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(document.activeElement).toBe(apple);
    fireEvent.keyDown(menu, { key: "End" });
    expect(document.activeElement).toBe(pear);
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(document.activeElement).toBe(any);
    fireEvent.keyDown(menu, { key: "ArrowUp" });
    expect(document.activeElement).toBe(pear);
    fireEvent.keyDown(menu, { key: "Home" });
    expect(document.activeElement).toBe(any);
  });

  it("stays open for a checkbox row, and closes on a radio row", () => {
    const onPick = vi.fn();
    render(<Fruit onPick={onPick} />);
    const button = screen.getByRole("button", { name: "Fruit" });
    fireEvent.click(button);
    fireEvent.click(screen.getByRole("menuitemcheckbox", { name: "Apple" }));
    fireEvent.click(screen.getByRole("menuitemcheckbox", { name: "Pear" }));
    expect(screen.getByRole("menu")).toBeTruthy();
    expect(
      screen.getByRole("menuitemcheckbox", { name: "Apple" }).getAttribute("aria-checked"),
    ).toBe("true");
    expect(screen.getByRole("menuitemradio", { name: "Any" }).getAttribute("aria-checked")).toBe(
      "false",
    );
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Any" }));
    expect(onPick).toHaveBeenCalledWith("any");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(button);
  });

  it("closes on Escape and on Tab, back to its button", () => {
    render(<Fruit />);
    const button = screen.getByRole("button", { name: "Fruit" });
    for (const key of ["Escape", "Tab"]) {
      fireEvent.click(button);
      fireEvent.keyDown(screen.getByRole("menu"), { key });
      expect(screen.queryByRole("menu")).toBeNull();
      expect(document.activeElement).toBe(button);
    }
  });

  it("takes a press elsewhere for itself: it closes, and the tap does nothing else", () => {
    const onPick = vi.fn();
    render(<Fruit onPick={onPick} />);
    fireEvent.click(screen.getByRole("button", { name: "Fruit" }));
    const elsewhere = screen.getByRole("button", { name: "Elsewhere" });
    fireEvent.pointerDown(elsewhere);
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(elsewhere);
    expect(onPick).not.toHaveBeenCalled();
    // Only that tap: the next one is an ordinary press again.
    fireEvent.click(elsewhere);
    expect(onPick).toHaveBeenCalledWith("outside");
  });

  it("names a row with a line by its name alone, and reads the line after it (ADR 0042)", () => {
    render(
      <Menu
        label="View"
        trigger={(props) => (
          <button type="button" {...props}>
            View
          </button>
        )}
      >
        <MenuRadio checked drawing={<svg />} detail="One day, hour by hour." onChoose={vi.fn()}>
          Day
        </MenuRadio>
      </Menu>,
    );
    fireEvent.click(screen.getByRole("button", { name: "View" }));
    const row = screen.getByRole("menuitemradio", { name: "Day" });
    const line = document.getElementById(row.getAttribute("aria-describedby") ?? "");
    expect(line?.textContent).toBe("One day, hour by hour.");
    // The drawing is the row's picture only: a screen reader passes it by.
    expect(row.querySelector("[aria-hidden=true] svg")).not.toBeNull();
  });

  it("its own button closes it without swallowing anything", () => {
    const onPick = vi.fn();
    render(<Fruit onPick={onPick} />);
    const button = screen.getByRole("button", { name: "Fruit" });
    fireEvent.click(button);
    fireEvent.pointerDown(button);
    fireEvent.click(button);
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Elsewhere" }));
    expect(onPick).toHaveBeenCalledWith("outside");
  });
});
