import { CANVAS_WINDOW_SURFACE_CLASS } from "@/components/app/canvasPanelLayout";
import React from "react";
import { NodeToolbar, Position } from "@xyflow/react";
import { ArrowUp, AudioLines, Loader2 } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { listTtsEngines, listTtsVoices, listVoices, type BoardItem, type Voice } from "@/api/client";
import { compactSpeechEngineChoices } from "@/features/voice/speechEngines";
import { OptionPicker } from "@/components/ui/option-picker";
import { useSubmitting } from "@/features/boards/useSubmitting";
import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";
import { BOARD_NODE_PANEL_OFFSET } from "@/features/boards/boardLayout";
import { isImeKeystroke } from "@/lib/shortcuts";

/**
 * 音频节点的「念出来」面板。
 *
 * **音频在这个应用里不是「生成」能力,是 TTS。** 出图出片选的是生成模型,而念一段字选的是
 * **音色** —— 硬塞进图片/视频那张描述符驱动的表单里,会长出一个永远没有比例、没有时长、
 * 参数栏全空的怪东西。
 *
 * 上游便签的文字**直接就是要念的内容**:一张写好的文案连过来,用户的意思就是「念这个」,
 * 让他再抄一遍那条线就白连了。
 *
 * **音色不等于「克隆出来的音色」。** 这里一度只列工作区配音库里的克隆音色,于是一台没克隆过
 * 任何嗓子的机器打开这张卡片,看到的是「还没有可用的音色」—— 而 Edge 有十几个免费内置音色,
 * 不要密钥、不用配置。后端念字的表单(producers.SpeakForm)早就同时收 voice_id 和 engine/engine_voice 两条路
 * (它的注释写着"两条都要能走"),漏的是这一侧。
 */
/**
 * 紧凑工具行里的选择器。底色、焦点环、内边距全由触发器这一个盒子出 —— 和视频卡片同一套。
 *
 * **高度由调用点给**,不写在这里:「同一行的控件一样高」是那一行的决定,而这个组件不知道自己
 * 会被摆进哪一行。design/controlRhythm 那条棘轮也正是按调用点读的 —— 把高度藏进来,它就只能
 * 按 `Pick` 的默认档(40px)猜,于是要么误报、要么把真参差放过去。
 */
function Pick({
  value,
  onChange,
  options,
  ariaLabel,
  icon,
  className,
}: {
  value: string;
  onChange: (next: string) => void;
  options: { value: string; label: string }[];
  ariaLabel: string;
  icon?: React.ReactNode;
  className: string;
}) {
  if (options.length === 0) return null;
  return (
    <OptionPicker
      value={value}
      onChange={onChange}
      options={options}
      ariaLabel={ariaLabel}
      icon={icon}
      className={cn(
        "w-auto max-w-[min(11rem,40%)] gap-1 border-0 bg-transparent px-1.5 text-ui-2xs text-muted-foreground shadow-none transition-colors hover:bg-secondary data-[state=open]:text-foreground",
        className,
      )}
      contentClassName="max-w-[min(360px,calc(100vw-16px))]"
    />
  );
}

