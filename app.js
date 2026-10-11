/**
 * WasteAI — app.js
 * Clean Frontend: Handles image upload, calls backend /api/classify,
 *                 connects to MQTT broker automatically, updates UI.
 */

'use strict';

const CATEGORIES = {
  'Metal': { icon: '⚙️', color: '#94a3b8', angle: 15 },
  'Wet Waste': { icon: '🌿', color: '#34d399', angle: 60 },
  'Plastic': { icon: '🧴', color: '#38bdf8', angle: 105 },
  'Dry Waste': { icon: '📦', color: '#fb923c', angle: 150 },
};

let mqttClient = null;
let currentCategory = null;
let currentImage = null; // base64 string
let currentImageMime = 'image/jpeg';
let servoAngle = 180; // current display angle
let servoTargetAngle = 180;
let animFrameId = null;

const HARDCODED_BROKER = "ws://broker.hivemq.com:8000/mqtt";
const HARDCODED_TOPIC = "wasteai/sorter/command";

// DOM REFS
const dropZone = document.getElementById('dropZone');
const dropZoneInner = document.getElementById('dropZoneInner');
const fileInput = document.getElementById('fileInput');
const previewImg = document.getElementById('previewImg');
const classifyBtn = document.getElementById('classifyBtn');
const classifySpinner = document.getElementById('classifySpinner');
const classifyBtnText = document.getElementById('classifyBtnText');
const errorBox = document.getElementById('errorBox');
const resultPlaceholder = document.getElementById('resultPlaceholder');
const resultContent = document.getElementById('resultContent');
const resultCategoryIcon = document.getElementById('resultCategoryIcon');
const resultCategoryName = document.getElementById('resultCategoryName');
const resultConfidenceFill = document.getElementById('resultConfidenceFill');
const mqttDot = document.getElementById('mqttDot');
const mqttStatusLabel = document.getElementById('mqttStatusLabel');
const servoBaseAngleEl = document.getElementById('servoBaseAngle');
const servoGripperEl = document.getElementById('servoGripperState');
const servoCanvas = document.getElementById('servoCanvas');
const servoCtx = servoCanvas.getContext('2d');

function showError(msg) {
  errorBox.textContent = msg;
  errorBox.classList.remove('hidden');
}

function clearError() {
  errorBox.classList.add('hidden');
  errorBox.textContent = '';
}

// ─── DRAG & DROP + FILE INPUT ─────────────────────────────
dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file && file.type.startsWith('image/')) loadImage(file);
});

fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) loadImage(fileInput.files[0]);
});

function loadImage(file) {
  clearError();
  currentImageMime = file.type || 'image/jpeg';
  const reader = new FileReader();
  reader.onload = (e) => {
    const dataUrl = e.target.result;
    currentImage = dataUrl.split(',')[1];
    previewImg.src = dataUrl;
    previewImg.classList.remove('hidden');
    dropZoneInner.style.opacity = '0';
    dropZoneInner.style.pointerEvents = 'none';
    classifyBtn.disabled = false;
    showPlaceholder();
  };
  reader.readAsDataURL(file);
}

// ─── CLASSIFY WITH BACKEND ───────────────────────────────
classifyBtn.addEventListener('click', classifyImage);

async function classifyImage() {
  if (!currentImage) return;

  clearError();
  classifyBtn.disabled = true;
  classifySpinner.classList.remove('hidden');
  classifyBtnText.textContent = 'Classifying…';

  try {
    const res = await fetch('/api/classify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image: currentImage,
        mime_type: currentImageMime
      }),
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data?.error?.message || `HTTP ${res.status}`);
    }

    const candidate = data.candidates?.[0];
    const finishReason = candidate?.finishReason || 'UNKNOWN';
    const rawText = candidate?.content?.parts?.[0]?.text?.trim() || '';

    const hardBlock = !['STOP', 'MAX_TOKENS'].includes(finishReason);
    if (hardBlock || (!rawText && finishReason !== 'STOP')) {
      throw new Error(`Gemini blocked. finishReason: ${finishReason}. Try a different image.`);
    }

    const category = normalizeCategory(rawText);
    if (!category) {
      throw new Error(`Unexpected response: "${rawText}".`);
    }

    showResult(category);
    animateServoArm(CATEGORIES[category].angle);
    currentCategory = category;

    publishCommand(category);

  } catch (err) {
    showError(err.message);
    showPlaceholder();
  } finally {
    classifyBtn.disabled = false;
    classifySpinner.classList.add('hidden');
    classifyBtnText.textContent = 'Classify Waste';
  }
}

