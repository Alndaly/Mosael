/**
 * 把配音库里的一把嗓子交给远端引擎念之前,那一次「传上去吗」(ADR 0037)。
 *
 * 参考音频离开这台机器、进到第三方账号里,要当事人知道:传到哪(哪条连接、哪个模型)、存多久(一年不用被删)、
 * 删嗓子会不会一起删。**判据在后端**:配音、字幕配音、AI 工作台、画板念字、对话音色,哪一条把嗓子交给 CosyVoice
 * 而这个账号还没同意过,都回同一个 409(`remote_voice_consent_required`)。这里只做界面那一半:认出那个 409,弹一个
 * 确认框,同意了就带着同意去复刻(`copyVoiceToEngine`),再把刚才那一下重来一次。之后换模型、副本被删,后端按需重建,
 * 不再问。
 *
 * 确认框挂在应用级(`RemoteVoiceConsentHost`),不挂在每个入口里:入口有六七处,而画板的「念出来」连失败都是在
 * 画板那一层统一接的。入口只要把请求包进 `withRemoteVoiceConsent`。
 */
import React from "react";

import { copyVoiceToEngine, remoteConsentRequest, type RemoteConsentRequest } from "@/api/client";
import { useI18n } from "@/app/preferences";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";

/** 确认框里点了「不传」。**不是失败**:调用方据 `isConsentDeclined` 不弹报错。 */
export class RemoteConsentDeclined extends Error {
  readonly declined = true;
  constructor() {
    super("remote voice consent declined");
    this.name = "RemoteConsentDeclined";
  }
}

export function isConsentDeclined(error: unknown): boolean {
  return error instanceof RemoteConsentDeclined;
}

type Pending = { request: RemoteConsentRequest; answer: (agreed: boolean) => void };

//: 排着等人回答的确认。一次只弹一个;同时撞上两次(很少见)就排着,一个答完弹下一个。
let queue: Pending[] = [];
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

/** 弹确认框问这一次,答了才落地:同意是 true。没挂确认框的地方(不该发生)当作不同意 —— 不替人点头。 */
export function askRemoteVoiceConsent(request: RemoteConsentRequest): Promise<boolean> {
  if (listeners.size === 0) return Promise.resolve(false);
  return new Promise<boolean>((resolve) => {
    queue = [...queue, { request, answer: resolve }];
    notify();
  });
}

function answerFirst(agreed: boolean): void {
  const [first, ...rest] = queue;
  if (!first) return;
  queue = rest;
  notify();
  first.answer(agreed);
}

/**
 * 跑一次;撞上「这个账号还没同意上传这把嗓子」就问一次,同意了带着同意去复刻、再跑一次。不同意抛
 * `RemoteConsentDeclined`。复刻在后台任务里做 —— 重来的那一下(配音任务)会在后端等它建好再念,不建第二份。
 */
export async function withRemoteVoiceConsent<T>(attempt: () => Promise<T>): Promise<T> {
  try {
    return await attempt();
  } catch (error) {
    const request = remoteConsentRequest(error);
    if (!request) throw error;
    if (!(await askRemoteVoiceConsent(request))) throw new RemoteConsentDeclined();
    await copyVoiceToEngine(request.voice_id, {
      engine: request.engine,
      provider_profile_id: request.provider_profile_id,
      consent: true,
    });
    return attempt();
  }
}

function useFirstPending(): Pending | null {
  const subscribe = React.useCallback((listener: () => void) => {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);
  return React.useSyncExternalStore(subscribe, () => queue[0] ?? null, () => null);
}

/** 应用级的那一个确认框。挂一次(App 的外壳里)。 */
export function RemoteVoiceConsentHost() {
  const t = useI18n();
  const pending = useFirstPending();
  const request = pending?.request;
  const fill = (text: string) =>
    text
      .replace("{voice}", request?.voice_name ?? "")
      .replace("{connection}", request?.connection ?? "")
      .replace("{model}", request?.model ?? "");
  return (
    <AlertDialog open={pending !== null} onOpenChange={(open) => !open && answerFirst(false)}>
      <AlertDialogContent data-remote-voice-consent="">
        <AlertDialogHeader>
          <AlertDialogTitle>{fill(t("remoteVoiceConsentTitle"))}</AlertDialogTitle>
          <AlertDialogDescription asChild>
            {/* 四件事各一行:传到哪、怎么收费和存多久、删嗓子会怎样、只问这一次。 */}
            <ul className="m-0 grid list-disc gap-1.5 pl-5 text-ui-sm leading-relaxed text-muted-foreground">
              <li>{fill(t("remoteVoiceConsentUpload"))}</li>
              <li>{t("remoteVoiceConsentKeep")}</li>
              <li>{t("remoteVoiceConsentDelete")}</li>
              <li>{t("remoteVoiceConsentOnce")}</li>
            </ul>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
          {/* 用 Button 而不是 AlertDialogAction:点了就答,框随答案关掉(onOpenChange 不再把它当成「不同意」)。 */}
          <Button onClick={() => answerFirst(true)}>{t("remoteVoiceConsentConfirm")}</Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
