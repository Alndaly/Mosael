import React from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { CONTROL_HEIGHT } from "@/components/ui/control-size";
import { cn } from "@/lib/utils";

/**
 * Shared settings building blocks: every section is a Group (title +
 * description + optional header actions) containing Rows (label +
 * description on the left, control on the right). Groups are deliberately
 * flat: the settings page already owns the surrounding panel, so another
 * rounded card here would create a frame inside a frame.
 *
 * Row dividers come from the group body's `[&>*+*]:border-t`, so a Group's children must be
 * only Rows, ItemRows and Blocks. Any other element between two of them — including a display:none
 * one, which sibling selectors do not skip — adds or shifts a divider.
 * Hidden file inputs belong inside the Row whose control opens them.
 *
 * 住在 components/ 而不是 features/settings/ 里:设置、插件、定时任务、管理四个页面都是这个
 * 版式,而前三个曾经要 import 第四个的内部文件才能画一行设置 —— 一套给大家用的版式不该长在
 * 某个功能里面(棘轮:features/featureBoundaries.test.ts 管的是同一件事的更严重形态)。
 */

export function SettingsGroup({
  title,
  description,
  actions,
  className,
  contentClassName,
  children,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  className?: string;
  contentClassName?: string;
  /** 没有内容时**不画那个框** —— 只有标题和说明的分组(比如"自助注册已开放")本来就没有行,
   *  空着渲染出来是一条无缘无故的横线。 */
  children?: React.ReactNode;
}) {
  const hasContent = React.Children.toArray(children).some(Boolean);
  return (
    <section data-slot="settings-group" className={cn("@container/settings grid gap-1", className)}>
      {/* 动作**对齐整个抬头的竖向中心**,不是对齐标题那一行,也不是对齐整块的底边。
          三种都试过:`items-end` 在说明一长时把按钮拖到最后一行旁边,看着像那句话的一部分;
          `items-start` 则在说明有两三行时把按钮顶在最上面,右边空出一大块。
          `items-center` 两头都不沾 —— 按钮始终落在这一节抬头的视觉重心上。 */}
      <header
        data-slot="settings-group-header"
        className={cn(
          "flex flex-wrap items-start justify-between gap-4 px-0.5",
          hasContent && "pb-2",
        )}
      >
        <div className="min-w-0">
          <h2
            data-slot="settings-group-title"
            className="m-0 text-xl font-semibold leading-snug tracking-tight"
          >
            {title}
          </h2>
          {description && (
            <p
              data-slot="settings-group-description"
              className="mb-0 mt-1.5 max-w-2xl text-ui-md leading-[1.55] text-muted-foreground"
            >
              {description}
            </p>
          )}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </header>
      {hasContent && (
        <div
          data-slot="settings-group-content"
          className={cn("grid [&>*+*]:border-t [&>*+*]:border-divider", contentClassName)}
        >
          {children}
        </div>
      )}
    </section>
  );
}

export function SettingsRow({
  id,
  className,
  controlClassName,
  label,
  description,
  stacked = false,
  children,
}: {
  id?: string;
  className?: string;
  controlClassName?: string;
  label: React.ReactNode;
  /** 通常是一句 i18n 文案;数据里带格式的说明(插件的配置帮助)传 `<InlineMarkdown>`。 */
  description?: React.ReactNode;
  /**
   * 控件放到标题下面、占满整行。给**要写一段话**的控件(多行文本框)用。
   *
   * 默认布局把控件放在右边一格 `auto` 列里,那一格按控件自己的宽度收 —— 下拉、开关正合适,
   * 一个文本框却会被挤成一条窄缝(自动放行的「补充说明」就是这样,写三行字要换十行)。调用方
   * 想用 className 覆盖成单列也盖不住:宽屏下那条 `@min-[620px]` 的两列规则更具体。
   */
  stacked?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <div
      id={id}
      data-slot="settings-row"
      className={cn(
        "grid grid-cols-1 items-start gap-3 px-0.5 py-5",
        !stacked && "@min-[620px]/settings:grid-cols-[minmax(0,1fr)_auto] @min-[620px]/settings:items-center @min-[620px]/settings:gap-8",
        className,
      )}
    >
      <div className="grid min-w-0 gap-1">
        <span data-slot="settings-row-label" className="text-ui-md font-medium leading-relaxed">{label}</span>
        {description && (
          <small data-slot="settings-row-description" className="text-ui-sm leading-[1.5] text-muted-foreground">
            {description}
          </small>
        )}
      </div>
      {children && (
        <div className={cn(stacked ? "grid min-w-0" : "flex min-w-0 flex-wrap items-center gap-2", controlClassName)}>{children}</div>
      )}
    </div>
  );
}

