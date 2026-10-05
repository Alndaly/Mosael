/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

/**
 * 克隆音色复刻到百炼 CosyVoice(ADR 0037)的界面那一半:
 *
 * - CosyVoice 的音色下拉在系统音色之外多一组「我的克隆音色」,点了它请求带 `voice_id`、不带 `engine_voice`;
 * - 后端说「这个账号还没同意上传这把嗓子」(409 `remote_voice_consent_required`)时弹确认框,同意了带着同意去复刻、
 *   再把刚才那一下重来一次;不同意就什么都不传、也不报错。
 *
 * 判据在后端(它不同意就不排任务),这里钉的是界面认得出那个 409、问的是那一句、同意之后真的重来了。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), message: vi.fn(), warning: vi.fn() } }));

import { toast } from "sonner";
import { VoicePanel } from "@/features/editor/VoicePanel";
import { RemoteVoiceConsentHost } from "@/features/voice/remoteVoiceConsent";
import { useEditorStore } from "@/features/editor/editorStore";

const COSY = "builtin:alibaba-cosyvoice";

beforeAll(() => {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    scrollIntoView: () => {},
  });
});

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.clearAllMocks();
});

const sequence = {
  id: "s1",
  workspace_id: "w1",
  revision: 1,
  tracks: [{
    id: "t1", kind: "subtitle", name: "S1", position: 0,
    clips: [{ id: "c0", track_id: "t1", asset_id: null, asset_kind: "", timeline_start: 0, src_in: 0, src_out: 3, speed: 1, text_override: "你好" }],
  }],
} as never;

const consentRequired = {
  detail: {
    code: "remote_voice_consent_required",
    message: "要先复刻",
    voice_id: "v1",
    voice_name: "我的嗓子",
    engine: COSY,
    provider_profile_id: "p1",
    connection: "我的百炼",
    model: "cosyvoice-v3-flash",
  },
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

/** 一台配好了百炼的机器:配音库里有一把声明过授权的嗓子;这个账号还没同意过把它传上去。 */
function serve() {
  const dubRequests: Array<Record<string, unknown>> = [];
  const copyRequests: Array<{ url: string; body: Record<string, unknown> }> = [];
  let consented = false;
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/dub-subtitles")) {
      dubRequests.push(JSON.parse(String(init?.body)));
      return consented ? json({ id: "job-dub", status: "queued" }) : json(consentRequired, 409);
    }
    if (url.includes("/remote-copies")) {
      copyRequests.push({ url, body: JSON.parse(String(init?.body)) });
      consented = true;
      return json({ id: "job-copy", status: "queued" });
    }
    const body = url.includes("/api/auth/me")
      ? { is_deployment_admin: true }
      : url.includes("/tts/f5-models")
        ? []
        : url.includes("/api/tts/models")
          ? [{ id: "f5-tts", label: "F5-TTS", status: "installed", runtime_ready: true, runtime_checked: true, supports_speed: true }]
          : url.includes("/api/settings/tts")
            ? { engine: "f5-tts", python_path: "", source: "modelscope" }
            : url.includes("/tts/engines")
              ? [
                  { id: "builtin:clone", label: "本地音色克隆", needs_key: false, needs_voice_id: false, voices: [], ready: true },
                  { id: COSY, label: "百炼 CosyVoice", needs_key: true, needs_voice_id: true, voices: [], ready: true,
                    supports_speed: true, clones_voices: true },
                ]
              : url.includes("/tts/voices")
                ? url.includes("workspace_id=w1")
                  ? [
                      { value: "longxiaochun_v3", label: "longxiaochun_v3" },
                      { value: "longwan_v3", label: "longwan_v3" },
                      { value: "v1", label: "我的嗓子", cloned: true },
                    ]
                  : [{ value: "longxiaochun_v3", label: "longxiaochun_v3" }]
                : url.includes("/api/voices")
                  ? [{ id: "v1", name: "我的嗓子", reference_text: "", source: "upload", created_at: "2026-10-05T00:00:00Z",
                       has_reference: true, consent_kind: "self", remote_copies: [] }]
                  : url.includes("/api/jobs/")
                    ? { id: "job-dub", status: "running" }
                    : url.includes("/api/assets?")
                      ? { items: [], next_cursor: null, total: 0 }
                      : [];
    return json(body);
  }) as never;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <VoicePanel workspace={{ id: "w1", name: "W" } as never} project={{ id: "p1" } as never} sequence={sequence} />
      <RemoteVoiceConsentHost />
    </QueryClientProvider>,
  );
  return { dubRequests, copyRequests };
}

