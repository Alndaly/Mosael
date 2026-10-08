import * as React from "react";
import { Bot, ChevronDown, Download, Ellipsis, Film, Image as ImageIcon, Layers, Mic, MousePointer2, Plus, Search, Trash2, Upload, Volume2, X } from "lucide-react";

import { CanvasInputModeMenu } from "@/components/app/CanvasInputModeMenu";
import type { CanvasInputMode } from "@/components/app/canvasInputMode";
import { CollectionTabs, PageHeading } from "@/components/layout/StudioPage";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Chip } from "@/components/ui/chip";
import { FIELD_TRIGGER_CHEVRON, fieldTriggerClass } from "@/components/ui/field-trigger";
import { FLOATING_SURFACE, MENU_WIDTH } from "@/components/ui/floating";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { MenuItem } from "@/components/ui/menu";
import { OptionPicker } from "@/components/ui/option-picker";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { RadioGroup } from "@/components/ui/radio-group";
import { Segmented } from "@/components/ui/segmented";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { TimePicker } from "@/components/ui/time-picker";
import { Truncate } from "@/components/ui/truncate";
import { cn } from "@/lib/utils";

/**
 * 设计语言的**规格样张**(docs/DESIGN_LANGUAGE.md):每一档、每一类控件、每一种状态;顶上切浅色 / 深色。只在开发构建里有
 * (`#/dev/design`,见 app/App.tsx),不进发行包。
 *
 * - 「悬停」「键盘聚焦」两列在截图里是用开发者工具强制出来的(`data-sheet-state`);在页面上自己移上去、按 Tab 看。
 * - 这里摆的都是真组件:改了基础组件或 token,这一页跟着变 —— 它是规格落地的样子,不是一张画出来的图。
 * - 文字写死中文:这一页给维护者和写界面的人看,不给用户看(design/uiTextIsTranslated.test.ts 的 EXEMPT 里记着)。
 */
export function DesignSheet() {
  //: 深浅色切的是根上的 .dark,和应用本身同一个开关 —— 不在页面里套一层 .dark:那样一部分令牌(`--control: var(--panel)`
  //: 这种在 :root 上就算好了值的)会带着浅色的值继承下来,样张就不是应用里真实的样子。离开这一页时放回原样。
  const [theme, setTheme] = React.useState<"light" | "dark">(() => (document.documentElement.classList.contains("dark") ? "dark" : "light"));
  React.useEffect(() => {
    const root = document.documentElement;
    const wasDark = root.classList.contains("dark");
    return () => {
      root.classList.toggle("dark", wasDark);
    };
  }, []);
  React.useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);
  return (
    <div className="h-screen overflow-auto bg-panel-subtle text-foreground" data-design-sheet="">
      <div className="mx-auto grid max-w-[1600px] gap-10 px-8 py-8">
        <header className="grid gap-2">
          <h1 className="m-0 text-ui-title font-semibold tracking-tight">设计语言 · 规格样张</h1>
          <p className="m-0 max-w-4xl text-ui-sm leading-relaxed text-muted-foreground">
            规则见 docs/DESIGN_LANGUAGE.md。这里摆的都是真组件;「悬停」「键盘聚焦」两列在截图里是强制出来的。
          </p>
          <Segmented
            aria-label="主题"
            className="justify-self-start"
            value={theme}
            onValueChange={setTheme}
            options={[
              { value: "light", label: "浅色" },
              { value: "dark", label: "深色" },
            ]}
          />
        </header>
        <Section id="scale" title="一、刻度:同档同高" note="每一行是一档:按钮、描边按钮、输入框、下拉、分段、图标按钮并排,一样高。方钮和同档文字控件一样高(md 40)。">
          <ScaleRows />
        </Section>
        <Section id="buttons" title="二、按钮:变体 × 状态" note="一屏只有一个主(实心)。危险只用在确认弹窗里那一颗上。行内动作挨着值,不写 size。">
          <ButtonStates />
        </Section>
        <Section id="button-sizes" title="三、按钮:档位 × 图标" note="按钮里的图标大小由档位定,在图标上写 size 不生效:xs 文字按钮 14,sm、md 16;只有图标的按钮在哪一档都是 16。">
          <ButtonSizes />
        </Section>
        <Section id="fields" title="四、字段:一种外观" note="输入框、下拉、可搜索下拉、选项选择器、时间、数字、日期、文本域同一种描边、底色、圆角、留白、字号。出错(aria-invalid)时描边和聚焦环变红,下面一行 12px 红字。">
          <FieldStates />
        </Section>
        <Section id="choices" title="五、选择类控件" note="分段三档(md 40 / sm 32 / xs 28)、胶囊筛选 28、页签、开关、复选、单选各一种样子。">
          <Choices />
        </Section>
        <Section id="scenes" title="六、场景 → 档位" note="先认容器再认档:填值的地方 md,画布工具条和窗口顶栏 sm,密集工具条 xs,挨着值的是行内。">
          <SceneSamples />
        </Section>
        <Section id="motion" title="七、动效" note="时长四档、缓动两种;减少动态时循环的只走一遍、停在原样,转圈放慢不停。把指针移到色块上看。">
          <MotionSamples />
        </Section>
      </div>
    </div>
  );
}

