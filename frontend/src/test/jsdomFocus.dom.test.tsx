/** @vitest-environment jsdom */
/**
 * setup.ts 里那段 window blur 过滤的两面:该拦的拦住,不该拦的放过。
 *
 * 它补的是 jsdom 30.1 的一个回归(焦点元素被移出 DOM 后,下一次 focus() 会往 window 派发
 * blur)。去掉那段过滤再跑这里,第一条会挂 —— 那时再看 jsdom 修没修。
 */
import { fireEvent, render, screen } from "@testing-library/react";
import * as ContextMenu from "@radix-ui/react-context-menu";
import { expect, it, vi } from "vitest";

it("焦点元素被卸载后,下一个菜单打开时不会被一个假的 window blur 关掉", () => {
  const gone = document.createElement("button");
  document.body.append(gone);
  gone.focus();
  gone.remove(); // 这一步之后,jsdom 30.1 把「上一个焦点」记成 document

  render(
    <ContextMenu.Root>
      <ContextMenu.Trigger>区域</ContextMenu.Trigger>
      <ContextMenu.Portal>
        <ContextMenu.Content>
          <ContextMenu.Item>创建副本</ContextMenu.Item>
        </ContextMenu.Content>
      </ContextMenu.Portal>
    </ContextMenu.Root>,
  );
  fireEvent.contextMenu(screen.getByText("区域"), { clientX: 10, clientY: 10 });
  expect(screen.getByRole("menuitem", { name: "创建副本" })).toBeInTheDocument();
});

it("真正的窗口失焦照常送达", () => {
  const heard = vi.fn();
  window.addEventListener("blur", heard);
  window.dispatchEvent(new FocusEvent("blur", { relatedTarget: null }));
  window.removeEventListener("blur", heard);
  expect(heard).toHaveBeenCalledOnce();
});
