import type { Board, BoardItem } from "@/api/client";
import { errorText } from "@/api/errorMessage";

export interface NoteWriteInput {
  itemId: string;
  prompt: string;
  providerProfileId: string;
  model: string;
  assets: string[];
  context: string[];
}

/**
 * 写字也有完整的节点生命周期。
 *
 * 请求同步返回(服务端在请求里把写字任务跑完,见后端 write_on_board),但 loading / success /
 * failure 属于节点,而不是提交按钮。服务端返回的节点是最终事实；fallback 只防御一次不完整响应。
 */
export async function runNoteWrite({
  input,
  request,
  patch,
}: {
  input: NoteWriteInput;
  request: () => Promise<Board>;
  patch: (itemId: string, next: Partial<BoardItem>) => void;
}): Promise<Board> {
  patch(input.itemId, {
    run: { status: "running" },
  });

  try {
    const board = await request();
    const written = board.canvas.items.find((one) => one.id === input.itemId);
    patch(input.itemId, {
      ...(written?.text !== undefined ? { text: written.text } : {}),
      form: written?.form ?? {
        prompt: "",
        provider_profile_id: input.providerProfileId,
        model: input.model,
        mentioned_asset_ids: [],
      },
      run: written?.run ?? { status: "succeeded" },
    });
    return board;
  } catch (error) {
    const message = errorText(error);
    patch(input.itemId, {
      run: { status: "failed", error: message },
    });
    throw error;
  }
}
