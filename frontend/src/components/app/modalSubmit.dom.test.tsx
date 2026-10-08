/** @vitest-environment jsdom */

/**
 * 填值弹窗(ModalShell 给了 onSubmit):正文是一张真的表单,在任一格里按回车就是提交;底部的 ModalSubmit 点了同样提交;
 * 底部的「取消」这种普通按钮不提交。此前浏览器池「新建档案」这类弹窗按回车什么也不做。
 */
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { ModalShell, ModalSubmit } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

vi.mock("@/app/preferences", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useI18n: () => (key: string) => key,
}));

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(cleanup);

function Form({ onSubmit, onCancel }: { onSubmit: () => void; onCancel: () => void }) {
  return (
    <ModalShell
      open
      onOpenChange={() => undefined}
      title="新建档案"
      onSubmit={onSubmit}
      footer={
        <>
          <Button variant="outline" onClick={onCancel}>取消</Button>
          <ModalSubmit>新建</ModalSubmit>
        </>
      }
    >
      <div className="grid gap-2">
        <Input aria-label="名字" />
        <Input aria-label="代理" />
      </div>
    </ModalShell>
  );
}

describe("填值弹窗", () => {
  //: 按回车时浏览器找的是这张表单的「默认按钮」—— 表单关联的第一颗 submit,包括用 form= 从表单外面指过来的那颗。
  //: jsdom / user-event 只在表单里面找,所以这里钉的是这层关联;真界面里按回车提交走过一遍(浏览器池「新建档案」、新建连接)。
  it("底部的提交键和正文那张表单连在一起(按回车时浏览器找的默认按钮就是它)", () => {
    render(<Form onSubmit={vi.fn()} onCancel={vi.fn()} />);
    const submit = screen.getByRole("button", { name: "新建" }) as HTMLButtonElement;
    const form = screen.getByLabelText("名字").closest("form");
    expect(form).not.toBeNull();
    expect(submit.type).toBe("submit");
    expect(submit.form).toBe(form);
  });

  it("只有一格的时候,user-event 也认得回车提交", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(
      <ModalShell open onOpenChange={() => undefined} title="改代理" onSubmit={onSubmit} footer={<ModalSubmit>保存</ModalSubmit>}>
        <Input aria-label="代理" />
      </ModalShell>,
    );
    await user.type(screen.getByLabelText("代理"), "socks5://h:1{Enter}");
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("点底部的提交键提交;点「取消」不提交", async () => {
    const onSubmit = vi.fn();
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(<Form onSubmit={onSubmit} onCancel={onCancel} />);
    await user.click(screen.getByRole("button", { name: "取消" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "新建" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});
