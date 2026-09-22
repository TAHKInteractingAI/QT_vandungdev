import { mediaURL } from "/ui/lib.js";

// Creator should always open at its entry point, not at a browser-restored
// scroll position from a previous visit.
history.scrollRestoration = "manual";
window.scrollTo(0, 0);

const form = document.getElementById("creatorForm");
const operationCards = [...document.querySelectorAll(".operation-card")];
const imageField = document.getElementById("imageField");
const imageInput = document.getElementById("imageInput");
const dropzone = document.getElementById("dropzone");
const imagePreview = document.getElementById("imagePreview");
const imagePreviewTag = imagePreview.querySelector("img");
const imageName = document.getElementById("imageName");
const imageMeta = document.getElementById("imageMeta");
const prompt = document.getElementById("prompt");
const promptCount = document.getElementById("promptCount");
const statusTag = document.getElementById("statusTag");
const formStatus = document.getElementById("formStatus");
const generateButton = document.getElementById("generateButton");
const buttonLabel = document.getElementById("buttonLabel");
const previewStage = document.getElementById("previewStage");
const resultActions = document.getElementById("resultActions");
const downloadLink = document.getElementById("downloadLink");
const formatMeta = document.getElementById("formatMeta");
const modelSelect = document.getElementById("model");
const modelHint = document.getElementById("modelHint");
let modelRequest = 0;
let imageData = null;

