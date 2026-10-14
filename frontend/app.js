const DEFAULT_TOKEN = "demo-panel-token";

const state = {
  socket: null,
  sessionReady: false,
  sessionId: null,
  token: localStorage.getItem("ai-agent-token") || DEFAULT_TOKEN,
  theme: localStorage.getItem("ai-agent-theme") || "dark",
  messages: [],
  approvals: [],
  history: [],
  sessionRetrying: false,
  sessionRetryCount: 0,
};

const elements = {
  loginPanel: document.getElementById("loginPanel"),
  loginForm: document.getElementById("loginForm"),
  accessToken: document.getElementById("accessToken"),
  messages: document.getElementById("messages"),
  commandInput: document.getElementById("commandInput"),
  sendButton: document.getElementById("sendButton"),
  approvalsList: document.getElementById("approvalsList"),
  historyList: document.getElementById("historyList"),
  statusBadge: document.getElementById("statusBadge"),
  sessionBadge: document.getElementById("sessionBadge"),
  connectionDot: document.getElementById("connectionDot"),
  connectionText: document.getElementById("connectionText"),
  agentText: document.getElementById("agentText"),
  workingState: document.getElementById("workingState"),
  busyBanner: document.getElementById("busyBanner"),
  themeToggle: document.getElementById("themeToggle"),
};

function applyTheme(theme) {
  state.theme = theme;
  localStorage.setItem("ai-agent-theme", theme);
  document.documentElement.setAttribute("data-theme", theme);
  elements.themeToggle.textContent = theme === "dark" ? "Light Mode" : "Dark Mode";
}

function setStatus(text, kind = "default") {
  elements.statusBadge.textContent = text;
  elements.workingState.textContent = text;
  elements.busyBanner.classList.toggle("hidden", kind !== "working");
  if (kind === "working") {
    elements.busyBanner.textContent = text;
  }
}

function setConnection(online, text) {
  elements.connectionDot.classList.toggle("online", online);
  elements.connectionDot.classList.toggle("offline", !online);
  elements.connectionText.textContent = online ? "Bağlı" : "Bağlantı yok";
  elements.agentText.textContent = text || (online ? "Agent hazır" : "Agent bekleniyor");
}

function addMessage(role, content, meta = {}) {
  const item = document.createElement("article");
  item.className = `message ${role}`;
  const title = document.createElement("strong");
  title.textContent = meta.title || (role === "user" ? "Sen" : role === "assistant" ? "AI" : "Durum");
  const body = document.createElement("div");
  body.textContent = content;
  item.append(title, body);
  elements.messages.appendChild(item);
  elements.messages.scrollTop = elements.messages.scrollHeight;
  state.messages.push({ role, content, meta, createdAt: new Date().toISOString() });
}

function renderApprovals() {
  elements.approvalsList.innerHTML = "";
  if (state.approvals.length === 0) {
    const empty = document.createElement("div");
    empty.className = "history-item";
    empty.textContent = "Bekleyen işlem yok.";
    elements.approvalsList.appendChild(empty);
    return;
  }

  for (const approval of state.approvals) {
    const item = document.createElement("div");
    item.className = "approval-item";
    item.innerHTML = `
      <strong>${approval.command}</strong>
      <div>${approval.reason}</div>
      <div><span class="badge ghost">Risk: ${approval.risk}</span></div>
    `;
    const actions = document.createElement("div");
    actions.className = "approval-actions";

    const approveButton = document.createElement("button");
    approveButton.className = "primary";
    approveButton.textContent = "Onayla";
    approveButton.onclick = () => sendApproval(approval.approval_id, true, "Kullanıcı onayladı");

    const rejectButton = document.createElement("button");
    rejectButton.className = "secondary";
    rejectButton.textContent = "İptal";
    rejectButton.onclick = () => sendApproval(approval.approval_id, false, "Kullanıcı reddetti");

    actions.append(approveButton, rejectButton);
    item.appendChild(actions);
    elements.approvalsList.appendChild(item);
  }
}

function renderHistory(tasks) {
  elements.historyList.innerHTML = "";
  if (!tasks || tasks.length === 0) {
    const empty = document.createElement("div");
    empty.className = "history-item";
    empty.textContent = "Henüz işlem geçmişi yok.";
    elements.historyList.appendChild(empty);
    return;
  }

  const sorted = [...tasks].sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
  for (const task of sorted.slice(0, 20)) {
    const item = document.createElement("div");
    item.className = "history-item";
    item.innerHTML = `
      <strong>${task.message}</strong>
      <div>${task.summary || task.status}</div>
      <div class="muted">${task.status} • ${new Date(task.updated_at).toLocaleString()}</div>
    `;
    elements.historyList.appendChild(item);
  }
}

function syncState(payload) {
  setConnection(Boolean(payload.agent_connected), payload.agent_name || "Agent bekleniyor");
  state.approvals = Array.isArray(payload.approvals) ? payload.approvals.filter((item) => item.approved !== true) : [];
  state.history = Array.isArray(payload.tasks) ? payload.tasks : [];
  renderApprovals();
  renderHistory(state.history);
}

async function login(token) {
  const normalizedToken = (token || state.token || DEFAULT_TOKEN).trim();
  state.token = normalizedToken;
  localStorage.setItem("ai-agent-token", normalizedToken);

  const response = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: normalizedToken }),
    credentials: "include",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "Giriş başarısız");
  }
  const data = await response.json();
  state.sessionReady = true;
  state.sessionId = data.session_id;
  state.sessionRetrying = false;
  state.sessionRetryCount = 0;
  elements.sessionBadge.textContent = `Oturum: ${data.session_id.slice(0, 8)}`;
  elements.loginPanel.classList.add("hidden");
  connectSocket();
  setStatus("Bağlandı", "default");
  await refreshState();
}

