export interface StreamEvent {
  type: "content_block_start" | "content_block_delta" | "content_block_stop" | "message_start" | "message_delta" | "message_stop" | "ping" | "error";
  index?: number;
  content_block?: {
    type: "text" | "tool_use";
    id?: string;
    name?: string;
    text?: string;
  };
  delta?: {
    type?: string;
    text?: string;
    partial_json?: string;
    stop_reason?: string;
  };
  message?: {
    id: string;
    role: string;
    model: string;
  };
  error?: {
    type: string;
    message: string;
  };
}

export async function* parseSSEStream(
  reader: ReadableStreamDefaultReader<Uint8Array>
): AsyncGenerator<StreamEvent> {
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const data = line.slice(6).trim();
        if (data === "[DONE]") return;
        try {
          yield JSON.parse(data) as StreamEvent;
        } catch {
          // skip malformed events
        }
      }
    }
  }
}
