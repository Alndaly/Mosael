import { describe, expect, it } from "vitest";

import {
  clearCurrentAndLegacy,
  readMigratedValue,
  type ExtensionStorageArea,
} from "../src/storageMigration";

function memoryStorage(initial: Record<string, unknown>): ExtensionStorageArea & { values: Record<string, unknown> } {
  const values = { ...initial };
  return {
    values,
    async get(keys) {
      return Object.fromEntries(keys.filter((key) => key in values).map((key) => [key, values[key]]));
    },
    async set(items) {
      Object.assign(values, items);
    },
    async remove(keys) {
      for (const key of Array.isArray(keys) ? keys : [keys]) delete values[key];
    },
  };
}

describe("extension storage migration", () => {
  it("moves a legacy value and removes the old source", async () => {
    const storage = memoryStorage({ "openstudio.connection": { token: "old" } });

    await expect(
      readMigratedValue(storage, "mosael.connection", "openstudio.connection"),
    ).resolves.toEqual({ token: "old" });
    expect(storage.values).toEqual({ "mosael.connection": { token: "old" } });
  });

  it("does not overwrite a current value", async () => {
    const storage = memoryStorage({
      "mosael.locale": "en",
      "openstudio.locale": "zh-CN",
    });

    await expect(readMigratedValue(storage, "mosael.locale", "openstudio.locale")).resolves.toBe("en");
    expect(storage.values).toEqual({ "mosael.locale": "en" });
  });

  it("treats an explicit current null as authoritative", async () => {
    const storage = memoryStorage({
      "mosael.connection": null,
      "openstudio.connection": { token: "old" },
    });

    await expect(
      readMigratedValue(storage, "mosael.connection", "openstudio.connection"),
    ).resolves.toBeNull();
    expect(storage.values).toEqual({ "mosael.connection": null });
  });

  it("clears both generations so disconnect cannot be undone", async () => {
    const storage = memoryStorage({
      "mosael.connection": { token: "current" },
      "openstudio.connection": { token: "old" },
    });

    await clearCurrentAndLegacy(storage, "mosael.connection", "openstudio.connection");

    expect(storage.values).toEqual({});
  });
});
