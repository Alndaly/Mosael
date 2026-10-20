// 「转写模型」的默认那一层 —— 管理 → 引擎 → 转写模型。
// 五张卡本身的名字/说明在 aiStudio.ts(asrModels*);这里放「默认」这一个动作的文案。
export const transcription = {
  asrDefaultHint:
    "已经装在盘上的模型可以设为这台机器的默认 —— 在下面那一行里选,转写默认就用它。语音对话里的「说话输入用哪一家」是按用途的覆盖,留空就回到这里。",
  asrModelIsDefault: "默认模型",
  //: 还没设过默认时,那个选择器里说的是接下来会怎样:按自动挑(见 domain/asr.resolve_asr_model)。
  asrDefaultAuto: "自动(还没设默认)",
} as const;
