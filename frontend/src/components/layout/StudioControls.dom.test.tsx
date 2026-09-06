/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CollectionTabs } from "./StudioPage";
import { CanvasPreview } from "./CanvasPreview";
import { ActionMenu } from "./ActionMenu";
vi.mock("@/api/client", () => ({ assetThumbnailUrl: (id: string) => `/media/${id}` }));

describe("studio browsing controls", () => {
  it("exposes the selected filter and forwards a different choice", () => {
    const change = vi.fn();
    render(<CollectionTabs label="Media types" value="all" onChange={change} items={[{ value:"all", label:"All", count:2 }, { value:"video", label:"Video", count:0 }]} />);
    expect(screen.getByRole("button", { name:"All 2" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name:"Video 0" }));
    expect(change).toHaveBeenCalledWith("video");
  });
  it("renders real canvas positions, assets and valid connections without inventing missing nodes", () => {
    const { container } = render(<CanvasPreview items={[{ id:"a", x:-200, y:-100, assetId:"owned-image" }, { id:"b", x:300, y:120, label:"Draft" }]} edges={[{source:"a", target:"b"}, {source:"missing", target:"b"}]} />);
    expect(container.querySelectorAll("path")).toHaveLength(1);
    expect(container.querySelector("image")).toHaveAttribute("href", "/media/owned-image");
    const [x, y, width, height] = container.querySelector("svg")!.getAttribute("viewBox")!.split(" ").map(Number);
    expect(x).toBeLessThan(-200); expect(y).toBeLessThan(-100);
    expect(x+width).toBeGreaterThan(500); expect(y+height).toBeGreaterThan(230);
  });
  it("closes the action surface before returning to the collection", () => {
    const rename = vi.fn();
    render(<ActionMenu label="Project actions" actions={[{label:"Rename", onSelect:rename}]} />);
    fireEvent.click(screen.getByRole("button", {name:"Project actions"}));
    fireEvent.click(screen.getByRole("button", {name:"Rename"}));
    expect(rename).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", {name:"Rename"})).not.toBeInTheDocument();
  });
});
