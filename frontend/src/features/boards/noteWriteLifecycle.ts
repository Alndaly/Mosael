import type { Board, BoardItem, BoardRunRequest } from "@/api/client";
import { errorText } from "@/api/errorMessage";

/** 往一张便签里写字的那一次运行(产出者 write)。 */
export type NoteWriteRun = Extract<BoardRunRequest, { producer: "write" }>;

/**
 * 写字也有完整的节点生命周期。
 *
 * 请求同步返回(服务端在请求里把写字任务跑完,见后端 boards/actions.write_on_board),但 loading / success /
 * failure 属于节点,而不是提交按钮。服务端返回的节点是最终事实；fallback 只防御一次不完整响应。
 */
export async function runNoteWrite({
  run,
  request,
  patch,
}: {
  run: NoteWriteRun;
  /** 发出去(runOnBoard)。 */
  request: () => Promise<Board>;
  patch: (itemId: string, next: Partial<BoardItem>) => void;
}): Promise<Board> {
  patch(run.item_id, {
    run: { status: "running" },
  });

  try {
    const board = await request();
    const written = board.canvas.items.find((one) => one.id === run.item_id);
    patch(run.item_id, {
      ...(written?.text !== undefined ? { text: written.text } : {}),
      form: written?.form ?? {
        prompt: "",
        provider_profile_id: run.form.provider_profile_id,
        model: run.form.model,
        mentioned_asset_ids: [],
        producer: run.producer,
      },
      run: written?.run ?? { status: "succeeded" },
    });
    return board;
  } catch (error) {
    const message = errorText(error);
    patch(run.item_id, {
      run: { status: "failed", error: message },
    });
    throw error;
  }
}