function Section({ id, title, note, children }: { id: string; title: string; note: string; children: React.ReactNode }) {
  return (
    <section id={id} data-sheet-section={id} className="grid gap-3">
      <div className="grid gap-1">
        <h2 className="m-0 text-ui-lg font-semibold">{title}</h2>
        <p className="m-0 max-w-5xl text-ui-sm leading-relaxed text-muted-foreground">{note}</p>
      </div>
      <div className="min-w-0 overflow-x-auto rounded-xl border border-border bg-background p-6 text-foreground">{children}</div>
    </section>
  );
}

/** 一行:左边一列小字说明,右边是样子。 */
function Row({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className="grid grid-cols-[128px_minmax(0,1fr)] items-center gap-4">
      <span className="text-ui-xs text-muted-foreground">{label}</span>
      <div className={cn("flex min-w-0 flex-wrap items-center gap-3", className)}>{children}</div>
    </div>
  );
}

function Caption({ children }: { children: React.ReactNode }) {
  return <span className="text-ui-2xs text-muted-foreground">{children}</span>;
}

const SAMPLE_OPTIONS = [
  { value: "edge", label: "Edge 免费语音" },
  { value: "doubao", label: "豆包语音合成" },
  { value: "minimax", label: "MiniMax 语音" },
];

function SampleSelect({ size, placeholder = false, className = "w-44" }: { size?: "xs" | "sm" | "md"; placeholder?: boolean; className?: string }) {
  return (
    <Select defaultValue={placeholder ? undefined : "edge"}>
      <SelectTrigger size={size} className={className} aria-label="下拉">
        <SelectValue placeholder="选择模型" />
      </SelectTrigger>
      <SelectContent>
        {SAMPLE_OPTIONS.map((one) => (
          <SelectItem key={one.value} value={one.value}>
            {one.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function ScaleRows() {
  const [segment, setSegment] = React.useState("create");
  const tiers = [
    { tier: "xs · 28", button: "xs", field: "xs", icon: "icon-xs" },
    { tier: "sm · 32", button: "sm", field: "sm", icon: "icon-sm" },
    { tier: "md · 40", button: "default", field: "md", icon: "icon" },
  ] as const;
  return (
    <div className="grid gap-4">
      {tiers.map((one) => (
        <Row key={one.tier} label={one.tier}>
          <Button size={one.button}>
            <Plus /> 主动作
          </Button>
          <Button size={one.button} variant="outline">
            描边
          </Button>
          <Input size={one.field} className="w-44" placeholder="输入框" aria-label="输入框" />
          <SampleSelect size={one.field} />
          <Segmented aria-label="分段" size={one.field} value={segment} onValueChange={setSegment} options={SEGMENT_OPTIONS} />
          <IconButton size={one.icon} variant="outline" label="图标按钮">
            <Ellipsis />
          </IconButton>
        </Row>
      ))}
      <Row label="lg · 44">
        <Button size="lg">整页唯一的动作</Button>
        <Caption>只给登录页、首次引导</Caption>
      </Row>
      <Row label="行内 · 24">
        <span className="text-ui-sm">不知道</span>
        <Button variant="inline">
          <Search /> 在 Civitai 上找
        </Button>
        <Caption>不撑高那一行</Caption>
      </Row>
    </div>
  );
}

const SEGMENT_OPTIONS = [
  { value: "chat", label: "对话" },
  { value: "create", label: "创作" },
  { value: "old", label: "以前的" },
];

const STATES = [
  { key: "rest", label: "默认" },
  { key: "hover", label: "悬停" },
  { key: "focus-visible", label: "键盘聚焦" },
  { key: "disabled", label: "禁用" },
  { key: "loading", label: "在跑" },
] as const;

const VARIANTS = [
  { variant: "default", label: "主 default" },
  { variant: "secondary", label: "次 secondary" },
  { variant: "outline", label: "描边 outline" },
  { variant: "ghost", label: "幽灵 ghost" },
  { variant: "inline", label: "行内 inline" },
  { variant: "destructive", label: "危险 destructive" },
] as const;

function ButtonStates() {
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-[128px_repeat(5,minmax(112px,1fr))] items-center gap-3">
        <span />
        {STATES.map((state) => (
          <Caption key={state.key}>{state.label}</Caption>
        ))}
        {VARIANTS.map((one) => (
          <React.Fragment key={one.variant}>
            <span className="text-ui-xs text-muted-foreground">{one.label}</span>
            {STATES.map((state) => (
              <span key={state.key} className="flex items-center">
                <Button
                  variant={one.variant}
                  disabled={state.key === "disabled"}
                  loading={state.key === "loading"}
                  data-sheet-state={state.key === "hover" || state.key === "focus-visible" ? state.key : undefined}
                >
                  {one.variant === "destructive" ? <Trash2 /> : <Download />}
                  {one.variant === "destructive" ? "删除" : "导出"}
                </Button>
              </span>
            ))}
          </React.Fragment>
        ))}
      </div>
      <Row label="菜单项">
        <div role="menu" aria-label="菜单样子" className={cn(FLOATING_SURFACE, MENU_WIDTH, "grid p-1")}>
          <MenuItem icon={<Upload />} label="重命名" shortcut="F2" />
          <MenuItem icon={<Layers />} label="复制一份" description="名字下面一行说明 12px" data-sheet-state="hover" />
          <MenuItem icon={<MousePointer2 />} label="跟着系统" checked />
          <MenuItem icon={<Trash2 />} label="删除" destructive />
        </div>
        <Caption>最矮 36px、14px 字,不跟触发它的按钮变档</Caption>
      </Row>
    </div>
  );
}

function ButtonSizes() {
  const tiers = [
    { label: "xs · 28(图标 14)", text: "xs", icon: "icon-xs" },
    { label: "sm · 32(图标 16)", text: "sm", icon: "icon-sm" },
    { label: "md · 40(图标 16)", text: "default", icon: "icon" },
  ] as const;
  return (
    <div className="grid gap-4">
      {tiers.map((one) => (
        <Row key={one.label} label={one.label}>
          <Button size={one.text} variant="outline">
            <Plus /> 新建
          </Button>
          <Button size={one.text} variant="ghost">
            <Bot /> 交给智能体
          </Button>
          <IconButton size={one.icon} label="更多">
            <Ellipsis />
          </IconButton>
          <IconButton size={one.text === "default" ? "sm" : one.text} label="操控方式" className="gap-0.5 px-1.5">
            <Layers />
            <ChevronDown className="size-3! opacity-70" />
          </IconButton>
        </Row>
      ))}
      <Caption>最后一颗是「图标 + 小下拉箭头」的图标按钮(借文字档让宽度跟着内容走),图标照旧 16</Caption>
    </div>
  );
}

function FieldStates() {
  const [time, setTime] = React.useState("09:30");
  const [picked, setPicked] = React.useState("edge");
  const [searched, setSearched] = React.useState("doubao");
  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-[128px_repeat(6,minmax(176px,1fr))] items-center gap-3">
        <span />
        {["占位", "有值", "聚焦", "禁用", "出错", "出错 · 聚焦"].map((label) => (
          <Caption key={label}>{label}</Caption>
        ))}
        {(["xs", "sm", "md"] as const).map((size) => (
          <React.Fragment key={size}>
            <span className="text-ui-xs text-muted-foreground">{size} · {size === "xs" ? 28 : size === "sm" ? 32 : 40}</span>
            <Input size={size} placeholder="搜索名字" aria-label="占位" />
            <Input size={size} defaultValue="三间展厅" aria-label="有值" />
            <Input size={size} defaultValue="三间展厅" aria-label="聚焦" data-sheet-state="focus" />
            <Input size={size} defaultValue="三间展厅" aria-label="禁用" disabled />
            <span className="grid gap-1">
              <Input size={size} defaultValue="三间展厅!" aria-label="出错" aria-invalid />
              <span className="text-ui-xs text-destructive">名字里不能有「!」</span>
            </span>
            <span className="grid gap-1">
              <Input size={size} defaultValue="三间展厅!" aria-label="出错 · 聚焦" aria-invalid data-sheet-state="focus" />
              <span className="text-ui-xs text-destructive">名字里不能有「!」</span>
            </span>
          </React.Fragment>
        ))}
      </div>
      <Row label="同一种外观 · md">
        <Input className="w-44" placeholder="文字" aria-label="文字" />
        <Input className="w-28" type="number" defaultValue={24} aria-label="数字" />
        <Input className="w-44" type="date" defaultValue="2026-10-08" aria-label="日期" />
        <SampleSelect placeholder />
        <OptionPicker className="w-44" value={picked} onChange={setPicked} options={SAMPLE_OPTIONS} ariaLabel="选项选择器" />
        <SearchableSelect className="w-44" value={searched} onValueChange={setSearched} options={SAMPLE_OPTIONS} />
        <TimePicker className="w-32" value={time} onChange={setTime} ariaLabel="时间" />
      </Row>
      <Row label="文本域">
        <Textarea className="w-96" placeholder="描述你想生成的画面…" aria-label="文本域" />
        <Textarea className="w-96" defaultValue="一间光线很好的展厅,镜头从门口慢慢推进。" aria-label="文本域 · 有值" />
      </Row>
      <Row label="下拉触发器(静态)">
        <span aria-hidden className={cn(fieldTriggerClass("md"), "w-44")}>
          <span>值靠左</span>
          <ChevronDown className={FIELD_TRIGGER_CHEVRON} />
        </span>
        <Caption>值一律靠左,箭头 16px、半透明、顶到最右;不自己画触发器</Caption>
      </Row>
      <Row label="标签和值">
        <div className="grid w-72 gap-2">
          <span className="text-ui-sm font-medium">模型</span>
          <SampleSelect />
          <span className="text-ui-xs text-muted-foreground">说明文字 12px 次要色</span>
        </div>
        <dl className="m-0 grid w-80 gap-2">
          <div className="grid grid-cols-[88px_minmax(0,1fr)] items-baseline gap-x-3">
            <dt className="text-ui-xs text-muted-foreground">来源</dt>
            <dd className="m-0 text-ui-sm">Civitai · 写实人像</dd>
          </div>
          <div className="grid grid-cols-[88px_minmax(0,1fr)] items-baseline gap-x-3">
            <dt className="text-ui-xs text-muted-foreground">大小</dt>
            <dd className="m-0 text-ui-sm">6.5 GB</dd>
          </div>
        </dl>
        <Caption>填值:标签 14 中等字重;只读「名字 | 值」:名字 12 次要色、值 14</Caption>
      </Row>
    </div>
  );
}

function Choices() {
  const [segment, setSegment] = React.useState("create");
  const [filter, setFilter] = React.useState("all");
  const [tags, setTags] = React.useState<string[]>(["人像"]);
  const [tab, setTab] = React.useState("character");
  const [on, setOn] = React.useState(true);
  const [theme, setTheme] = React.useState("system");
  return (
    <div className="grid gap-4">
      {(["md", "sm", "xs"] as const).map((size) => (
        <Row key={size} label={`分段 · ${size} ${size === "md" ? 40 : size === "sm" ? 32 : 28}`}>
          <Segmented aria-label={`分段 ${size}`} size={size} value={segment} onValueChange={setSegment} options={SEGMENT_OPTIONS} />
          <Segmented
            aria-label={`分段 ${size} · 有点不了的`}
            size={size}
            value="grid"
            onValueChange={() => undefined}
            options={[
              { value: "grid", label: "网格" },
              { value: "list", label: "列表" },
              { value: "board", label: "画板", disabled: true },
            ]}
          />
        </Row>
      ))}
      <Row label="分段 · 铺满一行">
        <div className="w-96">
          <Segmented aria-label="分段 · 铺满" fill value="mid" onValueChange={() => undefined} options={[{ value: "low", label: "轻" }, { value: "mid", label: "中" }, { value: "high", label: "重" }]} />
        </div>
        <Caption>对话框里那种一整行的,每项等宽</Caption>
      </Row>
      <Row label="胶囊筛选 · 28">
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="种类">
          {[
            ["all", "全部", null],
            ["image", "图像", <ImageIcon key="i" />],
            ["video", "视频", <Film key="v" />],
            ["speech", "语音", <Mic key="m" />],
          ].map(([value, label, icon]) => (
            <Chip key={value as string} role="tab" selected={filter === value} icon={icon} onClick={() => setFilter(value as string)}>
              {label}
            </Chip>
          ))}
        </div>
        <div className="flex flex-wrap gap-1" role="group" aria-label="标签">
          {["人像", "风景", "夜景"].map((tag) => (
            <Chip key={tag} selected={tags.includes(tag)} onClick={() => setTags((now) => (now.includes(tag) ? now.filter((one) => one !== tag) : [...now, tag]))}>
              {tag}
            </Chip>
          ))}
        </div>
        <Caption>单选当页签读(role=tab),多选是切换按钮(aria-pressed)</Caption>
      </Row>
      <Row label="页签">
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="character">人物</TabsTrigger>
            <TabsTrigger value="location">场景</TabsTrigger>
            <TabsTrigger value="prop">道具</TabsTrigger>
          </TabsList>
        </Tabs>
        <CollectionTabs
          value={tab}
          onChange={setTab}
          label="页签 · 列表页那一种"
          items={[
            { value: "character", label: "人物", count: 3 },
            { value: "location", label: "场景", count: 0 },
            { value: "prop", label: "道具", count: 1 },
          ]}
        />
        <Caption>单独一条 44 带分隔线;列表页筛选条里那一排随那一行 40。字和选中样子同一种</Caption>
      </Row>
      <Row label="开关">
        <Switch checked={on} onCheckedChange={setOn} aria-label="开关" />
        <Switch checked={false} aria-label="开关 · 关" />
        <Switch checked disabled aria-label="开关 · 禁用" />
        <Switch checked={false} aria-label="开关 · 键盘聚焦" data-sheet-state="focus-visible" />
        <Caption>20×36,开为强调色</Caption>
      </Row>
      <Row label="复选">
        <Checkbox aria-label="未选" />
        <Checkbox checked aria-label="已选" />
        <Checkbox checked="indeterminate" aria-label="半选" />
        <Checkbox checked disabled aria-label="禁用" />
        <Checkbox aria-label="键盘聚焦" data-sheet-state="focus-visible" />
        <Caption>16px,圆角 4</Caption>
      </Row>
      <Row label="单选">
        <RadioGroup
          aria-label="主题"
          value={theme}
          onValueChange={setTheme}
          options={[
            { value: "system", label: "跟着系统", description: "系统切深色时一起切" },
            { value: "light", label: "总是浅色", description: "不管系统怎么设" },
            { value: "dark", label: "总是深色", description: "这一项点不了", disabled: true },
          ]}
        />
        <RadioGroup
          aria-label="清晰度"
          orientation="horizontal"
          value="1080"
          onValueChange={() => undefined}
          options={[
            { value: "720", label: "720p" },
            { value: "1080", label: "1080p" },
            { value: "4k", label: "4K" },
          ]}
        />
      </Row>
    </div>
  );
}

function SceneSamples() {
  const [mode, setMode] = React.useState<CanvasInputMode>("trackpad");
  return (
    <div className="grid gap-6">
      <Row label="页头 · md" className="block">
        <PageHeading
          title="3D 场景"
          count={3}
          description="页头的动作是 md;一屏只有一颗实心。"
          actions={
            <>
              <Button variant="outline">
                <Upload /> 导入
              </Button>
              <Button>
                <Plus /> 新建场景
              </Button>
            </>
          }
        />
      </Row>
      <Row label="对话框 / 表单 · md">
        <div className="grid w-[420px] gap-4 rounded-2xl border border-border bg-card p-5">
          <div className="grid gap-2">
            <span className="text-ui-sm font-medium">连接名称</span>
            <Input defaultValue="家里那台 ComfyUI" aria-label="连接名称" />
          </div>
          <div className="grid gap-2">
            <span className="text-ui-sm font-medium">地址</span>
            <Input defaultValue="http://192.168.3.15:8188" aria-label="地址" />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline">取消</Button>
            <Button>保存</Button>
          </div>
        </div>
      </Row>
      <Row label="侧栏面板 · md">
        <div className="grid w-[300px] gap-4 rounded-xl border border-border bg-panel p-4">
          <div className="flex items-center justify-between">
            <span className="text-ui-sm font-semibold">引擎参数</span>
            <IconButton size="icon-sm" label="关闭">
              <X />
            </IconButton>
          </div>
          <div className="grid gap-2">
            <span className="text-ui-sm font-medium">模型</span>
            <SampleSelect className="w-full" />
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)_88px] gap-2">
            <span className="text-ui-sm font-medium">音色</span>
            <span className="text-ui-sm font-medium">语速</span>
            <span className="flex min-w-0 gap-2">
              <Select defaultValue="yunxi">
                <SelectTrigger aria-label="音色">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="yunxi">云希(男·阳光)</SelectItem>
                </SelectContent>
              </Select>
              <IconButton size="icon" variant="outline" label="试听">
                <Volume2 />
              </IconButton>
            </span>
            <Select defaultValue="1">
              <SelectTrigger aria-label="语速">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="1">1×</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <Caption>模型、音色、语速、试听方钮都是 40(维护者定的「音色那一档」);面板标题栏上的关闭是 sm</Caption>
      </Row>
      <Row label="窗口顶栏 · sm">
        <div className="flex w-[560px] items-center gap-1 rounded-lg border border-border bg-panel px-3 py-3">
          <IconButton size="icon-sm" label="收起侧栏">
            <Layers />
          </IconButton>
          <span className="ml-2 flex-1 text-ui-sm font-semibold">AI Studio</span>
          <Button size="sm" variant="outline" className="gap-1.5 rounded-full">
            3 个请求等你确认
          </Button>
          <IconButton size="icon-sm" label="任务中心">
            <Bot />
          </IconButton>
          <IconButton size="icon-sm" label="主题">
            <Ellipsis />
          </IconButton>
        </div>
        <Caption>顶栏 56px 高,里面的按钮、搜索框都是 32</Caption>
      </Row>
      <Row label="画布工具条 · sm">
        <div className="flex items-center gap-1 rounded-lg border border-border bg-panel p-1">
          <IconButton label="选择" aria-pressed variant="ghost" className="bg-accent text-accent-foreground">
            <MousePointer2 />
          </IconButton>
          <IconButton label="添加">
            <Plus />
          </IconButton>
          <Button size="sm" variant="ghost">
            <Bot /> 智能体
          </Button>
          <CanvasInputModeMenu mode={mode} onChange={setMode} />
        </div>
      </Row>
      <Row label="密集工具条 · xs">
        <div className="flex items-center gap-1 rounded-lg border border-border bg-control px-2 py-1">
          <Button size="xs" variant="ghost">
            @ 资产
          </Button>
          <IconButton size="icon-xs" label="附件">
            <Upload />
          </IconButton>
          <Input size="xs" className="w-36" placeholder="搜索" aria-label="搜索" />
          <IconButton size="icon-xs" label="更多">
            <Ellipsis />
          </IconButton>
        </div>
      </Row>
      <Row label="卡片 · sm">
        <div className="grid w-64 gap-3 rounded-xl border border-border bg-card p-3">
          <div className="aspect-video rounded-lg bg-muted" />
          <div className="flex items-center justify-between gap-2">
            <Truncate className="text-ui-sm font-medium">三间展厅</Truncate>
            <span className="flex items-center gap-1">
              <Button size="sm" variant="outline">
                打开
              </Button>
              <IconButton size="icon-sm" label="更多">
                <Ellipsis />
              </IconButton>
            </span>
          </div>
        </div>
      </Row>
      <Row label="挨着值 · 行内">
        <dl className="m-0 grid w-[420px] gap-2">
          <div className="grid grid-cols-[88px_minmax(0,1fr)] items-baseline gap-x-3">
            <dt className="text-ui-xs text-muted-foreground">来源</dt>
            <dd className="m-0 flex flex-wrap items-center gap-x-2 text-ui-sm">
              不知道
              <Button variant="inline">
                <Search /> 在 Civitai 上找
              </Button>
            </dd>
          </div>
          <div className="grid grid-cols-[88px_minmax(0,1fr)] items-baseline gap-x-3">
            <dt className="text-ui-xs text-muted-foreground">NSFW</dt>
            <dd className="m-0 flex flex-wrap items-center gap-x-2 text-ui-sm">
              没有依据说它是 NSFW
              <Button variant="inline">标为 NSFW</Button>
            </dd>
          </div>
        </dl>
      </Row>
    </div>
  );
}

const MOTION = [
  { label: "快 100ms", className: "duration-100", use: "行上的悬停底色、小箭头转向" },
  { label: "中 160ms", className: "duration-160", use: "换颜色、浮层进出、折叠" },
  { label: "慢 240ms", className: "duration-240", use: "抽屉、大图放大" },
  { label: "余韵 600ms", className: "duration-600", use: "「刚做完」的高亮退掉" },
] as const;

function MotionSamples() {
  return (
    <div className="grid gap-3">
      {MOTION.map((one) => (
        <Row key={one.label} label={one.label}>
          <span className={cn("block h-8 w-40 rounded-md border border-border bg-control transition-colors ease-enter hover:bg-accent", one.className)} />
          <Caption>{one.use}</Caption>
        </Row>
      ))}
      <Row label="缓动">
        <Caption>出现 ease-enter(先快后慢)· 消失 ease-exit(先慢后快)</Caption>
      </Row>
    </div>
  );
}
