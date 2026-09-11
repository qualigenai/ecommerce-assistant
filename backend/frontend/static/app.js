// Trailhead Outfitters — shopping assistant frontend (Day 14)
// Plain JS, no build step, no framework - see Day 14's tech-stack decision.

const API_BASE = ""; // same-origin, single Render service - see main.py's Day 14 comment.

// parseSSEBuffer() is loaded from sse_parser.js (separate <script> tag in
// index.html, before this file) - kept dependency-free there so it can be
// unit-tested under Node without pulling in DOM globals.

// ---------- State ----------
let sessionId = sessionStorage.getItem("chat_session_id") || null;
let currentBotBubble = null;
let currentStatusBubble = null;
let sending = false;

// ---------- DOM refs ----------
const productGrid = document.getElementById("product-grid");
const chatBody = document.getElementById("chat-body");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const chatSend = document.getElementById("chat-send");
const chatError = document.getElementById("chat-error");
const chatPanel = document.getElementById("chat-panel");
const chatLauncher = document.getElementById("chat-launcher");
const chatClose = document.getElementById("chat-close");
const statusLine = document.getElementById("cw-status-line");

// ---------- Product grid ----------
async function loadProducts() {
  try {
    const res = await fetch(`${API_BASE}/products?limit=12`);
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    const products = await res.json();

    if (!products.length) {
      productGrid.innerHTML = `<div class="empty-state">No products found in the catalog yet.</div>`;
      return;
    }

    productGrid.innerHTML = products.map(renderProductCard).join("");
    productGrid.querySelectorAll(".pcard .add-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const name = btn.dataset.productName;
        sendMessage(`Add 1 ${name} to my cart`);
        openChatOnMobile();
      });
    });
  } catch (err) {
    console.error("Failed to load products:", err);
    productGrid.innerHTML = `<div class="error-state">Couldn't load products right now. Please refresh the page.</div>`;
  }
}