function normalizeCategory(raw) {
  const lower = raw.toLowerCase().trim();
  if (lower === 'metal') return 'Metal';
  if (lower === 'wet waste' || lower === 'wet') return 'Wet Waste';
  if (lower === 'plastic') return 'Plastic';
  if (lower === 'dry waste' || lower === 'dry') return 'Dry Waste';
  for (const cat of Object.keys(CATEGORIES)) {
    if (lower.includes(cat.toLowerCase())) return cat;
  }
  return null;
}

function showResult(category) {
  const cfg = CATEGORIES[category];
  resultPlaceholder.classList.add('hidden');
  resultContent.classList.remove('hidden');
  resultCategoryIcon.textContent = cfg.icon;
  resultCategoryName.textContent = category;
  resultCategoryName.style.color = cfg.color;
  resultCategoryName.style.textShadow = `0 0 24px ${cfg.color}66`;
  setTimeout(() => { resultConfidenceFill.style.width = '100%'; }, 50);
}

function showPlaceholder() {
  resultPlaceholder.classList.remove('hidden');
  resultContent.classList.add('hidden');
  resultConfidenceFill.style.width = '0%';
}

// ─── MQTT ─────────────────────────────────────────────────
function connectMqtt() {
  setMqttStatus('connecting');
  const clientId = 'wasteai_' + Math.random().toString(36).slice(2, 9);

  mqttClient = mqtt.connect(HARDCODED_BROKER, {
    clientId,
    keepalive: 60,
    reconnectPeriod: 5000,
    connectTimeout: 10000,
  });

  mqttClient.on('connect', () => {
    setMqttStatus('connected');
  });

  mqttClient.on('error', (err) => {
    setMqttStatus('error');
  });

  mqttClient.on('offline', () => {
    setMqttStatus('disconnected');
  });
}

function setMqttStatus(state) {
  mqttDot.className = 'status-dot';
  if (state === 'connected') {
    mqttDot.classList.add('connected');
    mqttStatusLabel.textContent = 'MQTT: Connected';
  } else if (state === 'error') {
    mqttDot.classList.add('error');
    mqttStatusLabel.textContent = 'MQTT: Error';
  } else if (state === 'connecting') {
    mqttStatusLabel.textContent = 'MQTT: Connecting…';
  } else {
    mqttStatusLabel.textContent = 'MQTT: Disconnected';
  }
}

function publishCommand(category) {
  console.log("Attempting to publish:", category);

  // If disconnected, force a quick reconnect and try again
  if (!mqttClient || !mqttClient.connected) {
    console.warn("MQTT is disconnected. Reconnecting to send command...");
    setMqttStatus('connecting');
    connectMqtt();

    // Wait 1.5 seconds for the connection to establish, then send
    setTimeout(() => {
      if (mqttClient && mqttClient.connected) {
        mqttClient.publish(HARDCODED_TOPIC, category, { qos: 0 });
        console.log("Published after reconnect:", category);
      } else {
        showError("MQTT Reconnect failed. Please refresh the page.");
      }
    }, 1500);
    return;
  }

  // If already connected, publish immediately with QoS 0 (fire and forget)
  mqttClient.publish(HARDCODED_TOPIC, category, { qos: 0 });
  console.log("Successfully published:", category);
}

// ─── SERVO ARM CANVAS ─────────────────────────────────────
function resizeServoCanvas() {
  const wrapper = servoCanvas.parentElement;
  const w = wrapper.clientWidth;
  servoCanvas.width = w;
  servoCanvas.height = Math.round(w * 0.5);
  drawServo();
}