/**
 * 一行"东西"(一个引擎、一个模型):名字 + 小字元信息 + 说明在左,状态或动作在右,
 * 需要时底下再挂一条横贯整行的进度。
 *
 * 和 SettingsRow **同一套版式**:同样的内边距、同样的两列、同样由分组画分隔线,标签和说明也是
 * 同一档字号 —— 于是一页"引擎列表"和一页"开关设置"读起来是同一个设置页。此前转写、配音、
 * 人声分离、降噪四页各画一叠带边框的卡片(卡片里还套着描边的大写小标),和其余设置格格不入。
 *
 * 为什么不直接用 SettingsRow:它表达不了三件事 —— 名字旁边的元信息(引擎族、大小、标签),
 * 说明下面按状态出现的几行(「正在检查运行环境…」、失败原因),以及横贯整行的进度条。
 * 这三件分别是 `meta`/`tags`、`notes`、`footer` 三个插槽;右边照旧是 children。
 */
export function SettingsItemRow({
  id,
  className,
  label,
  meta,
  tags,
  description,
  notes,
  footer,
  children,
}: {
  id?: string;
  className?: string;
  label: React.ReactNode;
  /** 名字后面的小字,逐项用「·」隔开(引擎族、大小)。假值自动跳过。 */
  meta?: readonly React.ReactNode[];
  /** 名字后面的安静标签,用 SettingsTag。 */
  tags?: React.ReactNode;
  description?: React.ReactNode;
  /** 说明下面按状态出现的几行,用 SettingsItemNote。 */
  notes?: React.ReactNode;
  /** 横贯整行、在最下面的一格 —— 下载进度条。 */
  footer?: React.ReactNode;
  /** 右边:SettingsItemState 或 `<Button size="sm" variant="outline">`。 */
  children?: React.ReactNode;
}) {
  const metaItems = (meta ?? []).filter((item) => item !== null && item !== undefined && item !== false && item !== "");
  return (
    <div
      id={id}
      data-slot="settings-item-row"
      className={cn(
        "grid grid-cols-1 items-start gap-3 px-0.5 py-5",
        "@min-[620px]/settings:grid-cols-[minmax(0,1fr)_auto] @min-[620px]/settings:items-center @min-[620px]/settings:gap-x-8",
        className,
      )}
    >
      <div className="grid min-w-0 gap-1">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <span data-slot="settings-item-label" className="text-ui-md font-medium leading-relaxed">
            {label}
          </span>
          {metaItems.length > 0 && (
            <span data-slot="settings-item-meta" className="text-ui-xs tabular-nums text-muted-foreground">
              {metaItems.map((item, index) => (
                <React.Fragment key={index}>
                  {index > 0 && " · "}
                  {item}
                </React.Fragment>
              ))}
            </span>
          )}
          {tags}
        </div>
        {description && (
          <small data-slot="settings-item-description" className="text-ui-sm leading-[1.5] text-muted-foreground">
            {description}
          </small>
        )}
        {notes}
      </div>
      {children && (
        <div data-slot="settings-item-control" className="flex min-w-0 flex-wrap items-center gap-2">
          {children}
        </div>
      )}
      {footer && (
        <div data-slot="settings-item-footer" className="min-w-0 @min-[620px]/settings:col-span-2">
          {footer}
        </div>
      )}
    </div>
  );
}

const NOTE_TONE = {
  muted: "text-muted-foreground",
  foreground: "text-foreground",
  destructive: "text-destructive",
} as const;

/** SettingsItemRow 说明下面的一行状态:检查中、跑不起来的原因、失败原因。和说明同一档字号,只换颜色。 */
export function SettingsItemNote({
  tone = "muted",
  icon,
  className,
  children,
}: {
  tone?: keyof typeof NOTE_TONE;
  icon?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <small
      data-slot="settings-item-note"
      data-tone={tone}
      className={cn(
        "flex min-w-0 items-center gap-1.5 text-ui-sm leading-[1.5] [&>svg]:shrink-0",
        NOTE_TONE[tone],
        className,
      )}
    >
      {icon}
      {children}
    </small>
  );
}

const STATE_TONE = {
  success: "font-medium text-success",
  muted: "text-muted-foreground",
} as const;

