(function () {
  "use strict";

  /* ===== DOM helpers ===== */
  const el = (id) => document.getElementById(id);
  const qs = (sel, ctx) => (ctx || document).querySelector(sel);
  const qsa = (sel, ctx) => Array.from((ctx || document).querySelectorAll(sel));

  /* ===== State ===== */
  let currentStep = 0;
  let pollIntervals = {};

  /* ===== Step Navigation ===== */
  function setStep(step) {
    currentStep = step;
    qsa(".pane").forEach((pane) => pane.classList.remove("active"));
    qsa(`.pane[data-step="${step}"]`).forEach((pane) => pane.classList.add("active"));
    qsa(".step").forEach((s) => s.classList.remove("active"));
    qsa(`.step[data-step="${step}"]`).forEach((s) => s.classList.add("active"));
  }

  function setStatus(message) {
    const elm = el("connection-status");
    if (elm) elm.textContent = message;
  }

  function addLog(message, level) {
    level = level || "info";
    var box = el("log-box");
    if (!box) return;
    var now = new Date();
    var time =
      String(now.getHours()).padStart(2, "0") +
      ":" +
      String(now.getMinutes()).padStart(2, "0") +
      ":" +
      String(now.getSeconds()).padStart(2, "0");
    var entry = document.createElement("div");
    entry.className = "log-entry";
    entry.innerHTML = '<span class="log-time">' + time + "</span><span class=\"log-msg " + level + '">' + message + "</span>";
    box.appendChild(entry);
    box.scrollTop = box.scrollHeight;
  }

  function clearLog() {
    var box = el("log-box");
    if (box) box.innerHTML = "";
  }

  function showToast(message, type) {
    type = type || "info";
    var toast = el("toast");
    toast.textContent = message;
    toast.className = "toast visible " + type;
    setTimeout(function () {
      toast.classList.remove("visible");
    }, 3000);
  }

  /* ===== Model Definitions ===== */
  var MODELS = [
    { key: "gemma-4b", label: "Gemma-3-4B", size: "8 GB", vram: "8 GB", gpu: "RTX 3060+", repo: "google/gemma-3-4b-it" },
    { key: "qwen-7b", label: "Qwen2.5-VL-7B", size: "14 GB", vram: "14 GB", gpu: "RTX 4080+", repo: "Qwen/Qwen2.5-VL-7B-Instruct" },
    { key: "gemma-12b", label: "Gemma-3-12B", size: "24 GB", vram: "24 GB", gpu: "RTX 4090", repo: "google/gemma-3-12b-it" },
    { key: "qwen-27b", label: "Qwen3.6-27B", size: "54 GB", vram: "54 GB", gpu: "2x RTX 4090", repo: "Qwen/Qwen3-27B" },
  ];

  var modelDownloads = {};
  var modelStates = {};

  /* ===== GPU Detection ===== */
  async function detectGPU() {
    try {
      var resp = await fetch("/v1/settings/gpu");
      if (!resp.ok) throw new Error("GPU detect failed");
      return await resp.json();
    } catch (err) {
      console.error("GPU detect error:", err);
      return { cuda_available: false, gpu_name: "N/A", vram_total_gb: 0, vram_free_gb: 0 };
    }
  }

  function recommendModel(gpuInfo) {
    if (!gpuInfo || !gpuInfo.cuda_available) return null;
    var freeGB = gpuInfo.vram_free_gb || gpuInfo.vram_total_gb || 0;
    if (freeGB >= 54) return MODELS[3]; // qwen-27b
    if (freeGB >= 24) return MODELS[2]; // gemma-12b
    if (freeGB >= 14) return MODELS[1]; // qwen-7b
    if (freeGB >= 8) return MODELS[0]; // gemma-4b
    return MODELS[0];
  }

  /* ===== Settings ===== */
  async function loadSettings() {
    try {
      var resp = await fetch("/v1/settings");
      if (!resp.ok) return;
      var settings = await resp.json();

      var modeRadios = qsa('input[name="llm-mode"]');
      modeRadios.forEach(function (r) {
        r.checked = r.value === settings.mode;
      });
      onModeChange(settings.mode);

      if (settings.remote) {
        el("api-key").value = settings.remote.api_key || "";
        el("base-url").value = settings.remote.base_url || "";
        el("remote-model").value = settings.remote.model || "";
      }
      if (settings.local) {
        el("model-path").value = settings.local.model_path || "";
        el("precision").value = settings.local.precision || "bf16";
        el("temperature").value = settings.local.temperature != null ? settings.local.temperature : 0.1;
        el("timeout-sec").value = settings.local.timeout_sec || 15;
        el("max-tokens").value = settings.local.max_tokens || 2048;
      }
    } catch (err) {
      console.error("Load settings error:", err);
    }
  }

  async function saveSettings() {
    var mode = qs('input[name="llm-mode"]:checked');
    var payload = {
      mode: mode ? mode.value : "remote",
      remote: {
        api_key: el("api-key").value.trim(),
        base_url: el("base-url").value.trim(),
        model: el("remote-model").value,
      },
      local: {
        model_path: el("model-path").value.trim(),
        precision: el("precision").value,
        temperature: parseFloat(el("temperature").value) || 0.1,
        timeout_sec: parseInt(el("timeout-sec").value, 10) || 15,
        max_tokens: parseInt(el("max-tokens").value, 10) || 2048,
      },
    };

    try {
      var resp = await fetch("/v1/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) throw new Error("Save failed");
      showToast("设置已保存", "success");
      addLog("设置保存成功", "success");
    } catch (err) {
      console.error("Save settings error:", err);
      showToast("保存失败: " + err.message, "error");
    }
  }

  async function testConnection() {
    setStatus("检测中...");
    var elm = qs("#connection-status");
    elm.className = "status-text loading";

    try {
      var apiKey = el("api-key").value.trim();
      var baseUrl = el("base-url").value.trim() || "https://api.openai.com/v1";

      if (!apiKey) {
        setStatus("请先填写 API Key");
        elm.className = "status-text error";
        return;
      }

      var resp = await fetch(baseUrl + "/models", {
        headers: { Authorization: "Bearer " + apiKey },
      });

      if (resp.ok) {
        var data = await resp.json();
        setStatus("连接成功 - " + (data.data && data.data.length ? data.data.length + " 个模型可用" : "已连接"));
        elm.className = "status-text success";
        addLog("API 连接测试成功", "success");
      } else {
        setStatus("连接失败 (HTTP " + resp.status + ")");
        elm.className = "status-text error";
      }
    } catch (err) {
      setStatus("连接失败: " + err.message);
      elm.className = "status-text error";
      console.error("Test connection error:", err);
    }
  }

  function onModeChange(mode) {
    var remotePanel = el("panel-remote");
    var localPanel = el("panel-local");
    if (mode === "local") {
      remotePanel.classList.add("hidden");
      localPanel.classList.remove("hidden");
    } else {
      remotePanel.classList.remove("hidden");
      localPanel.classList.add("hidden");
    }
  }

  /* ===== Model Download ===== */
  async function loadModelList() {
    try {
      var resp = await fetch("/v1/settings/models");
      if (resp.ok) {
        var data = await resp.json();
        if (data.models) {
          Object.keys(data.models).forEach(function (key) {
            var existing = MODELS.find(function (m) { return m.key === key; });
            if (!existing) return;
            existing.desc = data.models[key].description || "";
          });
        }
      }
    } catch (err) {
      console.error("Load model list error:", err);
    }
    renderModelCards();
  }

  async function fetchAllDownloadStatuses() {
    for (var i = 0; i < MODELS.length; i++) {
      try {
        var resp = await fetch("/v1/settings/model/download/status?model=" + MODELS[i].key);
        if (resp.ok) {
          var data = await resp.json();
          modelStates[MODELS[i].key] = {
            progress: data.progress,
            status: data.status,
          };
        }
      } catch (err) {
        // ignore
      }
    }
    renderModelCards();
  }

  function renderModelCards() {
    var container = el("model-cards");
    if (!container) return;
    var html = "";
    for (var i = 0; i < MODELS.length; i++) {
      var m = MODELS[i];
      var state = modelStates[m.key] || {};
      var status = state.status || "not_started";
      var progress = state.progress;
      var isDownloading = status === "downloading";
      var isCompleted = status === "completed" || progress >= 100;
      var isFailed = status === "failed" || progress === -1;
      var statusLabel = isDownloading ? "下载中"
        : isCompleted ? "已下载"
        : isFailed ? "下载失败"
        : "未下载";
      var statusClass = isDownloading ? "downloading"
        : isCompleted ? "completed"
        : isFailed ? "failed"
        : "not-downloaded";

      html +=
        '<div class="model-card" data-model-key="' +
        m.key +
        '">' +
        '<div class="model-card-header">' +
        '<div class="model-name">' +
        m.label +
        "</div>" +
        '<div class="model-status ' +
        statusClass +
        '">' +
        statusLabel +
        "</div>" +
        "</div>" +
        '<div class="model-desc">' +
        (m.desc || "") +
        "</div>" +
        '<div class="model-specs">' +
        '<div class="model-spec">文件大小: <strong>' +
        m.size +
        "</strong></div>" +
        '<div class="model-spec">显存需求: <strong>' +
        m.vram +
        "</strong></div>" +
        '<div class="model-spec" style="grid-column:1/-1">推荐显卡: <strong>' +
        m.gpu +
        "</strong></div>" +
        "</div>" +
        '<div class="model-path-row">' +
        '<input type="text" class="input path-input" id="path-' +
        m.key +
        '" placeholder="下载路径" value="">' +
        "</div>" +
        '<div class="model-progress">' +
        '<div class="model-progress-bar"><div class="model-progress-fill" style="width:' +
        (isDownloading && progress > 0 ? progress : 0) +
        '%"></div></div>' +
        '<div class="model-progress-label" id="prog-label-' +
        m.key +
        '">' +
        (isDownloading ? (progress || 0) + "%" : isCompleted ? "100%" : "") +
        "</div>" +
        "</div>" +
        '<div class="btn-group">' +
        (isDownloading
          ? '<button class="btn btn-sm btn-soft pause-btn" data-model="' + m.key + '">暂停</button>' +
            '<button class="btn btn-sm btn-danger cancel-btn" data-model="' + m.key + '">取消</button>'
          : isCompleted
          ? '<button class="btn btn-sm btn-danger delete-btn" data-model="' + m.key + '">删除</button>'
          : '<button class="btn btn-sm btn-accent download-btn" data-model="' + m.key + '">下载</button>') +
        "</div>" +
        "</div>";
    }
    container.innerHTML = html;
    bindModelCardEvents();
  }

  function bindModelCardEvents() {
    qsa(".download-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var modelKey = btn.dataset.model;
        var pathInput = el("path-" + modelKey);
        var downloadPath = pathInput ? pathInput.value.trim() : "";
        startDownload(modelKey, downloadPath);
      });
    });

    qsa(".pause-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        pauseDownload(btn.dataset.model);
      });
    });

    qsa(".cancel-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        cancelDownload(btn.dataset.model);
      });
    });

    qsa(".delete-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var modelKey = btn.dataset.model;
        var pathInput = el("path-" + modelKey);
        var path = pathInput ? pathInput.value.trim() : "";
        deleteModel(modelKey, path);
      });
    });
  }

  async function startDownload(modelKey, downloadPath) {
    if (!downloadPath) {
      showToast("请先填写下载路径", "warning");
      return;
    }

    try {
      var formData = new FormData();
      formData.append("model", modelKey);
      formData.append("path", downloadPath);

      var resp = await fetch("/v1/settings/model/download", {
        method: "POST",
        body: formData,
      });

      if (!resp.ok) {
        var errData = await resp.json().catch(function () { return {}; });
        showToast("下载启动失败: " + (errData.detail || "未知错误"), "error");
        return;
      }

      addLog("开始下载模型: " + modelKey, "progress");
      showToast("下载任务已启动", "info");
      modelStates[modelKey] = { progress: 0, status: "downloading" };
      renderModelCards();
      startPolling(modelKey);
    } catch (err) {
      showToast("下载启动失败: " + err.message, "error");
    }
  }

  function startPolling(modelKey) {
    if (pollIntervals[modelKey]) clearInterval(pollIntervals[modelKey]);

    pollIntervals[modelKey] = setInterval(async function () {
      try {
        var resp = await fetch("/v1/settings/model/download/status?model=" + modelKey);
        var data = await resp.json();
        if (data == null) return; // not started

        var progress = data.progress;
        var status = data.status;

        modelStates[modelKey] = { progress: progress, status: status };

        updateProgress(modelKey, progress);

        if (progress === -1 || status === "failed") {
          addLog("下载失败: " + modelKey, "error");
          clearInterval(pollIntervals[modelKey]);
          delete pollIntervals[modelKey];
          modelStates[modelKey].status = "failed";
          renderModelCards();
          return;
        }

        if (progress >= 100 || status === "completed") {
          addLog("下载完成: " + modelKey, "success");
          clearInterval(pollIntervals[modelKey]);
          delete pollIntervals[modelKey];
          modelStates[modelKey] = { progress: 100, status: "completed" };
          updateProgress(modelKey, 100);
          renderModelCards();
          return;
        }

        modelStates[modelKey].status = "downloading";
      } catch (err) {
        console.error("Poll error for", modelKey, err);
      }
    }, 500);
  }

  function updateProgress(modelKey, progress) {
    var progFill = el("progress-fill");
    var progLabel = el("progress-label");
    var cardProgLabel = el("prog-label-" + modelKey);
    var card = qs('.model-card[data-model-key="' + modelKey + '"]');
    var cardFill = card ? qs(".model-progress-fill", card) : null;

    if (progFill) progFill.style.width = (progress || 0) + "%";
    if (progLabel) progLabel.textContent = (progress || 0) + "%";
    if (cardProgLabel) cardProgLabel.textContent = (progress || 0) + "%";
    if (cardFill) cardFill.style.width = (progress || 0) + "%";
  }

  async function pauseDownload(modelKey) {
    try {
      var formData = new FormData();
      formData.append("model", modelKey);
      await fetch("/v1/settings/model/download/cancel", { method: "POST", body: formData });
      if (pollIntervals[modelKey]) {
        clearInterval(pollIntervals[modelKey]);
        delete pollIntervals[modelKey];
      }
      addLog("已暂停下载: " + modelKey, "warning");
      modelStates[modelKey] = { progress: modelStates[modelKey] ? modelStates[modelKey].progress : 0, status: "cancelled" };
      renderModelCards();
    } catch (err) {
      console.error("Pause error:", err);
    }
  }

  async function cancelDownload(modelKey) {
    try {
      var formData = new FormData();
      formData.append("model", modelKey);
      await fetch("/v1/settings/model/download/cancel", { method: "POST", body: formData });
      if (pollIntervals[modelKey]) {
        clearInterval(pollIntervals[modelKey]);
        delete pollIntervals[modelKey];
      }
      addLog("已取消下载: " + modelKey, "warning");
      delete modelStates[modelKey];
      renderModelCards();
    } catch (err) {
      console.error("Cancel error:", err);
    }
  }

  async function deleteModel(modelKey, path) {
    if (!path) {
      showToast("请先填写下载路径", "warning");
      return;
    }

    if (!confirm("确定要删除模型文件吗？此操作不可撤销。")) return;

    try {
      var resp = await fetch("/v1/settings/model/download?model=" + modelKey + "&path=" + encodeURIComponent(path), {
        method: "DELETE",
      });
      if (!resp.ok) throw new Error("Delete failed");

      addLog("已删除模型: " + modelKey, "success");
      showToast("模型已删除", "success");
      delete modelStates[modelKey];
      renderModelCards();
    } catch (err) {
      showToast("删除失败: " + err.message, "error");
    }
  }

  /* ===== Event Binding ===== */
  function bindEvents() {
    // Step navigation
    qsa(".step").forEach(function (btn) {
      btn.addEventListener("click", function () {
        setStep(parseInt(btn.dataset.step, 10));
        if (parseInt(btn.dataset.step, 10) === 2) {
          fetchAllDownloadStatuses();
        }
      });
    });

    // Mode switch
    qsa('input[name="llm-mode"]').forEach(function (radio) {
      radio.addEventListener("change", function () {
        onModeChange(radio.value);
      });
    });

    // API key visibility toggle
    var toggleBtn = el("toggle-api-key");
    if (toggleBtn) {
      toggleBtn.addEventListener("click", function () {
        var input = el("api-key");
        if (input.type === "password") {
          input.type = "text";
          toggleBtn.innerHTML = "&#128064;";
        } else {
          input.type = "password";
          toggleBtn.innerHTML = "&#128065;";
        }
      });
    }

    // Test connection
    var testBtn = el("test-connection");
    if (testBtn) {
      testBtn.addEventListener("click", testConnection);
    }

    // Save settings
    var saveBtn = el("save-settings");
    if (saveBtn) {
      saveBtn.addEventListener("click", saveSettings);
    }
  }

  /* ===== Init ===== */
  async function init() {
    setStep(0);
    bindEvents();
    await loadSettings();

    // Detect GPU for local panel
    var gpuInfo = await detectGPU();
    el("gpu-name").textContent = gpuInfo.gpu_name || "N/A";
    el("gpu-total").textContent = gpuInfo.vram_total_gb ? gpuInfo.vram_total_gb + " GB" : "--";
    el("gpu-free").textContent = gpuInfo.vram_free_gb ? gpuInfo.vram_free_gb + " GB" : "--";

    addLog("GPU 检测: " + (gpuInfo.cuda_available ? gpuInfo.gpu_name + " (" + gpuInfo.vram_total_gb + " GB)" : "未检测到可用 GPU"), gpuInfo.cuda_available ? "success" : "warning");

    var recommended = recommendModel(gpuInfo);
    if (recommended) {
      addLog("推荐模型: " + recommended.label + " (显存需求 " + recommended.vram + ")", "info");
    }

    await loadModelList();
    await fetchAllDownloadStatuses();
  }

  // Restore polling on page load
  for (var i = 0; i < MODELS.length; i++) {
    (function (key) {
      fetch("/v1/settings/model/download/status?model=" + key)
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
          if (data && data.status === "downloading") {
            modelStates[key] = { progress: data.progress, status: "downloading" };
            startPolling(key);
          }
        })
        .catch(function () {});
    })(MODELS[i].key);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
