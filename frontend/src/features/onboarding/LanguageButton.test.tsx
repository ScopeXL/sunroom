import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { getLanguage, setLanguage } from "../../lib/lang";
import { LanguageButton, LanguagePicker } from "./LanguageButton";

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
  HTMLElement.prototype.getAnimations = () => [];
});

afterEach(async () => {
  cleanup();
  await setLanguage("en", { remember: false });
});

describe("Choose a Language (ADR 0043)", () => {
  it("opens from the globe with the page's language checked, and closes with Done", () => {
    render(<LanguageButton />);
    fireEvent.click(screen.getByRole("button", { name: "Language: English" }));
    const sheet = screen.getByRole("dialog", { name: "Choose a Language" });
    const english = within(sheet).getByRole("radio", { name: "English" });
    expect(english.getAttribute("aria-checked")).toBe("true");
    // Spanish is a preview until it's translated: it isn't offered.
    expect(
      within(sheet)
        .getAllByRole("radio")
        .map((choice) => choice.textContent),
    ).toEqual(["English"]);
    fireEvent.click(english);
    expect(getLanguage()).toBe("en");
    fireEvent.click(within(sheet).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("names the page's language in that language's own words", async () => {
    await setLanguage("es");
    render(<LanguageButton />);
    expect(screen.getByRole("button", { name: "Language: Español" })).toBeTruthy();
  });

  it("offers the complete languages side by side, the chosen one pressed", () => {
    const onChange = vi.fn();
    render(<LanguagePicker label="Language" value="en" onChange={onChange} />);
    const english = within(screen.getByRole("group", { name: "Language" })).getByRole("button", {
      name: "English",
    });
    expect(english.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(english);
    expect(onChange).toHaveBeenCalledWith("en");
  });
});
