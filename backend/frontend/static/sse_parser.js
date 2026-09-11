// Pure SSE-over-fetch parser - no DOM dependencies, so this can be
// unit-tested directly under Node (see sse_parser_test.js) as well as
// loaded in the browser via a plain <script> tag.
//
// /chat/stream is a POST endpoint, so the browser's built-in EventSource
// (GET-only) can't be used. This parses the same "event: X\ndata: Y\n\n"
// wire format by hand from raw decoded text chunks.

function parseSSEBuffer(buffer) {
  const events = [];
  const blocks = buffer.split("\n\n");
  // The last element is either "" (buffer ended exactly on a boundary)
  // or an incomplete trailing block - either way, keep it as the new
  // remainder rather than trying to parse it early.
  const remainder = blocks.pop();

  for (const block of blocks) {
    if (!block.trim()) continue;
    let eventType = "message";
    let dataStr = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) eventType = line.slice(7).trim();
      else if (line.startsWith("data: ")) dataStr += line.slice(6);
    }
    let data = {};
    try {
      data = JSON.parse(dataStr);
    } catch (e) {
      console.error("Failed to parse SSE data as JSON:", dataStr, e);
      continue;
    }
    events.push({ event: eventType, data });
  }

  return { events, remainder };
}

if (typeof module !== "undefined") {
  module.exports = { parseSSEBuffer };
}
