import { usePreferences } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";

/** 用户协议 / 隐私政策弹窗。条款正文较长且成段,不进 messages.ts 的扁平键值表,
 *  按语言整段维护在这里 — 修订条款时改这一个文件即可。 */

type LegalSection = { heading: string; body: string };

const TERMS_ZH: LegalSection[] = [
  { heading: "1. 协议的接受", body: "创建账户或使用 Open Studio(下称「本软件」)即表示你已阅读并同意本协议。若不同意,请勿注册或使用。" },
  { heading: "2. 服务形态", body: "本软件是本地优先的视频创作工具:账户、项目、素材与时间线数据默认存储在运行后端的这台设备上,不依赖官方云端服务。" },
  { heading: "3. 账户与数据责任", body: "账户仅存在于本机(或你所连接的自建后端)。你需要自行妥善保管登录凭据,并对设备上的数据自行备份 — 本软件不提供云端备份,数据因设备损坏、误删除等造成的丢失需由你自行承担。" },
  { heading: "4. 你的内容", body: "你通过本软件导入、录制、生成或编辑的内容归你所有。你须确保对所处理的素材拥有必要权利,并对使用本软件发布到第三方平台的内容及其合法性负责。" },
  { heading: "5. 第三方服务", body: "你可以自行配置 AI 模型供应商、发布平台等第三方服务。调用这些服务时,相应数据会发送给对应服务方,并受其条款与隐私政策约束;由第三方服务产生的费用与风险由你自行承担。" },
  { heading: "6. 免责声明", body: "本软件按「现状」提供,不对可用性、准确性或特定用途适用性作任何明示或默示保证。在法律允许的最大范围内,开发者不对因使用本软件造成的任何间接损失负责。" },
  { heading: "7. 协议变更", body: "条款如有实质变更,会在软件更新说明中提示;变更后继续使用即视为接受新条款。" },
];

const TERMS_EN: LegalSection[] = [
  { heading: "1. Acceptance", body: "By creating an account or using Open Studio (the \"Software\") you confirm that you have read and agree to these terms. Do not register or use the Software if you disagree." },
  { heading: "2. Nature of the service", body: "The Software is a local-first video creation tool: accounts, projects, assets and timeline data are stored on the device running the backend. No official cloud service is involved." },
  { heading: "3. Account and data responsibility", body: "Accounts exist only on this machine (or a self-hosted backend you connect to). Keep your credentials safe and back up your data yourself — the Software provides no cloud backup, and loss caused by device failure or accidental deletion is your responsibility." },
  { heading: "4. Your content", body: "Content you import, record, generate or edit remains yours. You must hold the necessary rights to the material you process, and you are responsible for anything you publish to third-party platforms with the Software." },
  { heading: "5. Third-party services", body: "You may configure third-party services such as AI model providers and publishing platforms. Calls to those services send the relevant data to them under their own terms and privacy policies; their fees and risks are yours to bear." },
  { heading: "6. Disclaimer", body: "The Software is provided \"as is\", without warranties of availability, accuracy or fitness for a particular purpose. To the maximum extent permitted by law, the developers are not liable for indirect damages arising from its use." },
  { heading: "7. Changes", body: "Material changes to these terms will be noted in release notes; continued use after a change constitutes acceptance." },
];

const PRIVACY_ZH: LegalSection[] = [
  { heading: "1. 数据存在哪里", body: "账户信息、项目、时间线与素材文件全部保存在运行后端的设备本地(数据库与媒体目录),本软件不设官方云端,也不上传你的创作数据。" },
  { heading: "2. 凭据与密钥", body: "你配置的 AI 供应商 API Key、发布平台登录态等凭据仅保存在本地,用于你主动发起的调用;请像对待密码一样保管这台设备。" },
  { heading: "3. 什么情况下数据会离开设备", body: "仅在你主动使用相应功能时:调用 AI 生成/分析会把有关素材或文本发送给你配置的供应商;发布功能会把成片与文案发送到你连接的平台;团队模式下数据存放在你们自建的后端主机上。" },
  { heading: "4. 遥测", body: "本软件不内置使用统计、行为追踪或崩溃上报,不向开发者回传任何数据。" },
  { heading: "5. 团队工作区", body: "加入他人的工作区即表示你的相关创作数据存放在对方的后端设备上,由工作区所有者负责其存储与访问控制。" },
  { heading: "6. 数据删除", body: "删除素材、项目或工作区即从本地存储中移除对应数据;卸载并清空数据目录后不留任何副本。已发送给第三方服务的数据须按对应服务的流程处理。" },
];

const PRIVACY_EN: LegalSection[] = [
  { heading: "1. Where your data lives", body: "Account details, projects, timelines and media files are stored locally on the device running the backend (database and media directory). There is no official cloud, and your creative data is never uploaded by the Software itself." },
  { heading: "2. Credentials and keys", body: "Provider API keys and publishing-platform sessions you configure are stored locally and used only for calls you initiate; treat this device like it holds your passwords." },
  { heading: "3. When data leaves the device", body: "Only when you actively use a feature: AI generation/analysis sends the relevant assets or text to the provider you configured; publishing sends the finished video and copy to the platform you connected; in team mode the data lives on your self-hosted backend." },
  { heading: "4. Telemetry", body: "The Software ships no usage analytics, behavioral tracking or crash reporting, and sends nothing back to its developers." },
  { heading: "5. Team workspaces", body: "Joining someone's workspace means your related creative data is stored on that workspace owner's backend; the owner is responsible for its storage and access control." },
  { heading: "6. Deleting data", body: "Deleting assets, projects or workspaces removes the data from local storage; uninstalling and clearing the data directory leaves no copies. Data already sent to third-party services must be handled through those services." },
];

export type LegalDoc = "terms" | "privacy";

export function LegalDialog({ doc, onClose }: { doc: LegalDoc | null; onClose: () => void }) {
  const { locale } = usePreferences();
  const zh = locale.startsWith("zh");
  const sections = doc === "privacy" ? (zh ? PRIVACY_ZH : PRIVACY_EN) : zh ? TERMS_ZH : TERMS_EN;
  const title = doc === "privacy" ? (zh ? "隐私政策" : "Privacy Policy") : zh ? "用户协议" : "Terms of Service";
  return (
    <ModalShell open={doc !== null} onOpenChange={(next) => !next && onClose()} title={title} className="w-[460px]">
      <div className="grid max-h-[min(420px,60vh)] gap-3 overflow-y-auto pr-1 [&_h3]:m-0 [&_h3]:text-[12.5px] [&_h3]:font-semibold [&_h3]:text-foreground [&_p]:m-0 [&_p]:text-xs [&_p]:leading-[1.7] [&_p]:text-muted-foreground">
        {sections.map((section) => (
          <section className="grid gap-1" key={section.heading}>
            <h3>{section.heading}</h3>
            <p>{section.body}</p>
          </section>
        ))}
      </div>
    </ModalShell>
  );
}