async function pickClonedVoiceOnCosyVoice(user: ReturnType<typeof userEvent.setup>) {
  useEditorStore.getState().selectClip(null);
  await user.click(await screen.findByRole("combobox", { name: "voiceEngine" }));
  await user.click(await screen.findByRole("option", { name: "百炼 CosyVoice" }));
  const picker = await screen.findByRole("combobox", { name: "voiceEngineVoice" });
  await waitFor(() => expect(picker).toHaveTextContent("longxiaochun_v3"));
  await user.click(picker);
  //: 两组:系统音色在前,配音库里的嗓子在后,各有标题。
  const listbox = await screen.findByRole("listbox");
  expect(within(listbox).getByText("voiceGroupStock")).toBeInTheDocument();
  expect(within(listbox).getByText("voiceGroupCloned")).toBeInTheDocument();
  const options = within(listbox).getAllByRole("option").map((one) => one.textContent);
  expect(options).toEqual(["longxiaochun_v3", "longwan_v3", "我的嗓子"]);
  await user.click(within(listbox).getByRole("option", { name: "我的嗓子" }));
  expect(await screen.findByText("voiceClonedOnEngineHint")).toBeInTheDocument();
}

describe("CosyVoice 念配音库里的嗓子", () => {
  it("默认落在系统音色上,不替人点克隆音色 —— 那一下要把参考音频传出去", async () => {
    const user = userEvent.setup();
    const { dubRequests } = serve();
    await user.click(await screen.findByRole("combobox", { name: "voiceEngine" }));
    await user.click(await screen.findByRole("option", { name: "百炼 CosyVoice" }));
    await waitFor(() => expect(screen.getByRole("combobox", { name: "voiceEngineVoice" })).toHaveTextContent("longxiaochun_v3"));
    expect(screen.queryByText("voiceClonedOnEngineHint")).toBeNull();
    expect(dubRequests).toEqual([]);
  });

  it("点了克隆音色:后端要同意时弹确认框,同意了带着同意去复刻、再配一次,请求带 voice_id 不带 engine_voice", async () => {
    const user = userEvent.setup();
    const { dubRequests, copyRequests } = serve();
    await pickClonedVoiceOnCosyVoice(user);

    const apply = await screen.findByRole("button", { name: /subtitleDubApply/ });
    await waitFor(() => expect(apply).toBeEnabled());
    await user.click(apply);

    const dialog = await screen.findByRole("alertdialog");
    //: 说清楚传到哪、存多久、删嗓子会怎样、只问这一次。
    for (const line of ["remoteVoiceConsentUpload", "remoteVoiceConsentKeep", "remoteVoiceConsentDelete", "remoteVoiceConsentOnce"]) {
      expect(within(dialog).getByText(line)).toBeInTheDocument();
    }
    expect(copyRequests).toEqual([]);
    await user.click(within(dialog).getByRole("button", { name: "remoteVoiceConsentConfirm" }));

    await waitFor(() => expect(dubRequests).toHaveLength(2));
    expect(copyRequests).toEqual([
      { url: expect.stringContaining("/api/voices/v1/remote-copies"), body: { engine: COSY, provider_profile_id: "p1", consent: true } },
    ]);
    expect(dubRequests[1]).toMatchObject({ engine: COSY, voice_id: "v1" });
    expect(dubRequests[1]).not.toHaveProperty("engine_voice");
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("不同意:不传、不复刻、不报错", async () => {
    const user = userEvent.setup();
    const { dubRequests, copyRequests } = serve();
    await pickClonedVoiceOnCosyVoice(user);
    const apply = await screen.findByRole("button", { name: /subtitleDubApply/ });
    await waitFor(() => expect(apply).toBeEnabled());
    await user.click(apply);

    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "cancel" }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(copyRequests).toEqual([]);
    expect(dubRequests).toHaveLength(1);
    expect(toast.error).not.toHaveBeenCalled();
  });
});
