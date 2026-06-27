(function () {
  "use strict";

  /* ── Configuration from data attributes ──────────────────────────────── */
  var script = document.currentScript;
  var API = script.getAttribute("data-api") || "";
  var TITLE = script.getAttribute("data-title") || "Chat with us";
  var COLOR = script.getAttribute("data-color") || "#2563eb";
  var POSITION = script.getAttribute("data-position") || "right";

  if (!API) {
    console.error("[LeadAgent] data-api attribute is required");
    return;
  }

  /* ── Inject styles ───────────────────────────────────────────────────── */
  var css = `
    #la-launcher{position:fixed;bottom:24px;${POSITION}:24px;width:56px;height:56px;
      border-radius:50%;background:${COLOR};color:#fff;border:none;cursor:pointer;
      box-shadow:0 4px 12px rgba(0,0,0,.25);z-index:99999;display:flex;
      align-items:center;justify-content:center;transition:transform .2s}
    #la-launcher:hover{transform:scale(1.08)}
    #la-launcher svg{width:28px;height:28px;fill:currentColor}
    #la-panel{position:fixed;bottom:92px;${POSITION}:24px;width:380px;max-width:calc(100vw - 32px);
      height:520px;max-height:calc(100vh - 120px);border-radius:16px;background:#fff;
      box-shadow:0 8px 30px rgba(0,0,0,.18);z-index:99999;display:none;flex-direction:column;
      overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
    #la-panel.la-open{display:flex}
    #la-header{background:${COLOR};color:#fff;padding:16px 20px;font-size:15px;font-weight:600;
      display:flex;align-items:center;justify-content:space-between;flex-shrink:0}
    #la-close{background:none;border:none;color:#fff;cursor:pointer;font-size:20px;
      line-height:1;padding:0 0 0 12px}
    #la-messages{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px}
    .la-msg{max-width:85%;padding:10px 14px;border-radius:14px;font-size:14px;
      line-height:1.45;word-wrap:break-word;white-space:pre-wrap}
    .la-msg.la-user{align-self:flex-end;background:${COLOR};color:#fff;border-bottom-right-radius:4px}
    .la-msg.la-bot{align-self:flex-start;background:#f1f3f5;color:#1a1a1a;border-bottom-left-radius:4px}
    .la-msg.la-status{align-self:center;background:none;color:#888;font-size:12px;
      font-style:italic;padding:2px 0}
    #la-input-area{display:flex;border-top:1px solid #e5e7eb;padding:10px 12px;gap:8px;flex-shrink:0}
    #la-input{flex:1;border:1px solid #d1d5db;border-radius:10px;padding:8px 14px;font-size:14px;
      outline:none;resize:none;max-height:80px;font-family:inherit}
    #la-input:focus{border-color:${COLOR}}
    #la-send{background:${COLOR};color:#fff;border:none;border-radius:10px;padding:8px 16px;
      cursor:pointer;font-size:14px;font-weight:500;flex-shrink:0}
    #la-send:disabled{opacity:.5;cursor:default}
    @media(max-width:480px){
      #la-panel{bottom:0;${POSITION}:0;width:100%;max-width:100%;height:100%;max-height:100%;
        border-radius:0}
      #la-launcher{bottom:16px;${POSITION}:16px}
    }
  `;
  var style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  /* ── Build DOM ───────────────────────────────────────────────────────── */
  var launcher = document.createElement("button");
  launcher.id = "la-launcher";
  launcher.setAttribute("aria-label", "Open chat");
  launcher.innerHTML =
    '<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.17L4 17.17V4h16v12z"/></svg>';

  var panel = document.createElement("div");
  panel.id = "la-panel";
  panel.innerHTML =
    '<div id="la-header"><span>' +
    TITLE +
    '</span><button id="la-close" aria-label="Close chat">&times;</button></div>' +
    '<div id="la-messages"></div>' +
    '<div id="la-input-area">' +
    '<textarea id="la-input" placeholder="Type a message…" rows="1"></textarea>' +
    '<button id="la-send" aria-label="Send">Send</button></div>';

  document.body.appendChild(launcher);
  document.body.appendChild(panel);

  var messages = document.getElementById("la-messages");
  var input = document.getElementById("la-input");
  var sendBtn = document.getElementById("la-send");
  var conversationId = null;
  var busy = false;

  /* ── Helpers ─────────────────────────────────────────────────────────── */
  function addMsg(text, cls) {
    var el = document.createElement("div");
    el.className = "la-msg " + cls;
    el.textContent = text;
    messages.appendChild(el);
    messages.scrollTop = messages.scrollHeight;
    return el;
  }

  function setStatus(text) {
    var existing = messages.querySelector(".la-status:last-child");
    if (existing) existing.remove();
    if (text) addMsg(text, "la-status");
  }

  function togglePanel() {
    panel.classList.toggle("la-open");
    if (panel.classList.contains("la-open")) input.focus();
  }

  /* ── Event handlers ──────────────────────────────────────────────────── */
  launcher.addEventListener("click", togglePanel);
  document.getElementById("la-close").addEventListener("click", togglePanel);

  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  sendBtn.addEventListener("click", send);

  input.addEventListener("input", function () {
    this.style.height = "auto";
    this.style.height = Math.min(this.scrollHeight, 80) + "px";
  });

  /* ── Send message via SSE ────────────────────────────────────────────── */
  function send() {
    var text = input.value.trim();
    if (!text || busy) return;

    addMsg(text, "la-user");
    input.value = "";
    input.style.height = "auto";
    busy = true;
    sendBtn.disabled = true;
    setStatus("Thinking…");

    var botEl = null;
    var accumulated = "";

    fetch(API + "/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, conversation_id: conversationId }),
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        var reader = resp.body.getReader();
        var decoder = new TextDecoder();
        var buffer = "";

        function read() {
          return reader.read().then(function (result) {
            if (result.done) {
              finish();
              return;
            }
            buffer += decoder.decode(result.value, { stream: true });
            var lines = buffer.split("\n");
            buffer = lines.pop();

            var currentEvent = "";
            for (var i = 0; i < lines.length; i++) {
              var line = lines[i];
              if (line.startsWith("event: ")) {
                currentEvent = line.substring(7).trim();
              } else if (line.startsWith("data: ")) {
                var data;
                try {
                  data = JSON.parse(line.substring(6));
                } catch (e) {
                  continue;
                }
                handleEvent(currentEvent, data);
              }
            }
            return read();
          });
        }
        return read();
      })
      .catch(function (err) {
        setStatus("");
        addMsg("Connection error. Please try again.", "la-bot");
        finish();
      });

    function handleEvent(event, data) {
      if (event === "session" && data.conversation_id) {
        conversationId = data.conversation_id;
      } else if (event === "status") {
        setStatus(data.content || "");
      } else if (event === "token") {
        setStatus("");
        if (!botEl) {
          botEl = addMsg("", "la-bot");
        }
        accumulated += data.content || "";
        botEl.textContent = accumulated;
        messages.scrollTop = messages.scrollHeight;
      } else if (event === "clear") {
        if (botEl) { botEl.remove(); botEl = null; }
        accumulated = "";
      } else if (event === "replace") {
        setStatus("");
        accumulated = data.content || "";
        if (!botEl) botEl = addMsg("", "la-bot");
        botEl.textContent = accumulated;
      } else if (event === "message") {
        setStatus("");
        addMsg(data.content || "", "la-bot");
      } else if (event === "error") {
        setStatus("");
        addMsg(data.content || "An error occurred.", "la-bot");
      } else if (event === "done") {
        finish();
      }
    }

    function finish() {
      setStatus("");
      busy = false;
      sendBtn.disabled = false;
      input.focus();
    }
  }
})();