/**
 * SettingsItemRow 右边**不是按钮**时的那个状态(「已安装」、转圈 + 百分比)。
 *
 * 高度取 CONTROL_HEIGHT.sm,和同一格里的 `<Button size="sm">` 一样高 —— 一行从「下载」变成
 * 「已安装」时,整行不跳。
 */
export function SettingsItemState({
  tone = "muted",
  icon,
  children,
}: {
  tone?: keyof typeof STATE_TONE;
  icon?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <span
      data-slot="settings-item-state"
      data-tone={tone}
      className={cn(CONTROL_HEIGHT.sm, "inline-flex items-center gap-1.5 text-ui-sm tabular-nums [&>svg]:shrink-0", STATE_TONE[tone])}
    >
      {icon}
      {children}
    </span>
  );
}

const TAG_TONE = {
  neutral: "bg-secondary text-muted-foreground",
  warning: "bg-[color-mix(in_srgb,var(--warning)_14%,transparent)] text-warning",
} as const;

/**
 * 设置里的安静标签:语义色淡底的小圆角,不描边、不大写 —— 和飞书机器人的状态、计价规则的来源同一种。
 */
export function SettingsTag({ tone = "neutral", children }: { tone?: keyof typeof TAG_TONE; children: React.ReactNode }) {
  return (
    <span
      data-slot="settings-tag"
      data-tone={tone}
      className={cn("inline-flex shrink-0 items-center rounded-full px-1.5 text-ui-2xs font-medium leading-5", TAG_TONE[tone])}
    >
      {children}
    </span>
  );
}

/**
 * 设置行右边那一格的**标准宽度**。
 *
 * 那一格是 `auto` 列 —— 控件要多宽就多宽。于是各个 tab 各写各的:实测过一遍是
 * 320 / 260 / 200 / 180 六种宽度并存,而它们在版面上是同一个位置。一个 tab 切到另一个 tab,
 * 右边那一列会跟着跳,看起来像每一页的表单都是另一套刻度。
 *
 * 文字类的字段(地址、备注、下拉选名字)一律走这个宽度。**真的只装得下几个字符的不走** ——
 * 0–10 的重试次数、1.0× 的语速,给它 280px 只会在一个数字后面拖一条空槽;那种就地写死,
 * 并且写清楚为什么。
 */
export const SETTINGS_FIELD_WIDTH = "w-[280px] max-w-full";

