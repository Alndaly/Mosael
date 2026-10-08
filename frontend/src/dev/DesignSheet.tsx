import * as React from "react";
import { Bot, ChevronDown, Download, Ellipsis, Layers, MousePointer2, Plus, Search, Trash2, Upload, Volume2, X } from "lucide-react";

import { CanvasInputModeMenu } from "@/components/app/CanvasInputModeMenu";
import type { CanvasInputMode } from "@/components/app/canvasInputMode";
import { CollectionTabs, PageHeading } from "@/components/layout/StudioPage";
import { Button, buttonVariants } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { FIELD_TRIGGER_CHEVRON, fieldTriggerClass } from "@/components/ui/field-trigger";
import { FLOATING_SURFACE, MENU_WIDTH } from "@/components/ui/floating";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { MenuItem } from "@/components/ui/menu";
import { OptionPicker } from "@/components/ui/option-picker";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { SEGMENTED_LIST, segmentedTriggerClass, Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { TimePicker } from "@/components/ui/time-picker";
import { Truncate } from "@/components/ui/truncate";
import { cn } from "@/lib/utils";

/**
 * 设计语言的**规格样张**(docs/DESIGN_LANGUAGE.md):每一档、每一类控件、每一种状态;顶上切浅色 / 深色。只在开发构建里有
 * (`#/dev/design`,见 app/App.tsx),不进发行包。
 *
 * - 「悬停」「键盘聚焦」两列在截图里是用开发者工具强制出来的(`data-sheet-state`);在页面上自己移上去、按 Tab 看。
 * - 标着「拟」的是规格里定了、基础组件还没有的样子(待拍板那几条):画成静态的样子摆在「现在」旁边,拍板后第 2 步落进基础组件,
 *   这里换成真组件。
 * - 文字写死中文:这一页是给维护者拍板看的,不给用户看(design/uiTextIsTranslated.test.ts 的 EXEMPT 里记着)。
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
            规则见 docs/DESIGN_LANGUAGE.md。「悬停」「键盘聚焦」两列在截图里是强制出来的。标着「拟」的是待拍板、基础组件还没有的样子。
          </p>
          <div className={cn(SEGMENTED_LIST, "justify-self-start")} role="radiogroup" aria-label="主题">
            {(["light", "dark"] as const).map((one) => (
              <button
                key={one}
                type="button"
                role="radio"
                aria-checked={theme === one}
                data-sheet-theme-toggle={one}
                className={segmentedTriggerClass(theme === one)}
                onClick={() => setTheme(one)}
              >
                {one === "light" ? "浅色" : "深色"}
              </button>
            ))}
          </div>
        </header>
        <Section id="scale" title="一、刻度:同档同高" note="每一行是一档:按钮、描边按钮、输入框、下拉、图标按钮并排,一样高。md 那一行的图标按钮现在是 36(下一行),规格是 40(拟)。">
          <ScaleRows />
        </Section>
        <Section id="buttons" title="二、按钮:变体 × 状态" note="一屏只有一个主(实心)。危险只用在确认弹窗里那一颗上。行内动作挨着值,不写 size。">
          <ButtonStates />
        </Section>
        <Section id="button-sizes" title="三、按钮:档位 × 图标" note="按钮里的图标大小由档位定,在图标上写 size 不生效。xs 文字按钮里的图标现在 16,规格 14(拟)。">
          <ButtonSizes />
        </Section>
        <Section id="fields" title="四、字段:一种外观" note="输入框、下拉、可搜索下拉、选项选择器、时间、数字、日期、文本域同一种描边、底色、圆角、留白、字号。出错现在只有下面那行红字(拟:描边和聚焦环变红)。">
          <FieldStates />
        </Section>
        <Section id="choices" title="五、选择类控件" note="分段控件现在只有一档 40,各处用 className 压成别的高度(拟:md 40 / sm 32 / xs 28 三档);胶囊筛选 24 还是 28 待拍板;单选还没有基础件(拟)。">
          <Choices />
        </Section>
        <Section id="scenes" title="六、场景 → 档位" note="先认容器再认档:填值的地方 md,画布工具条 sm,密集工具条 xs,挨着值的是行内。">
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

/** 「拟」:规格定了、基础组件还没有的样子 —— 静态画出来,不能点。 */
function Proposed({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-2" data-sheet-proposed="">
      {children}
      <span className="rounded-full bg-accent px-1.5 text-ui-2xs font-medium leading-5 text-accent-foreground">拟</span>
    </span>
  );
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
  const tiers = [
    { tier: "xs · 28", button: "xs", field: "xs", icon: "icon-xs" },
    { tier: "sm · 32", button: "sm", field: "sm", icon: "icon-sm" },
    { tier: "md · 40", button: "default", field: "md", icon: null },
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
          {one.icon ? (
            <IconButton size={one.icon} variant="outline" label="图标按钮">
              <Ellipsis />
            </IconButton>
          ) : (
            <Proposed>
              <span aria-hidden className={cn(buttonVariants({ variant: "outline", size: "icon" }), "pointer-events-none")} style={{ width: 40, height: 40 }}>
                <Ellipsis />
              </span>
            </Proposed>
          )}
        </Row>
      ))}
      <Row label="md 图标按钮 · 现在">
        <IconButton size="icon" variant="outline" label="图标按钮(36)">
          <Ellipsis />
        </IconButton>
        <Caption>36px,比同档的 40 矮一截 —— 待拍板 1</Caption>
      </Row>
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
  return (
    <div className="grid gap-4">
      <Row label="xs · 28">
        <Button size="xs" variant="outline">
          <Plus /> 新建
        </Button>
        <Button size="xs" variant="ghost">
          <Bot /> 交给智能体
        </Button>
        <IconButton size="icon-xs" label="更多">
          <Ellipsis />
        </IconButton>
        <Caption>文字按钮里的图标现在 16</Caption>
      </Row>
      <Row label="xs · 规格">
        <Proposed>
          <span aria-hidden className={cn(buttonVariants({ variant: "outline", size: "xs" }), "pointer-events-none")}>
            <Plus style={{ width: 14, height: 14 }} /> 新建
          </span>
          <span aria-hidden className={cn(buttonVariants({ variant: "ghost", size: "xs" }), "pointer-events-none")}>
            <Bot style={{ width: 14, height: 14 }} /> 交给智能体
          </span>
        </Proposed>
        <Caption>文字按钮 14;只有图标的不变,16 —— 待拍板 2</Caption>
      </Row>
      <Row label="sm · 32">
        <Button size="sm" variant="outline">
          <Plus /> 新建
        </Button>
        <Button size="sm" variant="ghost">
          <Bot /> 交给智能体
        </Button>
        <IconButton size="icon-sm" label="更多">
          <Ellipsis />
        </IconButton>
      </Row>
      <Row label="md · 40">
        <Button variant="outline">
          <Plus /> 新建
        </Button>
        <Button variant="ghost">
          <Bot /> 交给智能体
        </Button>
        <IconButton size="icon" label="更多(现在 36)">
          <Ellipsis />
        </IconButton>
      </Row>
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
        {["占位", "有值", "聚焦", "禁用", "出错 · 现在", "出错 · 规格"].map((label) => (
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
              <Input size={size} defaultValue="三间展厅!" aria-label="出错 · 现在" aria-invalid />
              <span className="text-ui-xs text-destructive">名字里不能有「!」</span>
            </span>
            <span className="grid gap-1">
              <Proposed>
                <Input size={size} defaultValue="三间展厅!" aria-label="出错 · 规格" aria-invalid className="border-destructive focus-visible:ring-destructive" />
              </Proposed>
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

/** 拟:分段控件的某一档(静态)。外壳 = 次级底色 + 内边距,圆角 = 里面 8 + 内边距。 */
function ProposedSegmented({ height, item, pad, text }: { height: number; item: number; pad: number; text: "text-ui-sm" | "text-ui-xs" }) {
  return (
    <span aria-hidden className={cn(SEGMENTED_LIST, "pointer-events-none min-h-0")} style={{ height, padding: pad }}>
      {["对话", "创作", "以前的"].map((label, index) => (
        <span key={label} className={cn(segmentedTriggerClass(index === 1), "min-h-0", text)} style={{ height: item }}>
          {label}
        </span>
      ))}
    </span>
  );
}

function ProposedChips({ height }: { height: number }) {
  return (
    <span className="flex flex-wrap gap-1">
      {["全部", "图像", "视频", "语音"].map((label, index) => (
        <span
          key={label}
          aria-hidden
          className={cn(
            "inline-flex shrink-0 items-center gap-1 rounded-full border px-2.5 text-ui-xs font-medium",
            index === 0
              ? "border-[color-mix(in_srgb,var(--primary)_40%,transparent)] bg-accent text-accent-foreground"
              : "border-border text-muted-foreground",
          )}
          style={{ height }}
        >
          {label}
        </span>
      ))}
    </span>
  );
}

function ProposedRadio({ checked, label, description }: { checked: boolean; label: string; description: string }) {
  return (
    <span className="flex items-start gap-2.5" aria-hidden>
      <span className={cn("mt-0.5 grid size-4 shrink-0 place-items-center rounded-full border", checked ? "border-primary" : "border-input bg-field")}>
        {checked && <span className="size-2 rounded-full bg-action" />}
      </span>
      <span className="grid gap-0.5">
        <span className="text-ui-sm">{label}</span>
        <span className="text-ui-xs text-muted-foreground">{description}</span>
      </span>
    </span>
  );
}

function Choices() {
  const [segment, setSegment] = React.useState("create");
  const [tab, setTab] = React.useState("character");
  const [on, setOn] = React.useState(true);
  return (
    <div className="grid gap-4">
      <Row label="分段 · 现在">
        <div className={SEGMENTED_LIST} role="tablist" aria-label="分段 · 现在">
          {[
            ["chat", "对话"],
            ["create", "创作"],
          ].map(([value, label]) => (
            <button key={value} type="button" role="tab" aria-selected={segment === value} className={segmentedTriggerClass(segment === value)} onClick={() => setSegment(value)}>
              {label}
            </button>
          ))}
        </div>
        <Caption>只有 40 这一档;别处在 className 里压成 36 / 32 / 28 / 24 等六种 —— 待拍板 3</Caption>
      </Row>
      <Row label="分段 · 规格">
        <Proposed>
          <ProposedSegmented height={40} item={32} pad={4} text="text-ui-sm" />
        </Proposed>
        <Caption>md 40(项 32)</Caption>
        <Proposed>
          <ProposedSegmented height={32} item={28} pad={2} text="text-ui-xs" />
        </Proposed>
        <Caption>sm 32(项 28)</Caption>
        <Proposed>
          <ProposedSegmented height={28} item={24} pad={2} text="text-ui-xs" />
        </Proposed>
        <Caption>xs 28(项 24)</Caption>
      </Row>
      <Row label="胶囊筛选">
        <Proposed>
          <ProposedChips height={24} />
        </Proposed>
        <Caption>24(AI Studio 现在的)</Caption>
        <Proposed>
          <ProposedChips height={28} />
        </Proposed>
        <Caption>28(和 xs 对齐)—— 待拍板 4</Caption>
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
        <Caption>两种写法(Radix Tabs 和列表页的 CollectionTabs)要长得一样</Caption>
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
        <Proposed>
          <span className="grid gap-2">
            <ProposedRadio checked label="跟着系统" description="系统切深色时一起切" />
            <ProposedRadio checked={false} label="总是浅色" description="不管系统怎么设" />
          </span>
        </Proposed>
        <Caption>还没有基础件 —— 待拍板 6</Caption>
      </Row>
      <Row label="按下 / 选中">
        <Button variant="outline" size="sm" aria-pressed>
          <MousePointer2 /> 选择(按下)
        </Button>
        <Caption>现在:Button 不认 aria-pressed,各处自己写</Caption>
        <Proposed>
          <span aria-hidden className={cn(buttonVariants({ variant: "outline", size: "sm" }), "pointer-events-none bg-accent text-accent-foreground")}>
            <MousePointer2 /> 选择(按下)
          </span>
        </Proposed>
        <Caption>强调底色 + 强调色前景,和分段选中项同一种</Caption>
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
            <Select defaultValue="yunxi">
              <SelectTrigger aria-label="音色">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="yunxi">云希(男·阳光)</SelectItem>
              </SelectContent>
            </Select>
            <Select defaultValue="1">
              <SelectTrigger aria-label="语速">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="1">1×</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button variant="outline" className="justify-self-start">
            <Volume2 /> 试听一句
          </Button>
        </div>
        <Caption>模型、音色、语速都是 40(维护者定的「音色那一档」);面板标题栏上的关闭是 sm</Caption>
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
