import { beforeEach, describe, expect, it } from "vitest";

import { migrateLegacyLocalStorage } from "./legacyStorage";

describe("pre-Mosael localStorage migration", () => {
  let storage: Storage;

  beforeEach(() => {
    const values = new Map<string, string>();
    storage = {
      get length() { return values.size; },
      clear: () => values.clear(),
      getItem: (key) => values.get(key) ?? null,
      key: (index) => [...values.keys()][index] ?? null,
      removeItem: (key) => { values.delete(key); },
      setItem: (key, value) => { values.set(key, String(value)); },
    };
  });

  it("moves old values and removes their source keys", () => {
    storage.setItem("openstudio.auth.token", "old-token");
    storage.setItem("open-studio:workspace", "workspace-1");

    migrateLegacyLocalStorage(storage);

    expect(storage.getItem("mosael.auth.token")).toBe("old-token");
    expect(storage.getItem("mosael:workspace")).toBe("workspace-1");
    expect(storage.getItem("openstudio.auth.token")).toBeNull();
    expect(storage.getItem("open-studio:workspace")).toBeNull();
  });

  it("keeps the current value when both generations exist", () => {
    storage.setItem("openstudio.auth.token", "stale-token");
    storage.setItem("mosael.auth.token", "current-token");

    migrateLegacyLocalStorage(storage);

    expect(storage.getItem("mosael.auth.token")).toBe("current-token");
    expect(storage.getItem("openstudio.auth.token")).toBeNull();
  });

  it("cannot restore a cleared token on a later launch", () => {
    storage.setItem("openstudio.auth.token", "old-token");
    migrateLegacyLocalStorage(storage);
    storage.removeItem("mosael.auth.token");

    migrateLegacyLocalStorage(storage);

    expect(storage.getItem("mosael.auth.token")).toBeNull();
  });
});