/** Full-width slot inside a group (forms, QR panels, lists). */
export function SettingsBlock({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div data-slot="settings-block" className={cn("grid gap-4 px-0.5 py-5", className)}>{children}</div>;
}

/**
 * **一整节的正文空着**时用它 —— 飞书没有机器人、音色库没有音色、计价没有规则。
 *
 * 两件事收在这里,而不是每个调用点各写一遍:
 *
 * 1. **占住一片地方,并在里面居中。** 此前空态直接摆进 SettingsBlock,而 Block 是内容高度 ——
 *    于是「还没有机器人」贴在标题下面,底下空着三百多像素(实测 366px)。有两处试过写
 *    `h-full min-h-0`,不管用:SettingsSectionStack 是 `content-start`,行高按内容算,
 *    `h-full` 回头去问一个由内容决定的高度,等于没写。
 *
 *    这里给的是**下限高度 + 居中**,不是真的撑满剩余空间 —— 这一条是踩出来的:让那一节吃掉
 *    整列高度(给堆叠加 `content-stretch`)确实把空态摆到了正中,但**有内容的页面一起被拉开了**:
 *    转写模型那四张卡片被撑成整屏高。行拉伸分不清"这一节空着"和"这一节有东西",而分节堆叠
 *    本来就该把各节顶到上面。所以代价只能由空态自己付:给一段足够大的高度,在里面居中。
 *
 * 2. **用 section 那一档尺寸。** 见 EmptyState 的说明:整页那一档在设置页里比节标题还重。
 */
export function SettingsEmpty({ className, ...props }: React.ComponentProps<typeof EmptyState>) {
  return (
    <div
      data-slot="settings-empty"
      className={cn("grid min-h-[clamp(280px,52vh,520px)] place-content-center place-items-center", className)}
    >
      <EmptyState size="section" {...props} />
    </div>
  );
}

/** Block 内的小标题不自带外边距；它与后续内容的距离由 SettingsBlock 的 gap 统一控制。 */
export function SettingsBlockTitle({ className, ...props }: React.ComponentProps<"h3">) {
  return (
    <h3
      data-slot="settings-block-title"
      className={cn("m-0 flex items-center gap-2 text-ui-md font-semibold", className)}
      {...props}
    />
  );
}

/** Flat settings collection: sibling rows are separated without becoming a stack of cards. */
export function SettingsList({
  children,
  className,
  scrollable = false,
  ...rest
}: {
  children: React.ReactNode;
  className?: string;
  scrollable?: boolean;
  /* 转交其余属性(`aria-busy`、`data-*`…)。**不转交的话它们会被静默吃掉** —— TypeScript 对
     带连字符的 JSX 属性豁免多余属性检查,于是 `<SettingsList aria-busy>` 编译通过、运行时
     什么也没发生,读屏一无所知。写了等于没写是这个仓库一直在消灭的那种沉默。 */
} & Omit<React.ComponentProps<"div">, "className" | "children">) {
  return (
    <div
      data-slot="settings-list"
      className={cn(
        "grid divide-y divide-divider",
        scrollable && "max-h-80 overflow-y-auto overscroll-contain [scrollbar-gutter:stable]",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

/** Pure list section: list rows own the vertical edge spacing, so no outer block padding is added. */
export function SettingsListBlock({
  children,
  className,
  toolbar,
}: {
  children: React.ReactNode;
  className?: string;
  toolbar?: React.ReactNode;
}) {
  return (
    <div data-slot="settings-list-block" className={cn("grid min-h-0 gap-1.5", className)}>
      {toolbar && (
        <div data-slot="settings-list-toolbar" className="px-0.5 pt-3">
          {toolbar}
        </div>
      )}
      <SettingsList>{children}</SettingsList>
    </div>
  );
}

export function SettingsListItem({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="settings-list-item" className={cn("px-0.5 py-5", className)} {...props} />;
}

/**
 * 各节之间画一条分割线,而不是把每一节裹成一张卡片。
 *
 * **线由 CSS 的相邻兄弟画,不由 JS 数第几个孩子。** 此前是「index > 0 就先插一条 Separator」——
 * 而"孩子"不等于"节":数据与诊断那一页在这里放了一个 AlertDialog(它走 portal,行内什么都不渲染),
 * 于是页面末尾多出一条**底下什么都没有的横线**。同类的还有 `{cond && <Group/>}` 里那个 false、
 * 以及任何顺手塞进来的对话框。
 *
 * 换成 `[data-slot=settings-group] + [data-slot=settings-group]`:只有真的画出来的两节相邻时
 * 才有线,portal 和 false 天然不参与。间距也照旧 —— 线紧贴上一节(mt-3),下面留 pt-7 给下一节的
 * 标题;不用 my-*,那会和上一节最后一行的内边距叠起来,看着上窄下宽。
 */
export function SettingsSectionStack({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      data-slot="settings-section-stack"
      className={cn(
        "grid h-full min-h-0 content-start",
        "[&>[data-slot=settings-group]+[data-slot=settings-group]]:mt-3 [&>[data-slot=settings-group]+[data-slot=settings-group]]:border-t [&>[data-slot=settings-group]+[data-slot=settings-group]]:border-divider [&>[data-slot=settings-group]+[data-slot=settings-group]]:pt-7",
        "[&>[data-slot=settings-group]:first-child_[data-slot=settings-group-description]]:text-ui-md [&>[data-slot=settings-group]:first-child_[data-slot=settings-group-title]]:text-2xl [&>[data-slot=settings-group]:first-child_[data-slot=settings-group-title]]:font-semibold [&>[data-slot=settings-group]:only-child]:h-full [&>[data-slot=settings-group]:only-child]:min-h-0 [&>[data-slot=settings-group]:only-child]:grid-rows-[auto_minmax(0,1fr)]",
        className,
      )}
    >
      {children}
    </div>
  );
}


/**
 * 一个表单字段:标签 + 说明 + 控件。
 *
 * 抽出来是因为那串 `[&>span]:… [&_small]:…` 在每个 label 上抄了一遍 —— 抄到第三遍时,
 * 三处的字号已经开始各说各的。
 */
export function SettingsField({
  label,
  description,
  className,
  children,
}: {
  label: string;
  description?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <label data-slot="settings-field" className={cn("grid min-w-0 gap-1.5", className)}>
      <span className="text-ui-md font-medium leading-relaxed text-foreground">{label}</span>
      {description && <small className="text-ui-sm leading-[1.5] text-muted-foreground">{description}</small>}
      {children}
    </label>
  );
}

/** 表单负责占满设置内容列；字段是否并排由调用方按信息关系显式组织。 */
export function SettingsForm({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div data-slot="settings-form" className={cn("grid w-full gap-5", className)}>{children}</div>;
}
