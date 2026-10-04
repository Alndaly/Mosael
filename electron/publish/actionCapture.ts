// 工作流「截图」节点(以及智能体的 browser_screenshot):截自动化会话里那一页,直接存进素材库。
//
// 截图本身就是顶栏「截屏」那一份实现(pageCapture.captureContents);这里只管三件事:元素还没出现时等一会儿、
// 把截不到的原因说成人话、截好的图带着出处交给后端(执行器通道,和动作里的下载同一个入口,见 actionDownloads)。
import type { WebContents } from "electron";

import { ELEMENT_WAIT_MS, type ActionOutcome } from "./browserActions";
import { browserBackend } from "./browserBackend";
import { ElementCaptureError, captureContents, type PageCapture } from "./pageCapture";
import { PageToolError } from "./pageTarget";
import { t } from "../i18n.cjs";

export const SHOT_MODES = ["visible", "full", "element"] as const;
export type ShotMode = (typeof SHOT_MODES)[number];

const POLL_MS = 250;
const brief = (v: string, max = 80): string => (v.length <= max ? v : `${v.slice(0, max - 1)}…`);

/** 截好之后放进动作结果的那一份(工作流节点从这里取素材 id)。 */
export interface ShotResult {
  asset_id: string;
  name: string;
  width: number;
  height: number;
  truncated: boolean;
}

function shotArgs(args: Record<string, unknown>) {
  const mode = (SHOT_MODES as readonly string[]).includes(String(args.mode)) ? (String(args.mode) as ShotMode) : "visible";
  const selector = String(args.selector ?? "").trim();
  const raw = Number(args.wait_ms);
  const waitMs = Number.isFinite(raw) && raw >= 0 ? raw : ELEMENT_WAIT_MS;
  return { mode, selector, waitMs, name: String(args.name ?? "").trim().slice(0, 200) };
}

/** 截一张;截元素时它还没出现就等到 waitMs 为止。截不到的原因按界面语言说出来。 */
async function shoot(wc: WebContents, mode: ShotMode, selector: string, waitMs: number): Promise<PageCapture> {
  if (mode === "element" && !selector) throw new Error(t("browserErr_shotNeedsSelector"));
  const deadline = Date.now() + Math.max(0, waitMs);
  for (;;) {
    try {
      return await captureContents(wc, mode, { selector });
    } catch (error) {
      if (error instanceof ElementCaptureError && error.reason === "missing") {
        if (Date.now() < deadline) {
          await new Promise((resolve) => setTimeout(resolve, Math.min(POLL_MS, Math.max(0, deadline - Date.now()))));
          continue;
        }
        throw new Error(
          t("browserErr_elementMissing", {
            target: brief(selector),
            seconds: (Math.max(0, waitMs) / 1000).toFixed(1),
            url: brief(wc.getURL(), 120),
          }),
        );
      }
      if (error instanceof ElementCaptureError) throw new Error(t("browserErr_shotElementEmpty", { target: brief(selector) }));
      if (error instanceof PageToolError) {
        throw new Error(t(error.code === "full_page_unavailable" ? "browserErr_shotFullUnavailable" : "browserErr_shotFailed"));
      }
      throw error;
    }
  }
}

export async function captureForAction(opts: {
  actionId: string;
  webContents: WebContents | null;
  args: Record<string, unknown>;
}): Promise<ActionOutcome> {
  const wc = opts.webContents;
  if (!wc || wc.isDestroyed()) throw new Error(t("browserErr_shotFailed"));
  const { mode, selector, waitMs, name } = shotArgs(opts.args);
  const shot = await shoot(wc, mode, selector, waitMs);
  const asset = await browserBackend.uploadArtifact(
    opts.actionId,
    "screenshot",
    { body: new Blob([shot.bytes], { type: "image/png" }), filename: "screenshot.png" },
    {
      capture: `screenshot_${mode}`,
      filename: "screenshot.png",
      name,
      page_url: shot.page.url,
      page_title: shot.page.title,
      captured_at: shot.capturedAt,
    },
  );
  const value: ShotResult = {
    asset_id: asset.asset_id,
    name: asset.name,
    width: shot.width,
    height: shot.height,
    truncated: shot.truncated,
  };
  return { value, lastUrl: wc.getURL() };
}
