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
  if (!response.ok) throw new Error(await response.text());
  return response.json();
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

