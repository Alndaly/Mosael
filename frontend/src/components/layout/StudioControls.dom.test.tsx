/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CollectionTabs } from "./StudioPage";
import { CanvasPreview } from "./CanvasPreview";
import { ActionMenu } from "@/components/app/ActionMenu";
vi.mock("@/api/client", () => ({ assetThumbnailUrl: (id: string) => `/media/${id}` }));

describe("studio browsing controls", () => {
  it("exposes the selected filter and forwards a different choice", () => {
    const change = vi.fn();
    render(<CollectionTabs label="Media types" value="all" onChange={change} items={[{ value:"all", label:"All", count:2 }, { value:"video", label:"Video", count:0 }]} />);
    expect(screen.getByRole("tab", { name:"All 2" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name:"Video 0" }));
    expect(change).toHaveBeenCalledWith("video");
  });
  //: 体检 UM-34:和插件详情、资产详情的 Radix Tabs 同一种语义 —— Tab 只停在选中的那一个,方向键 / Home / End 换。
  it("is a tablist: only the selected tab is in the Tab order, arrow keys and Home / End move and select", () => {
    function Harness() {
      const [value, setValue] = React.useState("b");
      return <CollectionTabs label="Kinds" value={value} onChange={setValue} items={[{ value: "a", label: "A" }, { value: "b", label: "B" }, { value: "c", label: "C" }]} />;
    }
    render(<Harness />);
    expect(screen.getByRole("tablist", { name: "Kinds" })).toBeInTheDocument();
    const tab = (name: string) => screen.getByRole("tab", { name });
    expect([tab("A"), tab("B"), tab("C")].map((one) => one.tabIndex)).toEqual([-1, 0, -1]);
    fireEvent.keyDown(tab("B"), { key: "ArrowRight" });
    expect(tab("C")).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(tab("C"));
    fireEvent.keyDown(tab("C"), { key: "ArrowRight" });
    expect(tab("A")).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(tab("A"), { key: "End" });
    expect(tab("C")).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(tab("C"), { key: "Home" });
    expect(tab("A")).toHaveAttribute("aria-selected", "true");
    expect(tab("A").tabIndex).toBe(0);
  });
  it("renders real canvas positions, assets and valid connections without inventing missing nodes", () => {
    const { container } = render(<CanvasPreview items={[{ id:"a", x:-200, y:-100, assetId:"owned-image" }, { id:"b", x:300, y:120, label:"Draft" }]} edges={[{source:"a", target:"b"}, {source:"missing", target:"b"}]} />);
    expect(container.querySelectorAll("path")).toHaveLength(1);
    expect(container.querySelector("image")).toHaveAttribute("href", "/media/owned-image");
    const [x, y, width, height] = container.querySelector("svg")!.getAttribute("viewBox")!.split(" ").map(Number);
    expect(x).toBeLessThan(-200); expect(y).toBeLessThan(-100);
    expect(x+width).toBeGreaterThan(500); expect(y+height).toBeGreaterThan(230);
  });
  it("falls back to the placeholder when a thumbnail cannot load, instead of a broken-image icon", () => {
    // 节点指着的素材可能还没生成完、已经被删了,或者这会儿取不到。SVG <image> 在这三种情况下
    // 都会画一个撕裂的图片图标 —— 既不说这里是什么,也不说出了什么事,只是看着像坏了。
    const { container } = render(<CanvasPreview items={[{ id:"a", x:0, y:0, assetId:"gone", label:"图片" }]} />);
    expect(container.querySelector("image")).not.toBeNull();
    fireEvent.error(container.querySelector("image")!);
    expect(container.querySelector("image")).toBeNull();
    // 退回的是"一个图片节点,暂时没有画面",所以那个节点本身还在,标签也还在。
    expect(container.querySelectorAll("rect").length).toBeGreaterThan(1);
    expect(container.querySelector("text")?.textContent).toBe("图片");
  });
  it("closes the action surface before returning to the collection", () => {
    const rename = vi.fn();
    render(<ActionMenu label="Project actions" actions={[{label:"Rename", icon:<svg />, onSelect:rename}]} />);
    fireEvent.click(screen.getByRole("button", {name:"Project actions"}));
    fireEvent.click(screen.getByRole("menuitem", {name:"Rename"}));
    expect(rename).toHaveBeenCalledOnce();
    expect(screen.queryByRole("menuitem", {name:"Rename"})).not.toBeInTheDocument();
  });
});
