/** @vitest-environment jsdom */
/**
 * 画板的音频卡片能用哪些嗓子。
 *
 * 这里一度只列工作区配音库里的**克隆**音色,于是一台没克隆过任何嗓子的机器打开这张卡片,
 * 看到的是「还没有可用的音色」—— 而 Edge 有十几个免费内置音色,不要密钥、不用配置。
 * 后端的 BoardSpeak 早就同时收 voice_id 和 engine/engine_voice 两条路,漏的是这一侧。
 */
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { BoardItem } from "@/api/client";
import { AudioComposer } from "./AudioComposer";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@xyflow/react", () => ({
  NodeToolbar: ({ children }: { children: React.ReactNode }) => children,
  Position: { Bottom: "bottom" },
}));
vi.mock("@tanstack/react-query", () => ({
  // 按 queryKey 分发 —— 这张卡片同时问三件事:引擎目录、克隆库、所选引擎的发音人。
  useQuery: ({ queryKey, enabled }: { queryKey: unknown[]; enabled?: boolean }) => {
    if (enabled === false) return { data: undefined };
    const [name, arg] = queryKey as [string, string];
    if (name === "tts-engines") {
      return { data: [
        { id: "clone", label: "本地音色克隆", voices: [], needs_key: false, needs_voice_id: false, note: "", ready: true },
        { id: "edge", label: "Edge 免费语音", voices: ["zh-CN-XiaoxiaoNeural", "en-US-JennyNeural"], needs_key: false, needs_voice_id: false, note: "", ready: true },
        { id: "volcano-podcast", label: "火山播客", voices: ["a", "b"], needs_key: true, needs_voice_id: false, note: "", ready: true },
      ] };
    }
    if (name === "voices") return { data: [] };           // 克隆库是空的 —— 正是那台新机器
    if (name === "tts-voices" && arg === "edge") {
      return { data: [{ value: "zh-CN-XiaoxiaoNeural", label: "晓晓(女·温暖)" }, { value: "en-US-JennyNeural", label: "Jenny" }] };
    }
    return { data: [] };
  },
}));

const item = { id: "audio", kind: "audio", form: { prompt: "念这段" } } as BoardItem;

it("克隆库空着时,别的引擎照样摆得出来 —— 那句「没有音色」只管克隆这一条", async () => {
  render(<AudioComposer item={item} busy={false} workspaceId="w" onSpeak={vi.fn()} onFormChange={vi.fn()} />);
  const engine = screen.getByRole("combobox", { name: "subtitleDubEngine" });
  expect(engine).toBeInTheDocument();
  fireEvent.click(engine);
  const options = (await screen.findAllByRole("option")).map((one) => one.textContent);
  expect(options).toContain("Edge 免费语音");
  // 播客引擎产出的是一整段双人对话,这张卡片是"念一句话" —— 形状不同,不该摆出来。
  expect(options).not.toContain("火山播客");
});

it("选了引擎音色之后,发出去的是 engine/engineVoice,不是空的 voiceId", async () => {
  const onSpeak = vi.fn();
  render(<AudioComposer item={{ ...item, form: { prompt: "念这段", engine: "edge" } } as BoardItem}
    busy={false} workspaceId="w" onSpeak={onSpeak} onFormChange={vi.fn()} />);
  await waitFor(() => expect(screen.getByRole("combobox", { name: "subtitleDubVoice" })).toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "boardSpeak" }));
  expect(onSpeak).toHaveBeenCalledWith({
    text: "念这段", voiceId: "", engine: "edge", engineVoice: "zh-CN-XiaoxiaoNeural",
  });
});

it("克隆库空着又没挑别的引擎时,提交键是禁用的 —— 而不是点了没反应", () => {
  render(<AudioComposer item={item} busy={false} workspaceId="w" onSpeak={vi.fn()} onFormChange={vi.fn()} />);
  expect(screen.getByRole("button", { name: "boardSpeak" })).toBeDisabled();
});
