/** @vitest-environment jsdom */

/**
 * 画板页已经挂着时,「打开另一张」要真的打开;地址里没被接住的 `?board=` 不能留着当延时炸弹。
 *
 * 实测过的两步(生产构建,隔离后端):开着画板 A,照「回到那里」/ 智能体带路的老写法只改 hash 去画板 B → 仍停在 A;
 * 回列表点「新建画板」→ 打开的是 B,新建的那张没打开。画板页在这里换成一个只有列表和「开着哪张」的替身,
 * 收请求的两条路(地址里的参数、信箱)和 BoardsView 用的是同一对 hook。
 */

import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { OPEN_BOARD_EVENT, openBoard, useHashOpenRequest, useOpenRequest } from "./deepLink";

let setBoards: (ids: string[]) => void = () => undefined;
let createBoard: (id: string) => void = () => undefined;

function BoardsPage({ initial }: { initial: string[] }) {
  const [list, setList] = React.useState(initial);
  const [openId, setOpenId] = React.useState<string | null>(null);
  setBoards = setList;
  createBoard = (id) => {
    setList((current) => [...current, id]);
    setOpenId(id);
  };
  useHashOpenRequest("#/boards", "board", OPEN_BOARD_EVENT);
  useOpenRequest(OPEN_BOARD_EVENT, (id) => {
    if (!list.includes(id)) return false;
    setOpenId(id);
  }, [list]);
  return <p data-testid="open">{openId ?? "列表"}</p>;
}

function changeHash(hash: string) {
  act(() => {
    window.history.replaceState(null, "", hash);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
}

afterEach(() => {
  window.history.replaceState(null, "", "#/");
});

describe("打开另一张画板", () => {
  it("从别的页面带着 ?board= 进来:打开那一张,地址里的参数随即清掉", () => {
    window.history.replaceState(null, "", "#/boards?board=b");
    render(<BoardsPage initial={["a", "b"]} />);
    expect(screen.getByTestId("open").textContent).toBe("b");
    expect(window.location.hash).toBe("#/boards");
  });

  it("已经开着 A 时去 B:只改 hash 的老写法也接得住,openBoard 当然也行", async () => {
    window.history.replaceState(null, "", "#/boards?board=a");
    render(<BoardsPage initial={["a", "b", "c"]} />);
    expect(screen.getByTestId("open").textContent).toBe("a");
    changeHash("#/boards?board=b");
    expect(screen.getByTestId("open").textContent).toBe("b");
    expect(window.location.hash).toBe("#/boards");
    act(() => openBoard("c"));
    expect(screen.getByTestId("open").textContent).toBe("c");
    // openBoard 写的 hash 在 hashchange 那一拍被收走(浏览器里 hashchange 也是异步的)。
    await waitFor(() => expect(window.location.hash).toBe("#/boards"));
    expect(screen.getByTestId("open").textContent).toBe("c");
  });

  it("没接住的参数不留在地址里:之后新建一张板,打开的是新建的那张", () => {
    window.history.replaceState(null, "", "#/boards");
    render(<BoardsPage initial={["a"]} />);
    // 指向一张这会儿不在列表里的板:接不住,参数也不留着。
    changeHash("#/boards?board=gone");
    expect(window.location.hash).toBe("#/boards");
    expect(screen.getByTestId("open").textContent).toBe("列表");
    act(() => createBoard("new"));
    act(() => setBoards(["a", "new", "other"]));
    expect(screen.getByTestId("open").textContent).toBe("new");
  });

  it("那一张还没加载出来时先留在信箱里,列表到了再打开", () => {
    window.history.replaceState(null, "", "#/boards?board=late");
    render(<BoardsPage initial={[]} />);
    expect(screen.getByTestId("open").textContent).toBe("列表");
    act(() => setBoards(["late"]));
    expect(screen.getByTestId("open").textContent).toBe("late");
  });
});
