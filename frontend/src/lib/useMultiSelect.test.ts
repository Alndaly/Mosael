/** @vitest-environment jsdom */
/**
 * 多选的状态机 —— **只有这一份**。
 *
 * 素材页先有了一套(选择模式 / 已选 N 项 / 全选切换 / 批量动作 / 取消),现在发布记录和
 * 工作流也要。抄第二遍、第三遍必然分叉:最容易漏的是**退出选择模式时把已选清空**,
 * 漏掉它的话下次进选择模式,上一批还勾着 —— 而批量删除会照着那批执行。
 *
 * 另一条是「全选」按钮的语义:它作用于**当前可见的那些**(筛选/搜索之后),不是全库;
 * 已经全选时再点是取消。这条在素材页是对的,抄的时候很容易变成"全选全部"。
 */
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useMultiSelect } from "@/lib/useMultiSelect";

const items = (...ids: string[]) => ids.map((id) => ({ id }));

describe("多选", () => {
  it("默认不在选择模式,也没有选中项", () => {
    const { result } = renderHook(() => useMultiSelect(items("a", "b"), (item) => item.id));

    expect(result.current.selectMode).toBe(false);
    expect(result.current.selectedIds.size).toBe(0);
  });

  it("勾选与取消勾选", () => {
    const { result } = renderHook(() => useMultiSelect(items("a", "b"), (item) => item.id));

    act(() => result.current.toggle("a"));
    expect([...result.current.selectedIds]).toEqual(["a"]);

    act(() => result.current.toggle("a"));
    expect(result.current.selectedIds.size).toBe(0);
  });

  it("全选只作用于**当前可见**的那些,不是全部", () => {
    const { result } = renderHook(() => useMultiSelect(items("a", "b"), (item) => item.id));

    act(() => result.current.selectAll(items("a")));

    expect([...result.current.selectedIds]).toEqual(["a"]);
  });

  it("已经全选时再点全选 = 取消", () => {
    const { result } = renderHook(() => useMultiSelect(items("a", "b"), (item) => item.id));

    act(() => result.current.selectAll(items("a", "b")));
    expect(result.current.allSelected(items("a", "b"))).toBe(true);

    act(() => result.current.selectAll(items("a", "b")));
    expect(result.current.selectedIds.size).toBe(0);
  });

  it("一个可见项都没有时,不算「已全选」—— 否则空列表上那个按钮会写着「取消全选」", () => {
    const { result } = renderHook(() => useMultiSelect(items(), (item) => item.id));

    expect(result.current.allSelected([])).toBe(false);
  });

  it("**退出选择模式会清空已选** —— 漏掉这条,下次进来上一批还勾着,而批量删除照着那批执行", () => {
    const { result } = renderHook(() => useMultiSelect(items("a", "b"), (item) => item.id));

    act(() => result.current.setSelectMode(true));
    act(() => result.current.toggle("a"));
    act(() => result.current.exit());

    expect(result.current.selectMode).toBe(false);
    expect(result.current.selectedIds.size).toBe(0);
  });

  it("选中的东西已经不在列表里了就不再算数(别人删掉了 / 筛选变了)", () => {
    const { result, rerender } = renderHook(({ list }) => useMultiSelect(list, (item: { id: string }) => item.id), {
      initialProps: { list: items("a", "b") },
    });

    act(() => result.current.toggle("b"));
    rerender({ list: items("a") });

    expect(result.current.selectedIds.has("b")).toBe(false);
  });
});
