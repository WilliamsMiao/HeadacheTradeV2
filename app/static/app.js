const toast = document.getElementById("toast");
let toastTimer;

function showToast(message, tone = "default") {
  if (!toast) return;
  window.clearTimeout(toastTimer);
  toast.textContent = message;
  toast.dataset.tone = tone;
  toast.hidden = false;
  toastTimer = window.setTimeout(() => {
    toast.hidden = true;
    toast.dataset.tone = "default";
  }, 4000);
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

function setButtonLoading(button, isLoading) {
  if (!button) return;
  if (isLoading) {
    button.dataset.originalText = button.textContent;
    button.textContent = button.dataset.loadingText || "处理中";
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
  } else {
    button.textContent = button.dataset.originalText || button.textContent;
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }
}

function setFormFeedback(form, message, tone = "") {
  const feedback = form ? form.querySelector("[data-form-feedback]") : null;
  if (!feedback) return;
  feedback.textContent = message;
  feedback.className = `inline-feedback${tone ? ` ${tone}` : ""}`;
}

function taskResultMessage(taskName, payload) {
  const labels = {
    "sync-watchlist": "自选股同步完成",
    "update-market-data": "行情更新完成",
    "compute-indicators": "指标计算完成",
    "run-pipeline": "状态机刷新完成",
    "run-backtest": "复盘生成完成",
  };
  const detail = Object.entries(payload || {})
    .filter(([, value]) => ["string", "number"].includes(typeof value))
    .slice(0, 2)
    .map(([key, value]) => `${key}: ${value}`)
    .join("，");
  return `${labels[taskName] || "任务完成"}${detail ? `。${detail}` : ""}`;
}

document.querySelectorAll("[data-task]").forEach((button) => {
  button.addEventListener("click", async () => {
    setButtonLoading(button, true);
    try {
      const payload = await postJson(`/tasks/${button.dataset.task}`);
      showToast(taskResultMessage(button.dataset.task, payload), "success");
      window.setTimeout(() => window.location.reload(), 800);
    } catch (error) {
      showToast(error.message, "error");
    } finally {
      setButtonLoading(button, false);
    }
  });
});

document.querySelectorAll("[data-logout]").forEach((button) => {
  button.addEventListener("click", async () => {
    setButtonLoading(button, true);
    try {
      await postJson("/api/auth/logout");
      window.location.href = "/login";
    } catch (error) {
      setButtonLoading(button, false);
      showToast(error.message, "error");
    }
  });
});

const navToggle = document.querySelector("[data-nav-toggle]");
const navClose = document.querySelector("[data-nav-close]");

function setNavigationOpen(isOpen) {
  document.body.classList.toggle("nav-open", isOpen);
  if (navToggle) {
    navToggle.setAttribute("aria-expanded", String(isOpen));
    navToggle.setAttribute("aria-label", isOpen ? "关闭导航" : "打开导航");
  }
}

if (navToggle) {
  navToggle.addEventListener("click", () => setNavigationOpen(!document.body.classList.contains("nav-open")));
}

if (navClose) {
  navClose.addEventListener("click", () => setNavigationOpen(false));
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    setNavigationOpen(false);
    document.querySelectorAll("details[open]").forEach((details) => {
      details.removeAttribute("open");
    });
  }
});

const loginForm = document.getElementById("login-form");
if (loginForm) {
  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(loginForm);
    const button = loginForm.querySelector("button[type='submit']");
    setFormFeedback(loginForm, "");
    setButtonLoading(button, true);
    try {
      await postJson("/api/auth/login", {password: formData.get("password")});
      window.location.href = "/";
    } catch (error) {
      setButtonLoading(button, false);
      setFormFeedback(loginForm, error.message, "error");
      showToast(error.message, "error");
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
    const button = setupPasswordForm.querySelector("button[type='submit']");
    setFormFeedback(setupPasswordForm, "");
    if (password !== confirmPassword) {
      setFormFeedback(setupPasswordForm, "两次输入的密码不一致", "error");
      return;
    }
    setButtonLoading(button, true);
    try {
      await postJson("/api/auth/setup-password", {password});
      window.location.href = "/";
    } catch (error) {
      setButtonLoading(button, false);
      setFormFeedback(setupPasswordForm, error.message, "error");
      showToast(error.message, "error");
    }
  });
}

document.querySelectorAll("[data-approve]").forEach((button) => {
  button.addEventListener("click", async () => {
    setButtonLoading(button, true);
    try {
      await postJson(`/api/signals/${button.dataset.approve}/approve`);
      showToast("建议已批准，模拟持仓已更新", "success");
      window.setTimeout(() => window.location.reload(), 600);
    } catch (error) {
      setButtonLoading(button, false);
      showToast(error.message, "error");
    }
  });
});

