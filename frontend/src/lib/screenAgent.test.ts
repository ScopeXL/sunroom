import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { qk } from "../api/keys";
import { toasts } from "./toast";
import {
  createScreenClient,
  forgetScreenAgent,
  keepPairing,
  listen,
  noteScreenAgent,
  screenAgentPort,
  screenClient,
  screenProgress,
  screenReloadUrl,
} from "./screenAgent";

afterEach(() => {
  forgetScreenAgent();
  vi.unstubAllGlobals();
  toasts.set([]);
});

describe("the wall's own Sunroom Screen agent (ADR 0035)", () => {
  it("is named once, on /display, by the launcher's ?screen=", () => {
    expect(noteScreenAgent("/display", "?dimmer=screen&screen=7800")).toBe(7800);
    expect(screenAgentPort()).toBe(7800);
    // Read once, at the start: a later address doesn't change it.
    expect(noteScreenAgent("/display", "?screen=7900")).toBe(7800);
    expect(screenReloadUrl("screen")).toBe("/display?dimmer=screen&screen=7800");
    expect(screenClient()).not.toBeNull();
  });

  it("is absent without the parameter, and nothing calls it", () => {
    expect(noteScreenAgent("/display", "?dimmer=page")).toBeNull();
    expect(screenClient()).toBeNull();
    expect(screenReloadUrl("page")).toBeNull();
  });

  it.each([
    ["/display", "?screen=80"],
    ["/display", "?screen=abc"],
    ["/display", "?screen=70000"],
    ["/display", "?screen=7800&screen=7801"],
    ["/display", "?screen=-7800"],
    ["/settings/family", "?screen=7800"],
    ["/", "?screen=7800"],
  ])("ignores %s%s: only that one document's policy lets it through", (path, search) => {
    expect(noteScreenAgent(path, search)).toBeNull();
  });

  it("asks the agent to keep a fresh pairing, and only where there is one (ADR 0040)", async () => {
    const seen: Request[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((request: Request) => {
        seen.push(request);
        return Promise.resolve(new Response(JSON.stringify({ ok: true }), { status: 202 }));
      }),
    );
    noteScreenAgent("/display", "?dimmer=page");
    keepPairing(); // a laptop's /display: no agent, nothing sent
    expect(seen).toEqual([]);
    forgetScreenAgent();
    noteScreenAgent("/display", "?dimmer=screen&screen=7800");
    keepPairing();
    await vi.waitFor(() => {
      expect(seen).toHaveLength(1);
    });
    expect([seen[0]?.method, seen[0]?.url]).toEqual([
      "POST",
      "http://127.0.0.1:7800/api/screen/keep-pairing",
    ]);
    expect(seen[0]?.headers.get("X-Sunroom-Screen")).toBe("1");
  });

  it("sends X-Sunroom-Screen on a change and nothing extra on a read", async () => {
    const seen: Request[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((request: Request) => {
        seen.push(request);
        return Promise.resolve(
          new Response(JSON.stringify({ ok: true }), {
            status: 202,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }),
    );
    const agent = createScreenClient("http://127.0.0.1:7800");
    await agent.POST("/api/screen/restart");
    await agent.GET("/api/screen/about");
    expect(seen.map((request) => [request.method, request.url])).toEqual([
      ["POST", "http://127.0.0.1:7800/api/screen/restart"],
      ["GET", "http://127.0.0.1:7800/api/screen/about"],
    ]);
    expect(seen[0]?.headers.get("X-Sunroom-Screen")).toBe("1");
    expect(seen[1]?.headers.get("X-Sunroom-Screen")).toBeNull();
    // Never the family's cookies: they're Sunroom's, not the agent's.
    expect(seen[0]?.credentials).not.toBe("include");
  });

  it("follows the event stream into the cache and the progress", () => {
    const queryClient = new QueryClient();
    const source = new EventTarget() as EventSource;
    const stop = listen(source, queryClient);
    source.dispatchEvent(
      new MessageEvent("state", { data: JSON.stringify({ version: "0.13.0", platform: "pi" }) }),
    );
    expect(queryClient.getQueryData(qk.screen.state())).toEqual({
      version: "0.13.0",
      platform: "pi",
    });
    source.dispatchEvent(
      new MessageEvent("update.progress", {
        data: JSON.stringify({ percent: 40, step: "Installing…" }),
      }),
    );
    expect(screenProgress.get()).toEqual({ percent: 40, step: "Installing…" });
    source.dispatchEvent(
      new MessageEvent("update.progress", { data: JSON.stringify({ percent: 100, step: "Done" }) }),
    );
    expect(screenProgress.get()).toBeNull();
    stop();
  });

  it("says the agent's toasts by their keys, and its English for a key it doesn't know", () => {
    const source = new EventTarget() as EventSource;
    const stop = listen(source, new QueryClient());
    const toast = (said: object) => {
      source.dispatchEvent(new MessageEvent("toast", { data: JSON.stringify(said) }));
    };
    toast({ message: "English", key: "agent.wifi.out_of_range", params: { ssid: "HomeNet" } });
    toast({ message: "A sentence from a newer agent.", key: "agent.not.here.yet", params: {} });
    toast({ message: "From an agent before 0.18.0." });
    expect(toasts.get().map((shown) => shown.message)).toEqual([
      "HomeNet is out of range. Move closer, or try another network.",
      "A sentence from a newer agent.",
      "From an agent before 0.18.0.",
    ]);
    stop();
  });
});