function drawServo() {
  const w = servoCanvas.width;
  const h = servoCanvas.height;
  const cx = w * 0.15;
  const cy = h * 0.72;
  const armLength = w * 0.52;
  const lowerArmLength = w * 0.26;

  servoCtx.clearRect(0, 0, w, h);
  servoCtx.strokeStyle = 'rgba(110,231,247,0.05)';
  servoCtx.lineWidth = 1;
  for (let x = 0; x < w; x += 24) { servoCtx.beginPath(); servoCtx.moveTo(x, 0); servoCtx.lineTo(x, h); servoCtx.stroke(); }
  for (let y = 0; y < h; y += 24) { servoCtx.beginPath(); servoCtx.moveTo(0, y); servoCtx.lineTo(w, y); servoCtx.stroke(); }

  servoCtx.beginPath();
  servoCtx.arc(cx, cy, armLength, -Math.PI, 0, false);
  servoCtx.strokeStyle = 'rgba(110,231,247,0.08)';
  servoCtx.lineWidth = 1.5;
  servoCtx.stroke();

  const rad = ((180 - servoAngle) / 180) * Math.PI;
  const elbowX = cx + armLength * Math.cos(rad);
  const elbowY = cy - armLength * Math.sin(rad);

  const grad1 = servoCtx.createLinearGradient(cx, cy, elbowX, elbowY);
  grad1.addColorStop(0, '#6ee7f7');
  grad1.addColorStop(1, '#a78bfa');
  servoCtx.beginPath();
  servoCtx.moveTo(cx, cy);
  servoCtx.lineTo(elbowX, elbowY);
  servoCtx.strokeStyle = grad1;
  servoCtx.lineWidth = 6;
  servoCtx.lineCap = 'round';
  servoCtx.stroke();

  const gripperY = elbowY + lowerArmLength;
  servoCtx.beginPath();
  servoCtx.moveTo(elbowX, elbowY);
  servoCtx.lineTo(elbowX, gripperY);
  servoCtx.strokeStyle = '#a78bfa';
  servoCtx.lineWidth = 4;
  servoCtx.stroke();

  servoCtx.beginPath();
  servoCtx.arc(elbowX, gripperY, 7, 0, Math.PI * 2);
  servoCtx.fillStyle = '#a78bfa';
  servoCtx.fill();

  servoCtx.beginPath();
  servoCtx.arc(cx, cy, 10, 0, Math.PI * 2);
  servoCtx.fillStyle = '#6ee7f7';
  servoCtx.fill();
  servoCtx.beginPath();
  servoCtx.arc(cx, cy, 5, 0, Math.PI * 2);
  servoCtx.fillStyle = '#080d1a';
  servoCtx.fill();

  servoCtx.fillStyle = '#6ee7f7';
  servoCtx.font = `bold ${Math.round(w * 0.03)}px JetBrains Mono, monospace`;
  servoCtx.fillText(`${Math.round(servoAngle)}°`, cx + armLength * 0.45 * Math.cos(rad), cy - armLength * 0.45 * Math.sin(rad) - 10);
}

function animateServoArm(targetAngle) {
  servoTargetAngle = targetAngle;
  if (animFrameId) cancelAnimationFrame(animFrameId);
  servoGripperEl.textContent = 'Closed ✊';
  servoGripperEl.style.color = '#fb7185';

  function step() {
    const diff = servoTargetAngle - servoAngle;
    if (Math.abs(diff) < 0.5) {
      servoAngle = servoTargetAngle;
      servoBaseAngleEl.textContent = `${Math.round(servoAngle)}°`;
      drawServo();
      setTimeout(() => {
        servoGripperEl.textContent = 'Open 🤙';
        servoGripperEl.style.color = '#34d399';
        animateServoArm(180);
      }, 2000);
      return;
    }
    servoAngle += diff * 0.06;
    servoBaseAngleEl.textContent = `${Math.round(servoAngle)}°`;
    drawServo();
    animFrameId = requestAnimationFrame(step);
  }
  step();
}

// ─── PARTICLE CANVAS ─────────────────────────────────────
const pCanvas = document.getElementById('particleCanvas');
const pCtx = pCanvas.getContext('2d');
let particles = [];

function resizeParticles() {
  pCanvas.width = window.innerWidth;
  pCanvas.height = window.innerHeight;
}

function createParticles() {
  const count = Math.floor((window.innerWidth * window.innerHeight) / 14000);
  particles = Array.from({ length: count }, () => ({
    x: Math.random() * pCanvas.width,
    y: Math.random() * pCanvas.height,
    r: Math.random() * 1.5 + 0.3,
    vx: (Math.random() - 0.5) * 0.3,
    vy: (Math.random() - 0.5) * 0.3,
    alpha: Math.random() * 0.5 + 0.1,
    hue: Math.random() > 0.6 ? 190 : 265,
  }));
}

function animateParticles() {
  pCtx.clearRect(0, 0, pCanvas.width, pCanvas.height);
  for (const p of particles) {
    p.x += p.vx; p.y += p.vy;
    if (p.x < 0) p.x = pCanvas.width;
    if (p.x > pCanvas.width) p.x = 0;
    if (p.y < 0) p.y = pCanvas.height;
    if (p.y > pCanvas.height) p.y = 0;
    pCtx.beginPath();
    pCtx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
    pCtx.fillStyle = `hsla(${p.hue}, 90%, 75%, ${p.alpha})`;
    pCtx.fill();
  }
  requestAnimationFrame(animateParticles);
}

// ─── INIT ─────────────────────────────────────────────────
function init() {
  resizeParticles();
  createParticles();
  animateParticles();

  resizeServoCanvas();
  servoAngle = 180;
  drawServo();

  window.addEventListener('resize', () => {
    resizeParticles();
    createParticles();
    resizeServoCanvas();
  });

  connectMqtt();
}

document.addEventListener('DOMContentLoaded', init);
