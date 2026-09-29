/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 装包的镜像:下拉选预设(名字和地址由后端给),末尾「自定义地址…」长出地址框、离开时才存。
 * 用户截图:Manim 的 PyPI 镜像、Remotion 的 npm 镜像都是一个自由文本框。
 */

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
//: 下拉在 jsdom 里点不开:平铺成按钮,选中的那个带 data-selected。
vi.mock("@/components/ui/searchable-select", () => ({
  SearchableSelect: ({ options, onValueChange, value }: {
    options: Array<{ value: string; label: string }>; onValueChange: (v: string) => void; value: string;
  }) => (
    <div data-picker="">
      {options.map((one) => (
        <button key={one.value} type="button" data-selected={one.value === value || undefined} onClick={() => onValueChange(one.value)}>
          {one.label}
        </button>
      ))}
    </div>
  ),
}));

import { PackageSourcePicker } from "./PackageSourcePicker";

const PRESETS = [
  { value: "pypi", label: "官方 PyPI", url: "" },
  { value: "tsinghua", label: "清华大学", url: "https://pypi.tuna.tsinghua.edu.cn/simple" },
];

const selected = () => document.querySelector("[data-selected]")?.textContent;

describe("插件连接上的镜像", () => {
  let onChange: ReturnType<typeof vi.fn<(value: string) => void>>;
  beforeEach(() => {
    onChange = vi.fn<(value: string) => void>();
  });

  it("没覆盖就是「跟随 Mosael(…)」,选一个预设存它的 key,选回跟随存空串", () => {
    const { rerender } = render(
      <PackageSourcePicker ariaLabel="PyPI 镜像" presets={PRESETS} value="" followLabel="清华大学" onChange={onChange} />,
    );
    expect(selected()).toBe("pkgSourceFollow");
    fireEvent.click(screen.getByRole("button", { name: "官方 PyPI" }));
    expect(onChange).toHaveBeenLastCalledWith("pypi");
    rerender(<PackageSourcePicker ariaLabel="PyPI 镜像" presets={PRESETS} value="pypi" followLabel="清华大学" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "pkgSourceFollow" }));
    expect(onChange).toHaveBeenLastCalledWith("");
  });

  it("自定义地址:先长出框,填完离开才存;存下来的地址不在预设里,下拉照样显示「自定义」和那个地址", () => {
    const { rerender } = render(
      <PackageSourcePicker ariaLabel="PyPI 镜像" presets={PRESETS} value="" followLabel="清华大学" onChange={onChange} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "pkgSourceCustom" }));
    const box = screen.getByLabelText("PyPI 镜像") as HTMLInputElement;
    fireEvent.change(box, { target: { value: "https://pypi.corp.example/simple" } });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.blur(box);
    expect(onChange).toHaveBeenCalledWith("https://pypi.corp.example/simple");
    rerender(<PackageSourcePicker ariaLabel="PyPI 镜像" presets={PRESETS} value="https://pypi.corp.example/simple"
      followLabel="清华大学" onChange={onChange} />);
    expect(selected()).toBe("pkgSourceCustom");
    expect((screen.getByLabelText("PyPI 镜像") as HTMLInputElement).value).toBe("https://pypi.corp.example/simple");
  });
});

describe("管理页的下载源", () => {
  it("没有「跟随」这一项;空值就是官方源,选官方存空串", () => {
    const onChange = vi.fn<(value: string) => void>();
    render(<PackageSourcePicker ariaLabel="pip" presets={PRESETS} value="tsinghua" onChange={onChange} />);
    expect(screen.queryByRole("button", { name: "pkgSourceFollow" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "官方 PyPI" }));
    expect(onChange).toHaveBeenCalledWith("");
  });
});
