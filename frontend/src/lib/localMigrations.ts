import { migrateModelPreviewBlur } from "@/components/generation/modelPreviewSettings";

/**
 * **本机存的设置**(localStorage)换形状时的迁移,和后端的 `db/migrations.py` 同一个立场:旧形状一次性改成新形状,
 * 代码只认新形状,不留「认不出就按旧的读」的分支。
 *
 * 启动时(渲染之前)按顺序跑一遍。每一步都要**幂等**:没有旧键就什么都不做,迁完删掉旧键。一步失败(存储不可用、
 * 值是坏的)不挡别的步,也不挡应用启动 —— 失败的那一步下次启动再试,设置照缺省值显示。
 */
const STEPS: readonly { id: string; run: (storage: Storage) => void }[] = [
  //: 模型库的「模糊预览图」开关换成预览图分档 + NSFW 单独管(ADR 0038 §9)
  { id: "model-preview-levels", run: migrateModelPreviewBlur },
];

export function runLocalMigrations(storage?: Storage): void {
  let target: Storage;
  try {
    target = storage ?? window.localStorage;
  } catch {
    return; // 隐私模式:没有存储,就没有要迁的
  }
  for (const step of STEPS) {
    try {
      step.run(target);
    } catch (error) {
      console.warn(`local migration ${step.id} failed`, error);
    }
  }
}
