import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { qk } from "../../api/keys";
import { t } from "../../lib/lang";
import { ShellContext } from "../../ui/shell";
import { AttentionButton } from "./AttentionButton";
import { AttentionPill } from "./AttentionPill";
import { sinceWords, type Problem } from "./data";

const navigate = vi.fn();
vi.mock("@tanstack/react-router", () => ({ useNavigate: () => navigate }));

beforeAll(() => {
  // jsdom has no modal dialogs and no animations; these stand in for what the sheet uses.
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
  navigate.mockClear();
});

const APPLE: Problem = {
  id: "sync:1",
  title: "Apple needs its password again.",
  key: "api.sync.needs_password",
  params: { name: "Apple" },
  detail: "Apple said that password isn't right.",
  since: null,
  page: "calendars",
  source: "calendar_sync",
};
const BACKUP: Problem = {
  id: "backup:stale",
  title: "The newest backup is over a week old.",
  key: "api.problems.backup_stale",
  params: {},
  detail: null,
  since: null,
  page: "backup",
  source: "core",
};

function draw(node: ReactNode, problems: Problem[], shell: "display" | "phone" = "display") {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  client.setQueryData(qk.problems(), problems);
  client.setQueryData(qk.session(), { device_kind: "phone", is_parent: true });
  client.setQueryData(["plugins"], []);
  render(
    <QueryClientProvider client={client}>
      <ShellContext.Provider value={shell}>{node}</ShellContext.Provider>
    </QueryClientProvider>,
  );
}

describe("Needs Attention (ADR 0034)", () => {
  it("counts in words", () => {
    expect(t("problems.pill.label", { n: 1 })).toBe("1 thing needs attention");
    expect(t("problems.pill.label", { n: 3 })).toBe("3 things need attention");
    expect(t("problems.button.aria", { n: 1 })).toBe("Needs attention: 1 thing");
  });

  it("says since when, with the day once it isn't today", () => {
    const now = new Date("2026-10-07T14:00:00Z");
    expect(sinceWords("2026-10-07T13:10:00Z", now)).toMatch(/^Since \d{1,2}:10/);
    expect(sinceWords("2026-10-05T13:10:00Z", now)).toMatch(/^Since \w{3}, Oct \d, /);
  });

  it("draws nothing at all while all is well", () => {
    draw(<AttentionButton />, []);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("is an icon in the wall's header that lists each problem with the page that fixes it", async () => {
    draw(<AttentionButton />, [APPLE, BACKUP]);
    fireEvent.click(screen.getByRole("button", { name: "Needs attention: 2 things" }));
    const sheet = screen.getByRole("dialog", { name: "Needs Attention" });
    expect(within(sheet).getByText("Apple needs its password again.")).toBeTruthy();
    expect(within(sheet).getByText("Apple said that password isn't right.")).toBeTruthy();
    expect(within(sheet).getByText("The newest backup is over a week old.")).toBeTruthy();
    expect(within(sheet).getByRole("button", { name: "Open Backup" })).toBeTruthy();
    fireEvent.click(within(sheet).getByRole("button", { name: "Open Calendars & Accounts" }));
    await vi.waitFor(() => {
      expect(navigate).toHaveBeenCalledWith({
        to: "/settings/$page",
        params: { page: "calendars" },
      });
    });
  });

  it("is a quiet pill on a phone's Today", () => {
    draw(<AttentionPill />, [BACKUP], "phone");
    fireEvent.click(screen.getByRole("button", { name: "1 thing needs attention" }));
    expect(screen.getByRole("dialog", { name: "Needs Attention" })).toBeTruthy();
  });
});