function renderProductCard(p) {
  const stockClass = p.stock <= 10 ? "low" : "in";
  const stockLabel = p.stock <= 10 ? `Low stock &middot; ${p.stock}` : `In stock &middot; ${p.stock}`;
  return `
    <div class="pcard">
      <div class="thumb">Product image</div>
      <div class="name">${escapeHtml(p.name)}</div>
      <div class="price-row">
        <span class="price">$${p.price.toFixed(2)}</span>
        <span class="stock ${stockClass}">${stockLabel}</span>
      </div>
      <button class="add-btn" data-product-name="${escapeHtml(p.name)}">Add to cart</button>
    </div>
  `;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ---------- Chat rendering helpers ----------
function addUserBubble(text) {
  const el = document.createElement("div");
  el.className = "bubble-user";
  el.textContent = text;
  chatBody.appendChild(el);
  scrollChatToBottom();
}

function startBotBubble() {
  const el = document.createElement("div");
  el.className = "bubble-bot";
  el.textContent = "";
  chatBody.appendChild(el);
  currentBotBubble = el;
  scrollChatToBottom();
  return el;
}

function appendToBotBubble(text) {
  if (!currentBotBubble) startBotBubble();
  currentBotBubble.textContent += text;
  scrollChatToBottom();
}

function setStatus(message) {
  clearStatus();
  const el = document.createElement("div");
  el.className = "bubble-status";
  el.textContent = message;
  chatBody.appendChild(el);
  currentStatusBubble = el;
  statusLine.textContent = message;
  scrollChatToBottom();
}

function clearStatus() {
  if (currentStatusBubble) {
    currentStatusBubble.remove();
    currentStatusBubble = null;
  }
}

function addProductCard(product) {
  const el = document.createElement("div");
  el.className = "inline-card";
  el.innerHTML = `
    <div class="thumb"></div>
    <div class="info">
      <div class="name">${escapeHtml(product.name)}</div>
      <div class="price">$${Number(product.price).toFixed(2)}</div>
      <button class="add-btn" data-product-name="${escapeHtml(product.name)}">Add to cart</button>
    </div>
  `;
  el.querySelector(".add-btn").addEventListener("click", (e) => {
    e.target.disabled = true;
    e.target.textContent = "Added";
    sendMessage(`Add 1 ${product.name} to my cart`);
  });
  chatBody.appendChild(el);
  scrollChatToBottom();
}

function showChatError(message) {
  chatError.textContent = message;
  chatError.hidden = false;
}

function clearChatError() {
  chatError.hidden = true;
  chatError.textContent = "";
}

function scrollChatToBottom() {
  chatBody.scrollTop = chatBody.scrollHeight;
}

function setSending(isSending) {
  sending = isSending;
  chatInput.disabled = isSending;
  chatSend.disabled = isSending;
}

// ---------- Streaming chat ----------
async function sendMessage(text) {
  const message = text.trim();
  if (!message || sending) return;

  clearChatError();
  addUserBubble(message);
  setSending(true);
  setStatus("Connecting...");

  const seenProductKeys = new Set(); // avoid duplicate cards within one reply

  try {
    const params = new URLSearchParams({ message });
    if (sessionId) params.set("session_id", sessionId);

    const res = await fetch(`${API_BASE}/chat/stream?${params.toString()}`, {
      method: "POST",
    });

    if (!res.ok) {
      // 400 (sanitize.py) or 429 (rate_limit.py) both return a JSON body
      // with a "detail" field - surface it honestly rather than a
      // generic error.
      let detail = `Request failed (${res.status}).`;
      try {
        const body = await res.json();
        if (body.detail) detail = body.detail;
      } catch (e) { /* body wasn't JSON - keep the generic message */ }
      clearStatus();
      showChatError(detail);
      setSending(false);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    currentBotBubble = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const { events, remainder } = parseSSEBuffer(buffer);
      buffer = remainder;

      for (const evt of events) {
        handleStreamEvent(evt, seenProductKeys);
      }
    }
  } catch (err) {
    console.error("Chat stream error:", err);
    clearStatus();
    showChatError("Lost connection while getting a response. Please try again.");
  } finally {
    clearStatus();
    setSending(false);
  }
}

function handleStreamEvent(evt, seenProductKeys) {
  switch (evt.event) {
    case "session":
      sessionId = evt.data.session_id;
      sessionStorage.setItem("chat_session_id", sessionId);
      break;

    case "status":
      setStatus(evt.data.message);
      break;

    case "token":
      clearStatus();
      appendToBotBubble(evt.data.text);
      break;

    case "tool_call": {
      const results = evt.data.results || [];
      for (const product of results) {
        const key = product.sku || product.id || product.name;
        if (key && !seenProductKeys.has(key)) {
          seenProductKeys.add(key);
          addProductCard(product);
        }
      }
      break;
    }

    case "correction":
      // BUG-011/BUG-013's guard fired - replace whatever was streamed
      // with the honest version, or clear it if a retry is in progress
      // (reply: null means "the last attempt was discarded, a new one
      // is coming").
      if (currentBotBubble) {
        if (evt.data.reply) {
          currentBotBubble.textContent = evt.data.reply;
        } else {
          currentBotBubble.remove();
          currentBotBubble = null;
        }
      }
      break;

    case "done":
      clearStatus();
      // Ensures the bubble's final text always matches the authoritative
      // vetted reply, even in the edge case where no "token" events fired
      // at all (e.g. the hard-fallback path).
      if (!currentBotBubble) startBotBubble();
      currentBotBubble.textContent = evt.data.reply;
      break;
  }
}

// ---------- Mobile chat overlay ----------
function openChatOnMobile() {
  chatPanel.classList.add("open");
}
function closeChatOnMobile() {
  chatPanel.classList.remove("open");
}

// ---------- Wiring ----------
chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = chatInput.value;
  chatInput.value = "";
  sendMessage(text);
});

chatLauncher.addEventListener("click", openChatOnMobile);
chatClose.addEventListener("click", closeChatOnMobile);

loadProducts();
