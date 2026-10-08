/**
 * 设置**按「我要改什么」搜得到**:设置页左边的搜索框和 ⌘K 都读这一份。
 *
 * 此前搜索只比 15 个分区名 —— 搜「语言」「密码」「主题」「默认模型」「代理」「镜像」「pip」全是「没有找到」,
 * 语言和主题在「外观」里,密码在「账户」里,代理、镜像、邀请码挪去了管理页(体检 UM-15)。
 *
 * - `SETTINGS_SEARCH`:每个分区一条(id、名字和它里面那些行的标签)。分区本身(渲染什么、图标)仍在
 *   settingsSections 那一份声明里;两边的 id 和名字由 settingsSections.test 钉住对得上。单独成这个轻文件,
 *   是为了 ⌘K 能用它而不把整个设置页拉进首屏。
 * - `ADMIN_SETTINGS`:只有部署管理员改得了的那些,在管理页的哪个 tab。搜到它们时,管理员点了直达;
 *   别人看到一句「这一项由部署管理员在『管理』里改」,而不是「没有找到」。
 *
 * `keywords` 是分区里那些行的标签(文案 key,跟着界面语言),搜到时在分区名后面写出是哪一行;`terms` 是只为搜索写的
 * 说法(「镜像」「HuggingFace」「Kimi」),只用来对,不显示。
 */
import type { MessageKey } from "@/app/messages";
import type { AdminTab } from "@/lib/adminTabs";

type Searchable = { label: MessageKey; keywords: readonly MessageKey[]; terms?: readonly MessageKey[] };
export type SettingsSearchEntry = Searchable & { id: string };
export type AdminSetting = Searchable & { id: string; tab: AdminTab };

export const SETTINGS_SEARCH: readonly SettingsSearchEntry[] = [
  { id: "account", label: "settingsAccount", keywords: ["settingsUsername", "displayName", "signature", "settingsPassword", "avatarChange", "signOut"] },
  { id: "team", label: "teamTitle", keywords: ["teamInvite", "teamRole", "teamActivity", "renameWorkspace", "deleteWorkspace", "teamLeave"] },
  { id: "appearance", label: "settingsAppearance", keywords: ["settingsTheme", "settingsLanguage", "settingsFont", "appearanceBgTitle", "customCssTitle"], terms: ["settingsSearchTermsAppearance"] },
  { id: "dubbing", label: "settingsDubbingTitle", keywords: ["builtinTtsTitle", "voiceLibrary"] },
  { id: "provider-chat", label: "providerChatTitle", keywords: ["providerDefaultsTitle"], terms: ["settingsSearchTermsProviders"] },
  { id: "provider-image", label: "providerImageTitle", keywords: ["providerDefaultsTitle"], terms: ["settingsSearchTermsProviders"] },
  { id: "provider-video", label: "providerVideoTitle", keywords: ["providerDefaultsTitle"], terms: ["settingsSearchTermsProviders"] },
  { id: "provider-audio", label: "providerAudioTitle", keywords: ["providerTtsTitle", "providerPodcastTitle", "providerMusicTitle", "providerDefaultsTitle"], terms: ["settingsSearchTermsProviders"] },
  { id: "agent-voice", label: "agentVoiceTitle", keywords: [] },
  { id: "agent-memory", label: "agentMemoryTitle", keywords: [] },
  { id: "agent-skills", label: "agentSkillsTitle", keywords: [] },
  { id: "agent-autopilot", label: "autopilotTitle", keywords: [] },
  { id: "feishu", label: "feishuTitle", keywords: [] },
  { id: "capabilities", label: "capabilityProvidersTitle", keywords: [], terms: ["settingsSearchTermsCapabilities"] },
  { id: "backend", label: "settingsBackend", keywords: ["settingsEndpoint", "serverSwitchLabel", "settingsStartup", "settingsVersion", "updateCheck"] },
];

export const ADMIN_SETTINGS: readonly AdminSetting[] = [
  { id: "invites", label: "deployInvitesTitle", tab: "members", keywords: [], terms: ["settingsSearchTermsInvites"] },
  { id: "pricing", label: "pricingRulesTitle", tab: "pricing", keywords: [] },
  { id: "install-source", label: "installSourceTitle", tab: "engines", keywords: [], terms: ["settingsSearchTermsInstallSource"] },
  { id: "model-source", label: "voiceCloneSource", tab: "engines", keywords: [], terms: ["settingsSearchTermsModelSource"] },
  { id: "asr", label: "asrModelsTitle", tab: "engines", keywords: [] },
  { id: "voice-clone", label: "voiceCloneTitle", tab: "engines", keywords: [] },
  { id: "separation", label: "separationTitle", tab: "engines", keywords: [] },
  { id: "denoise", label: "denoiseEnginesTitle", tab: "engines", keywords: [] },
  { id: "registration", label: "deployRegistrationTitle", tab: "deployment", keywords: [] },
  { id: "shared-folders", label: "deploySharedFoldersTitle", tab: "deployment", keywords: [] },
  { id: "outbound", label: "deployOutboundTitle", tab: "deployment", keywords: [] },
  { id: "proxy", label: "proxyTitle", tab: "deployment", keywords: [], terms: ["settingsSearchTermsProxy"] },
  { id: "ai-runtime", label: "aiRuntimeTitle", tab: "deployment", keywords: [] },
  { id: "data", label: "dataDiagnosticsTitle", tab: "deployment", keywords: [] },
];

/** 一条设置怎么被搜到的:名字本身对上,还是里面的哪一行(`hit`,给人看「· 主题」)。 */
export type SettingsHit<T> = { entry: T; hit: MessageKey | null };

/** 名字或任一关键字含有这串字(不分大小写)。空串什么都对得上。 */
export function matchSettings<T extends Searchable>(
  entries: readonly T[],
  query: string,
  t: (key: MessageKey) => string,
): SettingsHit<T>[] {
  const needle = query.trim().toLocaleLowerCase();
  const has = (key: MessageKey) => t(key).toLocaleLowerCase().includes(needle);
  const found: SettingsHit<T>[] = [];
  for (const entry of entries) {
    if (!needle || has(entry.label)) {
      found.push({ entry, hit: null });
      continue;
    }
    const hit = entry.keywords.find(has);
    if (hit) found.push({ entry, hit });
    else if ((entry.terms ?? []).some(has)) found.push({ entry, hit: null });
  }
  return found;
}
