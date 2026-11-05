import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createEventHandler, createInvalidator } from "./eventRouter";

let client: QueryClient;

beforeEach(() => {
  vi.useFakeTimers();
  client = new QueryClient();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("event router", () => {
  it("debounces repeated invalidations into one per key", () => {
    const spy = vi.spyOn(client, "invalidateQueries");
    const invalidate = createInvalidator(client);
    invalidate(["members"]);
    invalidate(["members"]);
    invalidate(["session"]);
    expect(spy).not.toHaveBeenCalled();
    vi.advanceTimersByTime(250);
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("never waits longer than a second under a steady stream", () => {
    const spy = vi.spyOn(client, "invalidateQueries");
    const invalidate = createInvalidator(client);
    for (let i = 0; i < 10; i++) {
      invalidate(["members"]);
      vi.advanceTimersByTime(200);
    }
    expect(spy).toHaveBeenCalled();
  });

  it("refetches the session when people, settings or devices change", () => {
    const spy = vi.spyOn(client, "invalidateQueries");
    const handle = createEventHandler(client, { onSignedOut: vi.fn() });
    for (const type of ["members.changed", "settings.changed", "devices.changed"]) {
      spy.mockClear();
      handle({ type });
      vi.advanceTimersByTime(250);
      expect(spy).toHaveBeenCalledWith({ queryKey: ["session"] });
    }
  });

  it("refreshes a plugin's own queries when its switch or settings change", () => {
    const spy = vi.spyOn(client, "invalidateQueries");
    const handle = createEventHandler(client, { onSignedOut: vi.fn() });
    const refreshed = (id: unknown) => {
      spy.mockClear();
      handle({ type: "plugins.changed", id, status: "running" });
      vi.advanceTimersByTime(250);
      return spy.mock.calls.map(([filters]) => filters?.queryKey);
    };
    // The screensaver's timing lives in its manifest: no waiting for it to go stale.
    expect(refreshed("screensaver")).toEqual([
      ["plugins"],
      ["problems"],
      ["occurrences"],
      ["screensaver"],
      ["photos"],
    ]);
    expect(refreshed("chores")).toEqual([["plugins"], ["problems"], ["occurrences"], ["chores"]]);
    expect(refreshed("meals")).toEqual([["plugins"], ["problems"], ["occurrences"], ["meals"]]);
    expect(refreshed("lists")).toEqual([["plugins"], ["problems"], ["occurrences"], ["lists"]]);
    expect(refreshed("countdowns")).toEqual([
      ["plugins"],
      ["problems"],
      ["occurrences"],
      ["countdowns"],
    ]);
    expect(refreshed("weather")).toEqual([["plugins"], ["problems"], ["occurrences"], ["weather"]]);
    expect(refreshed("calendar_sync")).toEqual([
      ["plugins"],
      ["problems"],
      ["occurrences"],
      ["calendar-sync"],
    ]);
    // A plugin this build has never heard of, or no id at all: everything, at once.
    expect(refreshed("something_new")).toEqual([
      undefined,
      ["plugins"],
      ["problems"],
      ["occurrences"],
    ]);
    expect(refreshed(undefined)).toEqual([undefined, ["plugins"], ["problems"], ["occurrences"]]);
  });

  it("asks Needs Attention again when something it reports may have changed (ADR 0034)", () => {
    const spy = vi.spyOn(client, "invalidateQueries");
    const handle = createEventHandler(client, { onSignedOut: vi.fn() });
    for (const type of [
      "sync.changed",
      "screensaver.changed",
      "photos.changed",
      "settings.changed",
    ]) {
      spy.mockClear();
      handle({ type });
      vi.advanceTimersByTime(250);
      expect(spy, type).toHaveBeenCalledWith({ queryKey: ["problems"] });
    }
  });

  it("hands commands for the wall screen to the shell", () => {
    const onKioskCommand = vi.fn();
    const handle = createEventHandler(client, { onSignedOut: vi.fn(), onKioskCommand });
    handle({ type: "kiosk.command", command: "reload" });
    expect(onKioskCommand).toHaveBeenCalledWith("reload", {
      type: "kiosk.command",
      command: "reload",
    });
  });

  it("says when Sunroom is running itself again (ADR 0034)", () => {
    const onRestarting = vi.fn();
    const handle = createEventHandler(client, { onSignedOut: vi.fn(), onRestarting });
    handle({ type: "server.restarting", reason: "restore" });
    expect(onRestarting).toHaveBeenCalledWith("restore");
    handle({ type: "server.updating" });
    expect(onRestarting).toHaveBeenCalledWith("update");
  });

  it("signs out on session.expired and refetches everything on resync", () => {
    const onSignedOut = vi.fn();
    const spy = vi.spyOn(client, "invalidateQueries");
    const handle = createEventHandler(client, { onSignedOut });
    handle({ type: "hello", mode: "resync" });
    expect(spy).toHaveBeenCalledWith();
    handle({ type: "session.expired" });
    expect(onSignedOut).toHaveBeenCalledOnce();
  });
});
