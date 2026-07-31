/**
 * 订阅计划的登录流程(设备码 / 浏览器授权)。
 *
 * 授权本身各家不同 —— 设备码、PKCE 回调、粘贴授权码 —— 但这些**全在 pi 的 Provider 定义里**,
 * 这里只做两件事:把 pi 要展示的东西(授权链接、设备码、进度)转成协议帧发给后端,把用户在
 * 界面上填的答案再喂回去。所以新增一家订阅供应商不需要改这个文件。
 *
 * 登录成功后凭据由 `models.login` 经 CredentialStore 落库 —— 和刷新走的是同一条写入路径
 * (BackendCredentialStore),不另开一条「登录专用」的存储链路。
 */
import type { AuthEvent, AuthPrompt } from "@earendil-works/pi-ai";
// 名字里的 "Bun" 只是上游的出处,做的事是「把各家授权流程静态注册进来」—— 任何打包场景都需要它。
// 不注册的话 pi 走动态 import 的那条路:它靠 `import.meta.url.endsWith(".js")` 判断运行形态,
// 而 CJS 产物里 import.meta 是 `{}`,于是登录一开始就炸在
//   TypeError: Cannot read properties of undefined (reading 'endsWith')
// 这类故障只在打包后出现,类型和单测都看不见(和当年 ModelsImpl is not a constructor 同源)。
import { registerBunOAuthFlows } from "@earendil-works/pi-ai/bun-oauth";

import { BackendCredentialStore } from "./credentials.js";
import { buildSubscriptionModels } from "./pi.js";
import { log, send } from "./protocol.js";

registerBunOAuthFlows();

/** 等待用户作答的 prompt:key = promptId。 */
const pending = new Map<string, (answer: string) => void>();
/** 单调递增,不用 pending.size —— 那个值在上一问答完后会退回去,连续两个同类型提问会撞 id。 */
let promptSeq = 0;

export function answerAuthPrompt(promptId: string, answer: string): boolean {
  const resolve = pending.get(promptId);
  if (!resolve) return false;
  pending.delete(promptId);
  resolve(answer);
  return true;
}

export interface AuthLoginInput {
  loginId: string;
  piProvider: string;
  profileId: string;
  apiBase: string;
  token: string;
  /** 已有凭据(重新登录时)。 */
  credential?: unknown;
}

export async function runAuthLogin(input: AuthLoginInput, signal: AbortSignal): Promise<void> {
  const { loginId } = input;
  const store = new BackendCredentialStore(
    input.apiBase,
    input.token,
    input.profileId,
    (input.credential as never) ?? undefined,
  );
  // 登录时还没有确定的模型,拿目录里第一个占位即可 —— 这一步只为拿到装好 provider 的 Models。
  const { models, provider } = await buildSubscriptionModels(input.piProvider, undefined, store);

  const interaction = {
    signal,
    prompt: (prompt: AuthPrompt): Promise<string> => {
      const promptId = `${loginId}:${(promptSeq += 1)}:${prompt.type}`;
      send({
        type: "auth_prompt",
        loginId,
        promptId,
        promptType: prompt.type,
        message: prompt.message,
        placeholder: "placeholder" in prompt ? prompt.placeholder : undefined,
        options: "options" in prompt ? prompt.options : undefined,
      });
      return new Promise<string>((resolve, reject) => {
        pending.set(promptId, resolve);
        const cancel = () => {
          pending.delete(promptId);
          reject(new Error("登录已取消"));
        };
        // 两个来源都可能先到:整体取消,或这一步被别的途径解决(如回调服务器抢先赢了)。
        signal.addEventListener("abort", cancel, { once: true });
        prompt.signal?.addEventListener("abort", cancel, { once: true });
      });
    },
    notify: (event: AuthEvent): void => {
      send({ type: "auth_event", loginId, event: event as unknown as Record<string, unknown> });
    },
  };

  await models.login(provider.id, "oauth", interaction);

  // 登录成功才知道这个账号能用哪些模型(Copilot 随订阅档位变、OpenRouter 有几百个)。
  // 顺手带回去,省得用户自己去猜一个模型名填进设置。
  const catalog = provider.getModels().map((model) => ({
    id: model.id,
    name: model.name,
    contextWindow: model.contextWindow,
    maxTokens: model.maxTokens,
    // 美元 / 百万 token,和后端计价规则的 million_* 单位同口径。
    // 只是**报价**,不是账单:实际计费始终由后端的 ProviderPricingRule 算(pi 的 Usage.cost 不用)。
    cost: model.cost,
  }));
  log(`auth login ok: ${provider.id}, ${catalog.length} models`);
  send({ type: "auth_done", loginId, models: catalog });
}
