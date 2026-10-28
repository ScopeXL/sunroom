import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";

import { ShellContext, type ShellKind } from "../../ui/shell";
import { DiscordButton } from "./DiscordButton";

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
  HTMLElement.prototype.getAnimations = () => [];
});

afterEach(cleanup);

function draw(kiosk: boolean, shell: ShellKind) {
  render(
    <ShellContext.Provider value={shell}>
      <DiscordButton kiosk={kiosk} />
    </ShellContext.Provider>,
  );
}

describe("the Sunroom Discord in Settings' header (ADR 0042)", () => {
  it("is a link on a device, opening a new tab", () => {
    for (const shell of ["phone", "display"] as const) {
      draw(false, shell);
      const link = screen.getByRole("link", { name: "Sunroom's Discord" });
      expect(link.getAttribute("href")).toBe("https://discord.gg/y6AeQRpsPQ");
      expect(link.getAttribute("target")).toBe("_blank");
      expect(link.getAttribute("rel")).toBe("noreferrer noopener");
      // The mark alone: its name is the link's.
      expect(link.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
      cleanup();
    }
  });

  it("shows a code to scan on a paired screen, which opens no other website", () => {
    draw(true, "display");
    expect(screen.queryByRole("link")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Sunroom's Discord" }));
    const sheet = screen.getByRole("dialog", { name: "Join the Sunroom Discord" });
    expect(
      within(sheet).getByRole("img", { name: "A code that opens the Sunroom Discord" }),
    ).toBeTruthy();
    expect(within(sheet).getByText("Scan this with your phone.")).toBeTruthy();
    fireEvent.click(within(sheet).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog", { name: "Join the Sunroom Discord" })).toBeNull();
  });
});