document.querySelectorAll("[data-reject]").forEach((button) => {
  button.addEventListener("click", async () => {
    if (!window.confirm("确认拒绝这条交易建议？")) return;
    setButtonLoading(button, true);
    try {
      await postJson(`/api/signals/${button.dataset.reject}/reject`);
      showToast("建议已拒绝", "success");
      window.setTimeout(() => window.location.reload(), 600);
    } catch (error) {
      setButtonLoading(button, false);
      showToast(error.message, "error");
    }
  });
});

const riskForm = document.getElementById("risk-form");
if (riskForm) {
  riskForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(riskForm);
    const payload = {};
    const button = riskForm.querySelector("button[type='submit']");
    setFormFeedback(riskForm, "");
    for (const [key, value] of formData.entries()) {
      payload[key] = key.includes("positions") || key.includes("days") ? Number.parseInt(value, 10) : Number.parseFloat(value);
    }
    setButtonLoading(button, true);
    try {
      await postJson("/api/risk", payload);
      setFormFeedback(riskForm, "风控参数已保存", "success");
      showToast("风控参数已保存", "success");
    } catch (error) {
      setFormFeedback(riskForm, error.message, "error");
      showToast(error.message, "error");
    } finally {
      setButtonLoading(button, false);
    }
  });
}

document.querySelectorAll("[data-opend-action]").forEach((button) => {
  button.addEventListener("click", async () => {
    if (button.dataset.confirm && !window.confirm(button.dataset.confirm)) return;
    await runOpenDAction(button, `/api/opend/${button.dataset.opendAction}`);
  });
});

document.querySelectorAll("[data-opend-refresh]").forEach((button) => {
  button.addEventListener("click", async () => {
    setButtonLoading(button, true);
    try {
      const payload = await getJson("/api/opend/status");
      renderOpenDStatus(payload);
      showToast(payload.message || "OpenD 状态已刷新", payload.ok === false ? "error" : "success");
    } catch (error) {
      showToast(error.message, "error");
    } finally {
      setButtonLoading(button, false);
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
    setFormFeedback(openDConfigForm, "");
    const result = await runOpenDAction(openDConfigForm.querySelector("button"), "/api/opend/configure", payload);
    setFormFeedback(openDConfigForm, result.ok ? "登录配置已保存" : result.message, result.ok ? "success" : "error");
    openDConfigForm.querySelectorAll("input[type='password']").forEach((input) => { input.value = ""; });
  });
}

const phoneCodeForm = document.getElementById("opend-phone-code-form");
if (phoneCodeForm) {
  phoneCodeForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(phoneCodeForm);
    setFormFeedback(phoneCodeForm, "");
    const result = await runOpenDAction(phoneCodeForm.querySelector("button"), "/api/opend/verify-code", {
      kind: "phone",
      code: String(formData.get("code") || ""),
    });
    setFormFeedback(phoneCodeForm, result.message, result.ok ? "success" : "error");
    phoneCodeForm.reset();
  });
}

const captchaCodeForm = document.getElementById("opend-captcha-code-form");
if (captchaCodeForm) {
  captchaCodeForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(captchaCodeForm);
    setFormFeedback(captchaCodeForm, "");
    const result = await runOpenDAction(captchaCodeForm.querySelector("button"), "/api/opend/verify-code", {
      kind: "captcha",
      code: String(formData.get("code") || ""),
    });
    setFormFeedback(captchaCodeForm, result.message, result.ok ? "success" : "error");
    captchaCodeForm.reset();
  });
}

async function runOpenDAction(button, url, payload = undefined) {
  setButtonLoading(button, true);
  try {
    const result = await postJson(url, payload);
    renderOpenDStatus(result);
    showToast(result.message || "OpenD 操作已完成", result.ok === false ? "error" : "success");
    return result;
  } catch (error) {
    showToast(error.message, "error");
    return {ok: false, message: error.message};
  } finally {
    setButtonLoading(button, false);
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
      <div><dt>验证码状态</dt><dd>${payload.needs_phone_code ? "需要手机验证码" : (payload.needs_captcha_code ? "需要图形验证码" : "暂无提示")}</dd></div>
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

document.addEventListener("click", (event) => {
  document.querySelectorAll(".action-menu[open]").forEach((menu) => {
    if (!menu.contains(event.target)) menu.removeAttribute("open");
  });
});