function selected(name) { return document.querySelector(`input[name="${name}"]:checked`)?.value; }
function setStatus(text, error = false, modelName = null) {
  formStatus.className = `form-status${error ? " error" : ""}`;
  formStatus.replaceChildren();
  if (!error) {
    formStatus.textContent = text;
    return;
  }

  const raw = String(text || "Generation failed");
  const isQuotaError = /\b429\b|RESOURCE_EXHAUSTED/i.test(raw);
  const hasZeroQuota = /limit:\s*0/i.test(raw);
  const model = modelName || raw.match(/model:\s*([A-Za-z0-9._-]+)/i)?.[1];
  const retrySeconds = raw.match(/retry\s+in\s+([\d.]+)\s*s/i)?.[1]
    || raw.match(/retry(?:Delay|_delay)["']?\s*:\s*["']?([\d.]+)\s*s/i)?.[1];
  const card = document.createElement("section");
  card.className = "error-card";
  card.setAttribute("aria-live", "assertive");

  const header = document.createElement("div");
  header.className = "error-card-head";
  const icon = document.createElement("span");
  icon.className = "error-card-icon";
  icon.textContent = "!";
  icon.setAttribute("aria-hidden", "true");
  const kicker = document.createElement("span");
  kicker.className = "error-card-kicker";
  kicker.textContent = isQuotaError ? "Provider limit" : "Generation error";
  header.append(icon, kicker);

  const title = document.createElement("h3");
  title.className = "error-card-title";
  title.textContent = isQuotaError ? "API quota is unavailable" : "The generation did not finish";

  const summary = document.createElement("p");
  summary.className = "error-card-summary";
  summary.textContent = hasZeroQuota
    ? "This model has no available free API quota for the current project."
    : isQuotaError
      ? "The provider temporarily refused this request because its quota or rate limit was reached."
      : "The selected provider returned an error while creating your media.";

  const facts = document.createElement("div");
  facts.className = "error-card-facts";
  const addFact = (label, value) => {
    if (!value) return;
    const fact = document.createElement("span");
    fact.className = "error-card-fact";
    fact.innerHTML = `<span>${label}</span><b></b>`;
    fact.querySelector("b").textContent = value;
    facts.append(fact);
  };
  addFact("STATUS", raw.match(/\b(4\d\d|5\d\d)\b/)?.[1]);
  addFact("MODEL", model);
  addFact("RETRY", retrySeconds ? `~${Math.ceil(Number(retrySeconds))}s` : null);

  const hint = document.createElement("p");
  hint.className = "error-card-hint";
  hint.textContent = hasZeroQuota
    ? "Check the provider billing/quota or choose another configured model."
    : isQuotaError
      ? "Wait briefly and retry, or switch to another available model."
      : "Review the technical details below and try again.";

  const details = document.createElement("details");
  const detailsSummary = document.createElement("summary");
  detailsSummary.textContent = "Technical details";
  const rawOutput = document.createElement("pre");
  rawOutput.textContent = raw;
  details.append(detailsSummary, rawOutput);
  card.append(header, title, summary, facts, hint, details);
  formStatus.append(card);
}

function updateModelMeta() {
  const selectedModel = modelSelect.selectedOptions[0];
  const operation = selected("operation");
  document.getElementById("modelMeta").textContent = selectedModel?.dataset.label || (operation === "text_to_image" ? "Image model" : "Video model");
  modelHint.textContent = selectedModel?.dataset.provider
    ? `${selectedModel.dataset.provider} API · ${selectedModel.disabled ? "unavailable" : "configured"}`
    : "loading";
}

async function loadModels(operation) {
  const requestId = ++modelRequest;
  modelSelect.disabled = true;
  modelSelect.replaceChildren(new Option("Loading models…", ""));
  try {
    const response = await fetch(`/api/models?operation=${encodeURIComponent(operation)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Could not load models");
    if (requestId !== modelRequest) return;
    const previous = modelSelect.value;
    modelSelect.replaceChildren(...data.models.map((item) => {
      const option = new Option(`${item.label} · ${item.provider}`, item.id);
      option.dataset.label = item.label;
      option.dataset.provider = item.provider;
      option.disabled = item.available === false;
      option.title = item.available === false
        ? (item.availability_reason || item.note || "Unavailable")
        : (item.note || "");
      return option;
    }));
    const defaultModel = data.models.find((item) => item.available && item.default)
      || data.models.find((item) => item.available)
      || data.models[0];
    const previousModel = data.models.find((item) => item.id === previous && item.available);
    const selectedModel = previousModel || defaultModel;
    modelSelect.value = selectedModel?.id || "";
    modelSelect.disabled = !selectedModel?.available;
    updateModelMeta();
  } catch (error) {
    if (requestId !== modelRequest) return;
    modelSelect.replaceChildren(new Option("No models available", ""));
    modelSelect.disabled = true;
    modelHint.textContent = "unavailable";
    setStatus(error.message, true);
  }
}

function refreshOperation() {
  const operation = selected("operation");
  operationCards.forEach((card) => card.classList.toggle("selected", card.querySelector("input").checked));
  imageField.classList.toggle("is-hidden", operation !== "image_to_video");
  loadModels(operation);
  updateModelMeta();
  if (operation !== "image_to_video") clearImage();
}

function clearImage() {
  imageData = null;
  imageInput.value = "";
  imagePreview.classList.add("is-hidden");
  dropzone.classList.remove("is-hidden");
}

async function loadImage(file) {
  if (!file) return;
  if (file.size > 15 * 1024 * 1024) { setStatus("Image is larger than 15 MB.", true); return; }
  if (!file.type.startsWith("image/")) { setStatus("Choose a PNG, JPG or WEBP image.", true); return; }
  imageData = await new Promise((resolve, reject) => {
    const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(file);
  });
  imagePreviewTag.src = imageData;
  imageName.textContent = file.name;
  imageMeta.textContent = `${Math.round(file.size / 1024)} KB · ready to use`;
  imagePreview.classList.remove("is-hidden");
  dropzone.classList.add("is-hidden");
  setStatus("Reference image ready.");
}

function showResult(data) {
  const files = data.files || [];
  const mediaFile = files.find((file) => /\.(mp4|webm|mov|png|jpg|jpeg|webp)$/i.test(file));
  if (!mediaFile) { setStatus("The tool finished but returned no preview file.", true); return; }
  const url = mediaURL(data.project_id, mediaFile);
  previewStage.innerHTML = "";
  const media = /\.(mp4|webm|mov)$/i.test(mediaFile) ? document.createElement("video") : document.createElement("img");
  media.src = url; media.controls = media.tagName === "VIDEO"; media.autoplay = media.tagName === "VIDEO"; media.loop = media.tagName === "VIDEO"; media.muted = media.tagName === "VIDEO"; media.alt = "Generated OpenMontage output";
  previewStage.append(media);
  downloadLink.href = url; downloadLink.classList.remove("is-hidden");
  resultActions.classList.remove("is-hidden");
  statusTag.textContent = "READY"; statusTag.classList.remove("busy");
  setStatus(data.message || "Created locally.");
}

operationCards.forEach((card) => card.addEventListener("click", refreshOperation));
imageInput.addEventListener("change", () => loadImage(imageInput.files[0]));
document.getElementById("removeImage").addEventListener("click", clearImage);
modelSelect.addEventListener("change", updateModelMeta);
prompt.addEventListener("input", () => { promptCount.textContent = `${prompt.value.length.toLocaleString()} / 2,000`; });
document.querySelectorAll('input[name="preset"]').forEach((input) => input.addEventListener("change", () => { formatMeta.textContent = input.value === "tiktok" ? "Vertical · 9:16" : "Landscape · 16:9"; }));

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const operation = selected("operation");
  if (operation === "image_to_video" && !imageData) { setStatus("Add a reference image first.", true); return; }
  generateButton.disabled = true; buttonLabel.textContent = "Generating locally…"; statusTag.textContent = "WORKING"; statusTag.classList.add("busy"); resultActions.classList.add("is-hidden"); setStatus("Calling the selected tool. This can take a few minutes.");
  try {
    if (!modelSelect.value || modelSelect.selectedOptions[0]?.disabled) throw new Error("The selected model is unavailable.");
    const response = await fetch("/api/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ operation, model: modelSelect.value, prompt: prompt.value.trim(), narration: document.getElementById("narration").value.trim(), language: selected("language"), preset: selected("preset"), image_data: imageData }) });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      const generationError = new Error(data.error || data.detail || "Generation failed");
      generationError.model = data.model;
      throw generationError;
    }
    showResult(data);
  } catch (error) {
    statusTag.textContent = "ERROR";
    statusTag.classList.remove("busy");
    setStatus(error.message, true, error.model);
  }
  finally { generateButton.disabled = false; buttonLabel.textContent = "Generate locally"; }
});

refreshOperation();