export function AudioComposer({
  item,
  busy,
  workspaceId,
  upstreamText,
  onSpeak,
  onFormChange,
}: {
  item: BoardItem;
  busy: boolean;
  workspaceId: string;
  /** 上游便签给的文字 —— 念的就是它。 */
  upstreamText?: string;
  onSpeak: (input: { text: string; voiceId: string; engine: string; engineVoice: string }) => void;
  onFormChange: (form: NonNullable<BoardItem["form"]>) => void;
}) {
  const t = useI18n();
  const [text, setText] = React.useState(item.form?.prompt ?? upstreamText ?? "");
  const [picked, setPicked] = React.useState(item.form?.voice_id ?? "");
  //: 空串 = 还没挑过,由拉回来的引擎列表定第一个;`clone` 走配音库,其余走引擎自己的音色目录。
  const [engine, setEngine] = React.useState(item.form?.engine ?? "");
  const [engineVoice, setEngineVoice] = React.useState(item.form?.engine_voice ?? "");

  //: 上游的字变了就跟着换 —— 但不覆盖用户自己改过的(和便签那条同一个道理)。
  const filled = React.useRef(upstreamText ?? "");
  React.useEffect(() => {
    const next = upstreamText ?? "";
    if (!next || next === filled.current) return;
    setText((current) => (current.trim() === "" || current === filled.current ? next : current));
    filled.current = next;
  }, [upstreamText]);

  const engines = useQuery({ queryKey: ["tts-engines"], queryFn: listTtsEngines, staleTime: 30_000 });
  //: 这一行只有一个下拉,所以只摆报得出音色清单的引擎 —— 理由见 compactSpeechEngineChoices。
  const engineChoices = compactSpeechEngineChoices(engines.data);
  const activeEngine = engineChoices.find((one) => one.id === engine) ?? engineChoices[0] ?? null;
  const usingClone = (activeEngine?.id ?? "clone") === "clone";

  const voices = useQuery({
    queryKey: ["voices", workspaceId],
    queryFn: () => listVoices(workspaceId),
    enabled: usingClone,
  });
  //: 发音人按引擎现拉 —— 火山的目录跟着账号走,不是引擎列表的一部分(和字幕面板同源)。
  const engineVoices = useQuery({
    queryKey: ["tts-voices", activeEngine?.id ?? ""],
    queryFn: () => listTtsVoices(activeEngine?.id ?? ""),
    enabled: Boolean(activeEngine) && !usingClone,
  });

  const cloneOptions = voices.data ?? [];
  const current = cloneOptions.find((one: Voice) => one.id === picked) ?? cloneOptions[0] ?? null;
  const engineVoiceChoices = engineVoices.data ?? [];
  const activeEngineVoice =
    engineVoiceChoices.find((one) => one.value === engineVoice) ?? engineVoiceChoices[0] ?? null;

  //: 能不能念:克隆要有一把嗓子,引擎要有一个发音人。
  const ready = usingClone ? Boolean(current) : Boolean(activeEngineVoice);

  const serializedForm = JSON.stringify({
    prompt: text,
    voice_id: usingClone ? (current?.id ?? item.form?.voice_id ?? "") : "",
    engine: usingClone ? "" : (activeEngine?.id ?? ""),
    engine_voice: usingClone ? "" : (activeEngineVoice?.value ?? ""),
  });
  const lastSavedForm = React.useRef(JSON.stringify(item.form ?? {}));
  React.useEffect(() => {
    if (serializedForm === lastSavedForm.current) return;
    lastSavedForm.current = serializedForm;
    onFormChange(JSON.parse(serializedForm) as NonNullable<BoardItem["form"]>);
  }, [serializedForm, onFormChange]);

  //: 点下去立刻转、落地就停(**失败也要停** —— 否则那个圈会一直转下去)。见 useSubmitting。
  const { submitting, run } = useSubmitting();
  const working = submitting || busy;

  const send = () => {
    const body = text.trim();
    if (!body || working || !ready) return;
    run(() =>
      onSpeak({
        text: body,
        voiceId: usingClone ? (current?.id ?? "") : "",
        engine: usingClone ? "" : (activeEngine?.id ?? ""),
        engineVoice: usingClone ? "" : (activeEngineVoice?.value ?? ""),
      }),
    );
  };

  return (
    <NodeToolbar nodeId={item.id} isVisible position={Position.Bottom} offset={BOARD_NODE_PANEL_OFFSET}>
      <div className={cn(CANVAS_WINDOW_SURFACE_CLASS, "nodrag nopan w-[420px] p-2")}>
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (isImeKeystroke(event)) return;
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              send();
            }
          }}
          rows={3}
          placeholder={t("boardSpeakPlaceholder")}
          className="nowheel w-full resize-none border-0 bg-transparent px-1.5 py-1 text-ui-sm leading-relaxed text-foreground outline-none placeholder:text-muted-foreground"
        />
        <div className="flex items-center gap-1 border-t border-border pt-1.5">
          {engineChoices.length === 0 ? (
            // 一个引擎都没有时说清楚 —— 给一个点了没反应的按钮比什么都不给更糟。
            <span className="px-1 text-ui-2xs text-muted-foreground">{t("boardNoVoices")}</span>
          ) : (
            <>
              {/* 图标画在触发器**里面**,箭头不藏:这一排和视频卡片的模型选择器是同一类控件,
                  看起来就该一样。包一层外壳只负责 hover 的写法会让悬停和聚焦高亮出两个不同
                  大小的框,而 `[&>svg]:hidden` 会让这一格看起来根本不像个下拉。 */}
              <Pick
                className="h-7"
                ariaLabel={t("subtitleDubEngine")}
                icon={<AudioLines size={12} className="shrink-0 text-muted-foreground" />}
                value={activeEngine?.id ?? ""}
                onChange={(next) => {
                  setEngine(next);
                  //: 换了引擎,上一把嗓子多半不在新目录里 —— 清掉,让它重新落在第一个。
                  setEngineVoice("");
                }}
                /* label 后端已按 Accept-Language 翻好(routes/voices.py 的 translate_fields),别再过一次 t()。 */
                options={engineChoices.map((one) => ({ value: one.id, label: one.label }))}
              />
              {usingClone ? (
                cloneOptions.length === 0 ? (
                  // 克隆库空着不等于"没有音色可用" —— 上面那个下拉里还有别的引擎。
                  <span className="px-1 text-ui-2xs text-muted-foreground">{t("boardNoVoices")}</span>
                ) : (
                  /* 音色一多自动带搜索 —— 一个供应商挂几十个音色是常态,滚着找「若曦」不现实。 */
                  <Pick
                    className="h-7"
                    ariaLabel={t("subtitleDubVoice")}
                    value={current?.id ?? ""}
                    onChange={setPicked}
                    options={cloneOptions.map((one: Voice) => ({ value: one.id, label: one.name }))}
                  />
                )
              ) : (
                <Pick
                  className="h-7"
                  ariaLabel={t("subtitleDubVoice")}
                  value={activeEngineVoice?.value ?? ""}
                  onChange={setEngineVoice}
                  options={engineVoiceChoices.map((one) => ({ value: one.value, label: one.label }))}
                />
              )}
            </>
          )}
          <button
            type="button"
            aria-label={t("boardSpeak")}
            title={`${t("boardSpeak")}  ⌘↵`}
            disabled={!text.trim() || !ready || working}
            onClick={send}
            className={cn(
              "ml-auto grid h-7 w-7 shrink-0 place-items-center rounded-full transition-colors",
              !text.trim() || !ready || working
                ? "cursor-not-allowed bg-secondary text-muted-foreground"
                : "cursor-pointer bg-action text-action-foreground hover:opacity-90",
            )}
          >
            {working ? <Loader2 size={13} className="animate-spin" /> : <ArrowUp size={13} />}
          </button>
        </div>
      </div>
    </NodeToolbar>
  );
}