async function refreshState() {
  const response = await fetch("/api/state", { credentials: "include" });
  if (!response.ok) {
    return;
  }
  const data = await response.json();
  syncState(data);
}

function connectSocket() {
  if (!state.sessionReady || !state.sessionId) {
    return;
  }
  if (state.socket && state.socket.readyState === WebSocket.OPEN) {
    return;
  }
  const base = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/frontend`;
  const socket = new WebSocket(state.sessionId ? `${base}?session_id=${encodeURIComponent(state.sessionId)}` : base);
  state.socket = socket;

  socket.onopen = () => {
    setStatus("Bağlandı", "default");
  };

  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "state") {
      syncState(message.payload);
      return;
    }
    if (message.type === "status") {
      const text = message.payload?.text || "Durum güncellendi";
      addMessage("status", text, { title: "Sistem" });
      setStatus(text, message.payload?.level === "info" ? "working" : "default");
      return;
    }
    if (message.type === "message") {
      const content = message.payload?.content || "";
      addMessage(message.payload?.role === "user" ? "user" : "assistant", content, { title: message.payload?.role === "user" ? "Sen" : "AI" });
      return;
    }
    if (message.type === "task_update") {
      renderHistory([...(state.history || []).filter((task) => task.task_id !== message.payload.task_id), message.payload]);
      state.history = [...(state.history || []).filter((task) => task.task_id !== message.payload.task_id), message.payload];
      setStatus(message.payload.summary || message.payload.status, message.payload.status === "running" ? "working" : "default");
      if (message.payload.status === "running") {
        addMessage("status", `İşlem sürüyor: ${message.payload.summary || message.payload.message}`, { title: "İşlem" });
      }
      return;
    }
    if (message.type === "task_finished") {
      const finalTask = message.payload;
      renderHistory([...(state.history || []).filter((task) => task.task_id !== finalTask.task_id), finalTask]);
      state.history = [...(state.history || []).filter((task) => task.task_id !== finalTask.task_id), finalTask];
      setStatus(finalTask.summary || finalTask.status, "default");
      addMessage("status", `İşlem tamamlandı: ${finalTask.summary || finalTask.status}`, { title: "İşlem" });
      return;
    }
    if (message.type === "approval_request") {
      state.approvals = [message.payload, ...state.approvals.filter((item) => item.approval_id !== message.payload.approval_id)];
      renderApprovals();
      addMessage("status", `Onay gerekli: ${message.payload.command}`, { title: "Onay" });
      setStatus("Onay bekleniyor", "working");
      return;
    }
    if (message.type === "approval_resolved") {
      state.approvals = state.approvals.filter((item) => item.approval_id !== message.payload.approval_id);
      renderApprovals();
      addMessage("status", message.payload.approved ? "İşlem onaylandı" : "İşlem reddedildi", { title: "Onay" });
      return;
    }
  };

  socket.onclose = (event) => {
    const staleSession = event && (event.code === 4401 || event.code === 1008 || event.code === 1006 || /session|authentication|forbidden|unauthorized/i.test(event.reason || ""));
    setConnection(false, staleSession ? "Oturum geçersiz" : "Bağlantı koptu");
    setStatus(staleSession ? "Yeniden giriş gerekli" : "Yeniden bağlanıyor...");

    state.socket = null;
    if (staleSession) {
      state.sessionReady = false;
      state.sessionId = null;
      state.sessionRetrying = false;
      state.sessionRetryCount = 0;
      elements.loginPanel.classList.remove("hidden");
      setStatus("Oturum geçersiz, lütfen tekrar giriş yapın", "default");
      return;
    }

    if (state.sessionReady) {
      state.sessionReady = false;
      setTimeout(() => {
        if (!state.sessionReady && !state.sessionRetrying && state.sessionId) {
          connectSocket();
        }
      }, 1500);
    }
  };

  socket.onerror = () => {
    setConnection(false, "WebSocket hatası");
  };
}

function sendMessage(message) {
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) {
    addMessage("status", "WebSocket bağlı değil", { title: "Hata" });
    return;
  }
  state.socket.send(JSON.stringify({ type: "chat_message", message }));
  addMessage("user", message);
  setStatus("Çalışıyor...", "working");
}

function sendApproval(approvalId, approved, note) {
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) {
    return;
  }
  state.socket.send(JSON.stringify({ type: "approval_decision", approval_id: approvalId, approved, note }));
}

elements.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await login(elements.accessToken.value.trim());
  } catch (error) {
    addMessage("status", error.message, { title: "Giriş hatası" });
  }
});

elements.sendButton.addEventListener("click", () => {
  const message = elements.commandInput.value.trim();
  if (!message) {
    return;
  }
  elements.commandInput.value = "";
  sendMessage(message);
});

elements.commandInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.sendButton.click();
  }
});

elements.themeToggle.addEventListener("click", () => {
  applyTheme(state.theme === "dark" ? "light" : "dark");
});

applyTheme(state.theme);
renderApprovals();
renderHistory([]);
setStatus("Oturum açın");
setConnection(false, "Agent bekleniyor");
if (state.token) {
  login(state.token).catch(() => {
    setStatus("Oturum açın");
  });
}
