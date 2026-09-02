import type { Board, BoardItem } from "@/api/client";

export interface NoteWriteInput {
  itemId: string;
  prompt: string;
  providerProfileId: string;
  model: string;
  assets: string[];
  context: string[];
}

/**
 * 同步写作也有完整的节点生命周期。
 *
 * 请求本身不需要后台 job，但 loading / success / failure 仍然属于节点，而不是提交按钮。
 * 服务端返回的节点是最终事实；fallback 只防御一次不完整响应。
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
    const message = error instanceof Error ? error.message : String(error);
    patch(input.itemId, {
      run: { status: "failed", error: message },
    });
    throw error;
  }
}
