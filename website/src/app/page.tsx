import { Badge } from "@/components/ui/badge";

/**
 * 排版基座的验证页 —— 不是最终首页,是把 globals.css 里那几条中文排版规则**显示出来**。
 * 规则写在 CSS 里看不出好坏,得有真实的长段落、中英混排、标点连用才知道调对没有。
 *
 * **中文段落一律写成一行的 {"…"} 字符串**,不要在源码里折行。JSX 会把换行 + 缩进折成
 * 一个空格 —— 英文里正好是词间距,中文里就是凭空多出来的空格,而且只在浏览器里看得见。
 * 这一页最初就踩了两处。内容迁移时每一段都适用。
 */
export default function Home() {
  return (
    <main className="prose-cn mx-auto min-h-svh px-6 py-24 font-serif text-foreground sm:px-8">
      <Badge variant="secondary" className="mb-8 font-sans text-xs tracking-wide">
        排版基座
      </Badge>

      <h1 className="mb-6 text-4xl font-semibold sm:text-5xl">让灵感落进时间线</h1>

      <p className="mb-8 text-lg text-muted-foreground">
        剪辑、字幕、配音、发布 —— 一个本地工作台完成全部创作。
      </p>

      <h2 className="mb-4 mt-14 text-2xl font-semibold">为什么是本地优先</h2>

      <p className="mb-5">
        {"素材不出本机,模型可以自己挑。Open Studio 把 FFmpeg、Whisper、以及你自己配置的大模型接到同一条时间线上:剪辑的每一步都可撤销,AI 的每一次改动都要你点头。它不替你做决定,只是把「想到」和「做到」之间那段路铺平。"}
      </p>

      <p className="mb-5">
        {"工作流把重复的事固定下来 —— 检索风格指南、起标题、拼装文案、合成配音、发布到多个平台。画布上能做的事,对话里的智能体也都能做,这一点由测试钉着,不是一句宣传。"}
      </p>

      <h3 className="mb-3 mt-10 text-xl font-semibold">排版检查项</h3>

      <ul className="mb-5 list-disc space-y-2 pl-5">
        <li>行距:中文正文 1.8,标题收到 1.3 —— 汉字没有 x-height 带来的留白,得靠行距补。</li>
        <li>标点:「这样,连续的标点。」不该在中间挤出一个洞。</li>
        <li>中英混排:GitHub 上的 Open Studio 与 FFmpeg 8.1,字母和汉字之间应有约 1/4 字宽。</li>
        <li>折行:标题两行时长度均衡,段落行末不留孤字。</li>
      </ul>

      <p className="text-sm text-muted-foreground">
        {"这一页会被真正的首页替换。留着是为了改排版时有地方对照。"}
      </p>
    </main>
  );
}
