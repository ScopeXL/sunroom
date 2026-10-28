import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import type { components } from "../../api/schema";
import { toasts } from "../../lib/toast";
import { ShellContext } from "../../ui/shell";
import { RenameScreenSheet } from "./RenameScreenSheet";

type Device = components["schemas"]["DeviceOut"];

const SCREEN: Device = {
  id: "00000000-0000-7000-8000-0000000000d2",
  label: "Wall screen",
  kind: "kiosk",
  form: "screen",
  member_name: null,
  is_kid_device: false,
  created_at: "2026-10-07T12:10:00Z",
  last_seen_at: "2026-10-07T12:40:00Z",
  is_current: false,
};

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
  HTMLElement.prototype.getAnimations = () => [];
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  toasts.set([]);
});

function draw(onClose = vi.fn()) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ShellContext.Provider value="display">
        <RenameScreenSheet device={SCREEN} onClose={onClose} />
      </ShellContext.Provider>
    </QueryClientProvider>,
  );
  return onClose;
}

describe("Rename Screen (Settings → Devices, ADR 0042)", () => {
  it("starts from the screen's own name, and a place names it", async () => {
    const sent: unknown[] = [];
    vi.spyOn(api, "PATCH").mockImplementation(
      (_path: string, init: { body: { label: string } }) => {
        sent.push(init.body);
        return Promise.resolve({
          data: { ...SCREEN, label: init.body.label },
          response: new Response(null, { status: 200 }),
        });
      },
    );
    const onClose = draw();
    const sheet = screen.getByRole("dialog", { name: "Rename Screen" });
    const field = within(sheet).getByLabelText<HTMLInputElement>("What should it be called?");
    expect(field.value).toBe("Wall screen");
    const save = within(sheet).getByRole<HTMLButtonElement>("button", { name: "Save Changes" });
    expect(save.disabled).toBe(true); // nothing changed yet
    fireEvent.click(within(sheet).getByRole("button", { name: "Hallway" }));
    expect(field.value).toBe("Hallway screen");
    expect(
      within(sheet).getByRole("button", { name: "Hallway" }).getAttribute("aria-pressed"),
    ).toBe("true");
    fireEvent.click(save);
    await waitFor(() => {
      expect(toasts.get().map((toast) => toast.message)).toEqual(["Renamed to Hallway screen"]);
    });
    expect(sent).toEqual([{ label: "Hallway screen" }]);
    expect(onClose).toHaveBeenCalled();
  });

  it("takes a name of its own, and Other clears the field for one", () => {
    draw();
    const sheet = screen.getByRole("dialog", { name: "Rename Screen" });
    const field = within(sheet).getByLabelText<HTMLInputElement>("What should it be called?");
    fireEvent.click(within(sheet).getByRole("button", { name: "Other" }));
    expect(field.value).toBe("");
    expect(
      within(sheet).getByRole<HTMLButtonElement>("button", { name: "Save Changes" }).disabled,
    ).toBe(true);
    fireEvent.change(field, { target: { value: "Sunroom by the door" } });
    expect(within(sheet).getByRole("button", { name: "Other" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
    expect(
      within(sheet).getByRole<HTMLButtonElement>("button", { name: "Save Changes" }).disabled,
    ).toBe(false);
  });
});
