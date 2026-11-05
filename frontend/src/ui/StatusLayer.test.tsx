import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const sw = { needRefresh: false, update: vi.fn(() => Promise.resolve()) };

vi.mock("virtual:pwa-register/react", () => ({
  useRegisterSW: () => ({
    needRefresh: [sw.needRefresh, vi.fn()],
    offlineReady: [false, vi.fn()],
    updateServiceWorker: sw.update,
  }),
}));

const { OfflinePill, ToastRegion, UpdatePrompt } = await import("./StatusLayer");
const { connection } = await import("../lib/connection");
const { anchorToasts, showToast, toasts } = await import("../lib/toast");
const { forgetRestart, restarting } = await import("../lib/restart");

afterEach(() => {
  cleanup();
  sw.needRefresh = false;
  connection.set({ server: "unknown", showOffline: false, lastReachableAt: null });
  toasts.set([]);
  forgetRestart();
});

describe("the quiet pill", () => {
  it("says Sunroom is updating, before it goes and while it's away", () => {
    restarting.set("update");
    render(<OfflinePill />);
    expect(screen.getByRole("status").textContent).toBe("Sunroom is updating. Back in a minute.");
    act(() => {
      connection.set({ server: "unreachable", showOffline: true, lastReachableAt: null });
    });
    expect(screen.getByRole("status").textContent).toBe("Sunroom is updating. Back in a minute.");
  });

  it("stays quiet for a restore, which says so its own way", () => {
    restarting.set("restore");
    render(<OfflinePill />);
    expect(screen.getByRole("status").textContent).toBe("");
  });
});

describe("the update prompt", () => {
  it("offers Refresh when a new version is waiting", () => {
    sw.needRefresh = true;
    render(<UpdatePrompt />);
    screen.getByRole("button", { name: "Refresh" }).click();
    expect(sw.update).toHaveBeenCalledWith(true);
  });

  it("stays away otherwise", () => {
    render(<UpdatePrompt />);
    expect(screen.queryByRole("button", { name: "Refresh" })).toBeNull();
  });
});

describe("looking for a new version (ADR 0034)", () => {
  it("looks hourly and when the page comes back, and stops when the shell unmounts", async () => {
    vi.useFakeTimers();
    const update = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "serviceWorker", {
      configurable: true,
      value: { getRegistration: () => Promise.resolve({ update }) },
    });
    try {
      const view = render(<UpdatePrompt />);
      await act(() => vi.advanceTimersByTimeAsync(60 * 60 * 1000));
      expect(update).toHaveBeenCalledTimes(1);
      document.dispatchEvent(new Event("visibilitychange"));
      await act(() => vi.advanceTimersByTimeAsync(0));
      expect(update).toHaveBeenCalledTimes(2);
      // The wall remounts its shell on every room change: no timer is left behind.
      view.unmount();
      await act(() => vi.advanceTimersByTimeAsync(3 * 60 * 60 * 1000));
      expect(update).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
      Reflect.deleteProperty(navigator, "serviceWorker");
    }
  });
});

describe("the connection pill (UX §8)", () => {
  it("says nothing while the server answers", () => {
    render(<OfflinePill />);
    expect(screen.getByRole("status").textContent).toBe("");
  });

  it("is quiet on a phone and says when the wall screen last heard from the server", () => {
    connection.set({
      server: "unreachable",
      showOffline: true,
      lastReachableAt: Date.UTC(2026, 9, 7, 13, 10),
    });
    const view = render(<OfflinePill />);
    expect(screen.getByRole("status").textContent).toBe("Offline · showing what we had");
    view.unmount();
    render(<OfflinePill display />);
    expect(screen.getByRole("status").textContent).toMatch(/^Can't reach Sunroom · showing /);
  });
});

describe("toasts", () => {
  it("show their action, and the action runs once", () => {
    const undo = vi.fn();
    render(<ToastRegion />);
    act(() => {
      showToast("Removed Mia", { label: "Undo", onAction: undo });
    });
    screen.getByRole("button", { name: "Undo" }).click();
    expect(undo).toHaveBeenCalledOnce();
  });

  it("sit over the wall's board, whichever side the rail is on and with the panel hidden", () => {
    const region = () => screen.getByRole("status").className;
    const left = render(<ToastRegion display />);
    expect(region()).toContain("left-[var(--rail-w)] right-[var(--panel-w)]");
    left.unmount();
    const right = render(<ToastRegion display railSide="right" />);
    expect(region()).toContain("left-[var(--panel-w)] right-[var(--rail-w)]");
    right.unmount();
    const alone = render(<ToastRegion display railSide="right" panelShown={false} />);
    expect(region()).toContain("left-0 right-[var(--rail-w)]");
    alone.unmount();
    render(<ToastRegion display panelShown={false} />);
    expect(region()).toContain("left-[var(--rail-w)] right-0");
  });

  it("stay where they were raised: on the page under a sheet, in a sheet while it's open", () => {
    render(<ToastRegion />);
    const region = screen.getByRole("status");
    act(() => {
      showToast("Changes saved");
    });
    // A sheet opens over it: the toast stays on the page, under the sheet's backdrop.
    const sheet = document.createElement("div");
    document.body.append(sheet);
    let sheetGone: () => void = () => undefined;
    act(() => {
      sheetGone = anchorToasts(sheet);
    });
    const saved = screen.getByText("Changes saved");
    expect(region.contains(saved)).toBe(true);
    // Raised while the sheet is open: in the sheet.
    act(() => {
      showToast("Copied the helper's address");
    });
    expect(sheet.contains(screen.getByText("Copied the helper's address"))).toBe(true);
    expect(region.contains(screen.getByText("Changes saved"))).toBe(true);
    // The sheet goes: its toast goes back to the page.
    act(() => {
      sheetGone();
    });
    expect(region.contains(screen.getByText("Copied the helper's address"))).toBe(true);
    sheet.remove();
  });
});
