/** @vitest-environment jsdom */
/**
 * useVersionedDocument 不经任何编辑器直接测:假的 load / save,看保存、冲突、跟进、撤销这几件事。
 * 此前这些只能靠把整个 3D 场景编辑器渲染出来测。
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useVersionedDocument, type Versioned, type VersionedDocumentOptions } from "./useVersionedDocument";

class Conflict extends Error {}

type Doc = { text: string };

function server(initial: Versioned<Doc>) {
  let latest = initial;
  const saves: { value: Doc; base: number }[] = [];
  let conflictOnce = false;
  return {
    get latest() {
      return latest;
    },
    saves,
    /** 别处先存了一版。 */
    elsewhere(value: Doc) {
      latest = { value, revision: latest.revision + 1 };
    },
    conflictNext() {
      conflictOnce = true;
    },
    options(extra: Partial<VersionedDocumentOptions<Doc>> = {}): VersionedDocumentOptions<Doc> {
      return {
        initial,
        autosaveDelay: 5,
        load: async () => latest,
        save: async (value, base) => {
          saves.push({ value, base });
          if (conflictOnce || base !== latest.revision) {
            conflictOnce = false;
            throw new Conflict();
          }
          latest = { value, revision: base + 1 };
          return latest.revision;
        },
        isConflict: (error) => error instanceof Conflict,
        ...extra,
      };
    },
  };
}

describe("useVersionedDocument", () => {
  it("改了就带着底子存,下一次带的是存上之后的修订号", async () => {
    const remote = server({ value: { text: "a" }, revision: 1 });
    const { result } = renderHook(() => useVersionedDocument(remote.options()));
    act(() => result.current.change({ text: "b" }));
    await waitFor(() => expect(remote.saves).toHaveLength(1));
    expect(remote.saves[0]).toEqual({ value: { text: "b" }, base: 1 });
    await waitFor(() => expect(result.current.revision()).toBe(2));
    act(() => result.current.change({ text: "c" }));
    await waitFor(() => expect(remote.saves).toHaveLength(2));
    expect(remote.saves[1].base).toBe(2);
    expect(result.current.unsaved()).toBe(false);
  });

  it("撞了 409:换成服务端那份、清掉撤销、告诉调用方;被换掉的那份之后不再被送出去(卸载时也不)", async () => {
    const remote = server({ value: { text: "a" }, revision: 1 });
    const onConflict = vi.fn();
    const { result, unmount } = renderHook(() => useVersionedDocument(remote.options({ onConflict })));
    remote.elsewhere({ text: "theirs" });
    act(() => result.current.change({ text: "mine" }));
    await waitFor(() => expect(onConflict).toHaveBeenCalledTimes(1));
    expect(result.current.value).toEqual({ text: "theirs" });
    expect(result.current.revision()).toBe(2);
    expect(result.current.canUndo).toBe(false);
    act(() => result.current.undo());
    expect(result.current.value).toEqual({ text: "theirs" });

    unmount();
    await Promise.resolve();
    //: 只有撞上的那一次:卸载时没有把「mine」带着新底子补发出去。
    expect(remote.saves.map((one) => one.value.text)).toEqual(["mine"]);
    expect(remote.latest.value).toEqual({ text: "theirs" });
  });

  it("冲突之后接着改,基于服务端那份、带新修订号存", async () => {
    const remote = server({ value: { text: "a" }, revision: 1 });
    const { result } = renderHook(() => useVersionedDocument(remote.options()));
    remote.conflictNext();
    remote.elsewhere({ text: "theirs" });
    act(() => result.current.change({ text: "mine" }));
    await waitFor(() => expect(result.current.value).toEqual({ text: "theirs" }));
    act(() => result.current.change({ text: "theirs+mine" }));
    await waitFor(() => expect(remote.latest.value).toEqual({ text: "theirs+mine" }));
    expect(remote.saves.at(-1)?.base).toBe(2);
  });

  it("本地干净时跟进别处存的新版本;本地有欠着的改动时不动它", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const remote = server({ value: { text: "a" }, revision: 1 });
      const save = vi.fn(async () => 99);
      const { result } = renderHook(() =>
        useVersionedDocument(remote.options({ followEveryMs: 1000, save, autosaveDelay: 60_000 })),
      );
      remote.elsewhere({ text: "agent" });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(result.current.value).toEqual({ text: "agent" });
      expect(result.current.revision()).toBe(2);

      act(() => result.current.change({ text: "local" }));
      remote.elsewhere({ text: "agent again" });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(3000);
      });
      expect(result.current.value).toEqual({ text: "local" });
    } finally {
      vi.useRealTimers();
    }
  });

  it("一次手势只占撤销栈的一步;onUnsaved 报出没存上的那份,存上后报 null", async () => {
    const remote = server({ value: { text: "" }, revision: 1 });
    const onUnsaved = vi.fn();
    const { result } = renderHook(() => useVersionedDocument(remote.options({ onUnsaved })));
    act(() => {
      for (const text of ["h", "he", "hel", "hell", "hello"]) result.current.change({ text }, { gesture: "typing" });
    });
    expect(onUnsaved).toHaveBeenLastCalledWith({ text: "hello" });
    act(() => result.current.undo());
    expect(result.current.value).toEqual({ text: "" });
    act(() => result.current.redo());
    await waitFor(() => expect(onUnsaved).toHaveBeenLastCalledWith(null));
    expect(remote.latest.value).toEqual({ text: "hello" });
  });
});
