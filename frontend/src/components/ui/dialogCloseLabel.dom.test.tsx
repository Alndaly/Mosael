/** @vitest-environment jsdom */
/** 弹窗、侧板右上角那颗 × 给读屏的名字走界面语言;此前写死成英文的 "Close"。 */
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { messages } from "@/app/messages";
import { PreferencesContext, type PreferencesContextValue } from "@/app/preferencesContext";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "./dialog";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "./sheet";

afterEach(cleanup);

const english = { locale: "en-US", t: (key: keyof (typeof messages)["en-US"]) => messages["en-US"][key] } as unknown as PreferencesContextValue;

function dialog() {
  return (
    <Dialog open>
      <DialogContent>
        <DialogTitle>标题</DialogTitle>
        <DialogDescription>说明</DialogDescription>
      </DialogContent>
    </Dialog>
  );
}

it("中文界面(没挂偏好时按默认的中文):× 叫「关闭」,不是 Close", () => {
  render(dialog());
  expect(screen.getByRole("button", { name: messages["zh-CN"].close })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Close" })).toBeNull();
});

it("英文界面:× 叫 Close(跟着界面语言走,不是写死的)", () => {
  render(<PreferencesContext.Provider value={english}>{dialog()}</PreferencesContext.Provider>);
  expect(screen.getByRole("button", { name: messages["en-US"].close })).toBeTruthy();
});

it("侧板同一个说法", () => {
  render(
    <Sheet open>
      <SheetContent>
        <SheetTitle>标题</SheetTitle>
        <SheetDescription>说明</SheetDescription>
      </SheetContent>
    </Sheet>,
  );
  expect(screen.getByRole("button", { name: messages["zh-CN"].close })).toBeTruthy();
});
