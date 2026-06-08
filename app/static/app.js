const toast = document.getElementById("toast");

function showToast(message) {
  toast.textContent = message;
  toast.hidden = false;
  setTimeout(() => { toast.hidden = true; }, 3500);
}

async function postJson(url, payload = undefined) {
  const response = await fetch(url, {
    method: "POST",
    headers: payload ? {"Content-Type": "application/json"} : {},
    body: payload ? JSON.stringify(payload) : undefined,
  });
  if (!response.ok) throw new Error(await responseText(response));
  return response.json();
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(await responseText(response));
  return response.json();
}

async function responseText(response) {
  const text = await response.text();
  try {
    const payload = JSON.parse(text);
    return payload.detail || payload.message || text;
  } catch (_) {
    return text;
  }
}

document.querySelectorAll("[data-task]").forEach((button) => {
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const payload = await postJson(`/tasks/${button.dataset.task}`);
      showToast(JSON.stringify(payload));
      setTimeout(() => window.location.reload(), 600);
    } catch (error) {
      showToast(error.message);
    } finally {
      button.disabled = false;
    }
  });
});

document.querySelectorAll("[data-logout]").forEach((button) => {
  button.addEventListener("click", async () => {
    await postJson("/api/auth/logout");
    window.location.href = "/login";
  });
});

const loginForm = document.getElementById("login-form");
if (loginForm) {
  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(loginForm);
    try {
      await postJson("/api/auth/login", {password: formData.get("password")});
      window.location.href = "/";
    } catch (error) {
      showToast(error.message);
    }
  });
}

const setupPasswordForm = document.getElementById("setup-password-form");
if (setupPasswordForm) {
  setupPasswordForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(setupPasswordForm);
    const password = String(formData.get("password") || "");
    const confirmPassword = String(formData.get("confirm_password") || "");
    if (password !== confirmPassword) {
      showToast("两次输入的密码不一致");
      return;
    }
    try {
      await postJson("/api/auth/setup-password", {password});
      window.location.href = "/";
    } catch (error) {
      showToast(error.message);
    }
  });
}

document.querySelectorAll("[data-approve]").forEach((button) => {
  button.addEventListener("click", async () => {
    await postJson(`/api/signals/${button.dataset.approve}/approve`);
    window.location.reload();
  });
});

document.querySelectorAll("[data-reject]").forEach((button) => {
  button.addEventListener("click", async () => {
    await postJson(`/api/signals/${button.dataset.reject}/reject`);
    window.location.reload();
  });
});

const riskForm = document.getElementById("risk-form");
if (riskForm) {
  riskForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(riskForm);
    const payload = {};
    for (const [key, value] of formData.entries()) {
      payload[key] = key.includes("positions") || key.includes("days") ? Number.parseInt(value, 10) : Number.parseFloat(value);
    }
    await postJson("/api/risk", payload);
    showToast("风控参数已保存");
  });
}

document.querySelectorAll("[data-opend-action]").forEach((button) => {
  button.addEventListener("click", async () => {
    await runOpenDAction(button, `/api/opend/${button.dataset.opendAction}`);
  });
});

document.querySelectorAll("[data-opend-refresh]").forEach((button) => {
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const payload = await getJson("/api/opend/status");
      renderOpenDStatus(payload);
      showToast(payload.message || "OpenD 状态已刷新");
    } catch (error) {
      showToast(error.message);
    } finally {
      button.disabled = false;
    }
  });
});

const openDConfigForm = document.getElementById("opend-config-form");
if (openDConfigForm) {
  openDConfigForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(openDConfigForm);
    const payload = {
      login_account: String(formData.get("login_account") || ""),
      login_password: String(formData.get("login_password") || ""),
      trd_unlock_password: String(formData.get("trd_unlock_password") || ""),
    };
    await runOpenDAction(openDConfigForm.querySelector("button"), "/api/opend/configure", payload);
    openDConfigForm.querySelectorAll("input[type='password']").forEach((input) => { input.value = ""; });
  });
}

const phoneCodeForm = document.getElementById("opend-phone-code-form");
if (phoneCodeForm) {
  phoneCodeForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(phoneCodeForm);
    await runOpenDAction(phoneCodeForm.querySelector("button"), "/api/opend/verify-code", {
      kind: "phone",
      code: String(formData.get("code") || ""),
    });
    phoneCodeForm.reset();
  });
}

const captchaCodeForm = document.getElementById("opend-captcha-code-form");
if (captchaCodeForm) {
  captchaCodeForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(captchaCodeForm);
    await runOpenDAction(captchaCodeForm.querySelector("button"), "/api/opend/verify-code", {
      kind: "captcha",
      code: String(formData.get("code") || ""),
    });
    captchaCodeForm.reset();
  });
}

async function runOpenDAction(button, url, payload = undefined) {
  if (button) button.disabled = true;
  try {
    const result = await postJson(url, payload);
    renderOpenDStatus(result);
    showToast(result.message || "OpenD 操作已完成");
  } catch (error) {
    showToast(error.message);
  } finally {
    if (button) button.disabled = false;
  }
}

function renderOpenDStatus(payload) {
  const message = document.getElementById("opend-message");
  const status = document.getElementById("opend-status");
  if (message) message.textContent = payload.message || "";
  if (!status) return;
  const socketConnected = payload.socket_health && payload.socket_health.connected;
  status.innerHTML = `
    <dl class="metric-grid">
      <div><dt>安装状态</dt><dd>${payload.installed ? "已安装" : "未安装"}</dd></div>
      <div><dt>服务状态</dt><dd>${escapeHtml(payload.service_active || "unknown")}</dd></div>
      <div><dt>API 端口</dt><dd>${payload.api_port_open ? "开放" : "关闭"}</dd></div>
      <div><dt>Telnet 端口</dt><dd>${payload.telnet_port_open ? "开放" : "关闭"}</dd></div>
      <div><dt>登录配置</dt><dd>${payload.credentials_configured ? "已配置" : "未配置"}</dd></div>
      <div><dt>后端连接</dt><dd>${socketConnected ? "已连接" : "未连接"}</dd></div>
    </dl>
    <pre class="log-box">${escapeHtml(payload.telnet_reply || payload.recent_log || "暂无 OpenD 日志。")}</pre>
  `;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
