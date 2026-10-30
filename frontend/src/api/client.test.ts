import { afterEach, describe, expect, it } from "vitest";

import { setLanguage, t } from "../lib/lang";
import { ApiError, errorMessage, notSaved, unwrap } from "./client";

function refused(status: number, error: Record<string, unknown>): ApiError {
  try {
    unwrap({ error: { error }, response: new Response(null, { status }) });
  } catch (thrown) {
    if (thrown instanceof ApiError) return thrown;
  }
  throw new Error("unwrap didn't refuse");
}

afterEach(async () => {
  await setLanguage("en", { remember: false });
});

describe("a refusal from the server (ADR 0043)", () => {
  it("keeps the sentence's key and values beside the server's English", () => {
    const error = refused(409, {
      code: "already_done",
      message: "Mia did it already.",
      key: "api.tasks.already_done",
      params: { name: "Mia" },
    });
    expect([error.status, error.code, error.message]).toEqual([
      409,
      "already_done",
      "Mia did it already.",
    ]);
    expect([error.key, error.params]).toEqual(["api.tasks.already_done", { name: "Mia" }]);
    expect(errorMessage(error)).toBe("Mia did it already.");
  });

  it("is said in the page's language when the page knows the key", async () => {
    const error = refused(409, {
      code: "already_done",
      message: "Mia did it already.",
      key: "api.tasks.already_done",
      params: { name: "Mia" },
    });
    await setLanguage("pseudo", { remember: false });
    expect(errorMessage(error)).toBe(t("api.tasks.already_done", { name: "Mia" }));
    expect(errorMessage(error)).not.toBe("Mia did it already.");
    expect(notSaved(error)).toContain(errorMessage(error));
  });

  it("says the server's English for a key this page doesn't know", async () => {
    const error = refused(409, {
      code: "brand_new",
      message: "A sentence from a newer Sunroom.",
      key: "api.brand.new",
      params: {},
    });
    await setLanguage("pseudo", { remember: false });
    expect(errorMessage(error)).toBe("A sentence from a newer Sunroom.");
  });

  it("names the generic sentence when the server said nothing", () => {
    const error = refused(502, {});
    expect([error.code, error.key, error.message]).toEqual([
      "error",
      "app.error.generic",
      t("app.error.generic"),
    ]);
  });

  it("an error from before keys still reads as its message", () => {
    expect(errorMessage(new ApiError(403, "pin", "PIN needed."))).toBe("PIN needed.");
    expect(errorMessage(new Error("boom"))).toBe(t("app.offline.error"));
  });
});
