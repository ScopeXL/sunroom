import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { keyboard, watchKeyboardFields } from "../lib/keyboard";
import { KeyboardHost } from "./Keyboard";

function Field({ onSubmit = () => undefined }: { onSubmit?: () => void }) {
  const [value, setValue] = useState("");
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <label>
        Name
        <input
          data-osk="text"
          inputMode="none"
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
          }}
        />
      </label>
    </form>
  );
}

let stop: () => void;
beforeAll(() => {
  // jsdom has no layout, so no scrollIntoView.
  Element.prototype.scrollIntoView = vi.fn();
});
beforeEach(() => {
  stop = watchKeyboardFields();
});
afterEach(() => {
  stop();
  cleanup();
  keyboard.set({ target: null, layout: "text", open: false });
});

function press(name: string) {
  fireEvent.click(screen.getByRole("button", { name }));
}

describe("the on-screen keyboard (UX §1)", () => {
  it("rises when a field is focused and types into it as React expects", () => {
    render(
      <>
        <Field />
        <KeyboardHost rail="left" />
      </>,
    );
    expect(screen.queryByRole("group", { name: "On-screen keyboard" })).toBeNull();
    const input = screen.getByLabelText("Name");
    act(() => {
      input.focus();
    });
    expect(screen.getByRole("group", { name: "On-screen keyboard" })).toBeTruthy();
    // Shift is automatic for the first letter.
    press("M");
    press("i");
    press("a");
    expect((input as HTMLInputElement).value).toBe("Mia");
    press("Delete");
    expect((input as HTMLInputElement).value).toBe("Mi");
  });

  it("shows letters only, with the numbers on 123, and the number pad unchanged", () => {
    render(
      <>
        <Field />
        <KeyboardHost rail="left" />
      </>,
    );
    const input = screen.getByLabelText<HTMLInputElement>("Name");
    act(() => {
      input.focus();
    });
    // The first row is the letters' own (ADR 0035): no row of numbers above q any more.
    const keys = screen.getByRole("group", { name: "On-screen keyboard" });
    const labels = [...keys.querySelectorAll("button")].map((key) =>
      key.getAttribute("aria-label"),
    );
    expect(labels.slice(0, 10)).toEqual(["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"]);
    expect(screen.queryByRole("button", { name: "1" })).toBeNull();
    // 123 is the way to the numbers: one row of them, typed as they are.
    press("Numbers and symbols");
    expect(screen.getAllByRole("button", { name: "1" })).toHaveLength(1);
    press("2");
    press("Letters");
    press("b");
    expect(input.value).toBe("2b");
    // The number pad has its digits, and no row above them.
    act(() => {
      keyboard.set({ ...keyboard.get(), layout: "numeric" });
    });
    expect(screen.getAllByRole("button", { name: "1" })).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Q" })).toBeNull();
  });

  it("goes inside an open sheet, because the page behind a modal dialog can't be tapped", () => {
    render(
      <>
        <dialog open aria-label="Edit Mia">
          <Field />
        </dialog>
        <KeyboardHost rail="left" />
      </>,
    );
    const input = screen.getByLabelText("Name");
    act(() => {
      input.focus();
    });
    const keys = screen.getByRole("group", { name: "On-screen keyboard" });
    expect(screen.getByRole("dialog", { name: "Edit Mia" }).contains(keys)).toBe(true);
    press("L");
    expect((input as HTMLInputElement).value).toBe("L");
  });

  it("Done lowers it and keeps what was typed; Enter submits the field's form", () => {
    const submitted = vi.fn();
    render(
      <>
        <Field onSubmit={submitted} />
        <KeyboardHost rail="left" />
      </>,
    );
    const input = screen.getByLabelText("Name");
    act(() => {
      input.focus();
    });
    press("S");
    press("Enter");
    expect(submitted).toHaveBeenCalledOnce();
    act(() => {
      press("Done");
    });
    expect(keyboard.get().open).toBe(false);
    expect((input as HTMLInputElement).value).toBe("S");
  });

  it("types into a box of words too, where Enter starts a new line (ADR 0042)", () => {
    const submitted = vi.fn();
    function Words() {
      const [value, setValue] = useState("");
      return (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            submitted();
          }}
        >
          <label>
            What happened
            <textarea
              data-osk="text"
              inputMode="none"
              value={value}
              onChange={(event) => {
                setValue(event.target.value);
              }}
            />
          </label>
        </form>
      );
    }
    render(
      <>
        <Words />
        <KeyboardHost rail="left" />
      </>,
    );
    const box = screen.getByLabelText<HTMLTextAreaElement>("What happened");
    act(() => {
      box.focus();
    });
    expect(screen.getByRole("group", { name: "On-screen keyboard" })).toBeTruthy();
    press("H");
    press("i");
    press("Enter");
    press("Y");
    expect(box.value).toBe("Hi\nY");
    expect(submitted).not.toHaveBeenCalled();
    press("Delete");
    press("Delete");
    expect(box.value).toBe("Hi");
  });

  it("stays down while a physical keyboard is in use", () => {
    render(
      <>
        <Field />
        <KeyboardHost rail="left" />
      </>,
    );
    fireEvent.keyDown(window, { key: "a" });
    act(() => {
      screen.getByLabelText("Name").focus();
    });
    expect(keyboard.get().open).toBe(false);
  });
});
