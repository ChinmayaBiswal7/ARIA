// ── Firebase Init ────────────────────────────────────────────────────────
const firebaseConfig = {
  apiKey:            "AIzaSyA5l74ebBKR8-veakGNISlwkIdasA-vQaQ",
  authDomain:        "aria-3e1da.firebaseapp.com",
  projectId:         "aria-3e1da",
  storageBucket:     "aria-3e1da.firebasestorage.app",
  messagingSenderId: "968886942490",
  appId:             "1:968886942490:web:8ab8c8a061ae6d79a94aa3"
};
firebase.initializeApp(firebaseConfig);
const db = firebase.firestore();

// ── 3D Particle Sphere class (Cinematic Jarvis Hologram - Optimized) ─────
class SphereCanvas {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.nPoints = 140; // High performance particle count
    this.connectDist = 0.55;
    
    // Generate uniform points on sphere using Fibonacci spiral for neat structures
    this.basePts = [];
    for (let i = 0; i < this.nPoints; i++) {
      let phi = Math.acos(-1 + (2 * i) / this.nPoints);
      let theta = Math.sqrt(this.nPoints * Math.PI) * phi;
      let x = Math.sin(phi) * Math.cos(theta);
      let y = Math.sin(phi) * Math.sin(theta);
      let z = Math.cos(phi);
      this.basePts.push({
        x: x, y: y, z: z,
        speed: 0.5 + Math.random() * 1.5,
        phase: Math.random() * 2 * Math.PI
      });
    }
    
    this.pts = this.basePts.map(p => ({...p}));
    this.ry = 0.0;
    this.rx = 0.12; 
    this.pulse = 1.0;
    this.pdx = 0.008;
    this.time = 0.0;
    this.state = "OFFLINE";
    this.wave = Array(32).fill(0.04);
    
    // Concentric orbits
    this.orbits = [
      { radiusFrac: 1.1, speed: 0.8, dash: [5, 15], angle: 0 },
      { radiusFrac: 1.25, speed: -0.5, dash: [40, 20, 10, 20], angle: 0 },
      { radiusFrac: 1.4, speed: 1.2, dash: [2, 12], angle: 0 }
    ];
    
    this.audioAnalyser = null;
    this.audioDataArray = null;

    // Rich palettes
    this.palettes = {
      "OFFLINE":   { core: "rgba(100, 110, 120, 0.95)", glow: "rgba(40, 45, 50, 0.4)", line: "rgba(80, 90, 100, 0.15)", glowColor: "#646e78" },
      "IDLE":      { core: "rgba(0, 140, 255, 0.95)",  glow: "rgba(0, 70, 180, 0.35)",  line: "rgba(0, 100, 220, 0.12)", glowColor: "#008cff" },
      "LISTENING": { core: "rgba(0, 229, 255, 0.95)",  glow: "rgba(0, 180, 220, 0.45)",  line: "rgba(0, 180, 220, 0.2)",  glowColor: "#00e5ff" },
      "THINKING":  { core: "rgba(255, 140, 0, 0.95)",   glow: "rgba(220, 90, 0, 0.45)",   line: "rgba(220, 100, 0, 0.2)",  glowColor: "#ff8c00" }, 
      "SPEAKING":  { core: "rgba(167, 139, 250, 0.95)", glow: "rgba(139, 92, 246, 0.45)", line: "rgba(124, 58, 237, 0.2)",  glowColor: "#a78bfa" },
      "ERROR":     { core: "rgba(255, 60, 60, 0.95)",   glow: "rgba(180, 20, 20, 0.45)",   line: "rgba(220, 40, 40, 0.2)",  glowColor: "#ff3c3c" }
    };
  }

  setState(state) {
    const canonical = state.toUpperCase();
    if (this.palettes[canonical]) {
      this.state = canonical;
    } else {
      this.state = "IDLE";
    }
  }

  tick() {
    this.time += 0.033;
    
    let speed = 0.005;
    if (this.state === "OFFLINE") speed = 0.001;
    else if (this.state === "IDLE") speed = 0.003;
    else if (this.state === "LISTENING") speed = 0.010;
    else if (this.state === "THINKING") speed = 0.018;
    else if (this.state === "SPEAKING") speed = 0.015;
    else if (this.state === "ERROR") speed = 0.025;
    
    this.ry += speed;

    // Get mic volume level
    let micVolume = 0;
    if (this.audioAnalyser && this.audioDataArray && (this.state === "LISTENING" || this.state === "SPEAKING")) {
      this.audioAnalyser.getByteFrequencyData(this.audioDataArray);
      let sum = 0;
      let count = 0;
      for (let i = 0; i < this.audioDataArray.length; i++) {
        sum += this.audioDataArray[i];
        if (this.audioDataArray[i] > 0) count++;
      }
      micVolume = count > 0 ? (sum / count / 255) : 0;
    }

    if (this.state === "SPEAKING" && micVolume === 0) {
      micVolume = 0.12 + Math.abs(Math.sin(this.time * 6)) * 0.22;
    }

    let pulseSpeed = 0.008;
    let pulseRange = [0.96, 1.04];
    if (this.state === "OFFLINE") { pulseSpeed = 0.002; pulseRange = [0.99, 1.01]; }
    else if (this.state === "IDLE") { pulseSpeed = 0.005; pulseRange = [0.96, 1.04]; }
    else if (this.state === "LISTENING") { pulseSpeed = 0.012; pulseRange = [0.88, 1.12]; }
    else if (this.state === "THINKING") { pulseSpeed = 0.020; pulseRange = [0.92, 1.08]; }
    else if (this.state === "SPEAKING") { pulseSpeed = 0.018; pulseRange = [0.85, 1.15]; }

    this.pulse += pulseSpeed * this.pdx;
    if (this.pulse > pulseRange[1] || this.pulse < pulseRange[0]) {
      this.pdx *= -1;
    }

    this.orbits.forEach(orb => {
      let orbitSpeed = orb.speed * (1.0 + micVolume * 3.0);
      orb.angle = (orb.angle + orbitSpeed) % 360;
    });

    if (this.state === "SPEAKING" || this.state === "LISTENING") {
      let activeVol = micVolume > 0 ? micVolume : 0.05;
      this.wave = this.wave.map((w, i) => {
        return activeVol * (0.6 + Math.random() * 0.4) + Math.abs(Math.sin(this.time * 5 + i * 0.3)) * 0.15;
      });
    } else {
      this.wave = this.wave.map(w => Math.max(0.04, w * 0.88));
    }

    return micVolume;
  }

  draw(micVolume) {
    let w = this.canvas.width;
    let h = this.canvas.height;
    this.ctx.clearRect(0, 0, w, h);

    let pal = this.palettes[this.state];
    let centerX = w / 2;
    let centerY = h / 2;
    let R = Math.min(centerX, centerY) * 0.62 * this.pulse;

    this.ctx.shadowBlur = 0; 

    // 1. Ambient Background glow
    this.ctx.beginPath();
    let bgR = R * 1.5;
    let radGrad = this.ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, bgR);
    radGrad.addColorStop(0, pal.glow.replace("0.35", "0.2").replace("0.45", "0.2"));
    radGrad.addColorStop(1, "rgba(5, 6, 15, 0)");
    this.ctx.fillStyle = radGrad;
    this.ctx.arc(centerX, centerY, bgR, 0, 2*Math.PI);
    this.ctx.fill();

    // 2. Concentric Dashboard Orbit Arcs
    if (this.state !== "OFFLINE") {
      this.orbits.forEach(orb => {
        let rOrb = R * orb.radiusFrac;
        
        this.ctx.beginPath();
        this.ctx.arc(centerX, centerY, rOrb, 0, 2 * Math.PI);
        this.ctx.strokeStyle = pal.line;
        this.ctx.lineWidth = 1;
        this.ctx.setLineDash(orb.dash);
        this.ctx.stroke();
        
        this.ctx.save();
        this.ctx.translate(centerX, centerY);
        this.ctx.rotate(orb.angle * Math.PI / 180);
        
        for (let a = 0; a < 360; a += 120) {
          this.ctx.beginPath();
          this.ctx.arc(0, 0, rOrb, (a - 6) * Math.PI / 180, (a + 6) * Math.PI / 180);
          this.ctx.strokeStyle = pal.core;
          this.ctx.lineWidth = 2.5;
          this.ctx.setLineDash([]);
          this.ctx.stroke();
        }
        this.ctx.restore();
      });
      this.ctx.setLineDash([]); 
    }

    // 3. Project 3D Nodes
    let projected = this.basePts.map(bp => {
      let cy = Math.cos(this.ry), sy = Math.sin(this.ry);
      let rx1 = bp.x * cy + bp.z * sy;
      let ry1 = bp.y;
      let rz1 = -bp.x * sy + bp.z * cy;

      let cx = Math.cos(this.rx), sx = Math.sin(this.rx);
      let rx2 = rx1;
      let ry2 = ry1 * cx - rz1 * sx;
      let rz2 = ry1 * sx + rz1 * cx;

      let displacement = 1.0;
      if (this.state === "LISTENING" || this.state === "SPEAKING") {
        let rippleOffset = Math.sin(this.time * 20 * bp.speed + bp.phase);
        displacement = 1.0 + (rippleOffset * micVolume * 0.10) + (micVolume * 0.12);
      } else {
        displacement = 1.0 + Math.sin(this.time * 2 * bp.speed + bp.phase) * 0.02;
      }

      let sizeFactor = 1.0 + micVolume * 1.2;

      return {
        x: centerX + rx2 * R * displacement,
        y: centerY - ry2 * R * displacement,
        z: rz2,
        size: sizeFactor
      };
    });

    // 4. Draw mesh lines (Optimized connections - only in foreground)
    for (let i = 0; i < projected.length; i += 3) {
      if (projected[i].z < -0.25) continue;
      
      for (let j = i + 1; j < projected.length; j += 4) {
        if (projected[j].z < -0.25) continue;
        
        let dx = this.basePts[i].x - this.basePts[j].x;
        let dy = this.basePts[i].y - this.basePts[j].y;
        let dz = this.basePts[i].z - this.basePts[j].z;
        let dist = Math.sqrt(dx*dx + dy*dy + dz*dz);

        if (dist < this.connectDist) {
          let zAvg = (projected[i].z + projected[j].z) / 2;
          let alpha = Math.max(0, Math.min(0.2, (zAvg + 1) * 0.08 + 0.01)) * (1.0 + micVolume * 1.5);
          
          this.ctx.beginPath();
          this.ctx.moveTo(projected[i].x, projected[i].y);
          this.ctx.lineTo(projected[j].x, projected[j].y);
          this.ctx.strokeStyle = pal.line.replace("0.2", alpha).replace("0.12", alpha);
          this.ctx.lineWidth = 0.5;
          this.ctx.stroke();
        }
      }
    }

    // 5. Draw dots
    let sortedIndices = Array.from({length: projected.length}, (_, i) => i)
                             .sort((a, b) => projected[a].z - projected[b].z);

    sortedIndices.forEach(idx => {
      let p = projected[idx];
      let brightness = (p.z + 1) / 2; 
      let size = Math.max(1.0, 3.0 * brightness * p.size);
      let alpha = (0.2 + 0.8 * brightness) * (this.state === "OFFLINE" ? 0.3 : 1.0);
      
      this.ctx.beginPath();
      this.ctx.arc(p.x, p.y, size / 2, 0, 2 * Math.PI);
      this.ctx.fillStyle = pal.core.replace("0.95", alpha);
      this.ctx.fill();
    });

    // 6. Central Morphing Core
    let coreR = R * 0.22;
    let coreGlow = coreR * (1.2 + micVolume * 2.0);
    
    let grad = this.ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, coreGlow);
    grad.addColorStop(0, pal.core.replace("0.95", "0.9"));
    grad.addColorStop(0.3, pal.core.replace("0.95", "0.4"));
    grad.addColorStop(1, "rgba(5, 6, 15, 0)");
    
    this.ctx.beginPath();
    this.ctx.arc(centerX, centerY, coreGlow, 0, 2 * Math.PI);
    this.ctx.fillStyle = grad;
    this.ctx.fill();

    // 7. Radial Equalizer sweeper lines
    if (this.state === "SPEAKING" || this.state === "LISTENING") {
      let spikeCount = 30;
      let angleStep = (2 * Math.PI) / spikeCount;
      
      this.ctx.lineWidth = 1.0;
      this.ctx.strokeStyle = pal.line.replace("0.2", "0.35").replace("0.12", "0.35");

      for (let i = 0; i < spikeCount; i++) {
        let angle = i * angleStep + this.time * 0.5;
        let waveAmp = this.wave[i % this.wave.length];
        
        let startR = R * 0.95;
        let endR = R * (0.95 + waveAmp * 0.6);
        
        let sx = centerX + Math.cos(angle) * startR;
        let sy = centerY + Math.sin(angle) * startR;
        let ex = centerX + Math.cos(angle) * endR;
        let ey = centerY + Math.sin(angle) * endR;
        
        this.ctx.beginPath();
        this.ctx.moveTo(sx, sy);
        this.ctx.lineTo(ex, ey);
        this.ctx.stroke();
      }
    }
  }
}

class BackgroundParticles {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.particles = [];
    this.resize();
    window.addEventListener('resize', () => this.resize());
    this.init();
  }
  resize() {
    this.canvas.width = window.innerWidth;
    this.canvas.height = window.innerHeight;
  }
  init() {
    const count = Math.min(50, Math.floor((window.innerWidth * window.innerHeight) / 25000));
    this.particles = [];
    for (let i = 0; i < count; i++) {
      this.particles.push({
        x: Math.random() * this.canvas.width,
        y: Math.random() * this.canvas.height,
        vx: (Math.random() - 0.5) * 0.35,
        vy: (Math.random() - 0.5) * 0.35,
        r: 1 + Math.random() * 2
      });
    }
  }
  tick() {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    
    // Update & Draw
    for (let i = 0; i < this.particles.length; i++) {
      let p = this.particles[i];
      p.x += p.vx;
      p.y += p.vy;
      
      if (p.x < 0 || p.x > this.canvas.width) p.vx *= -1;
      if (p.y < 0 || p.y > this.canvas.height) p.vy *= -1;
      
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(0, 229, 255, 0.18)';
      ctx.fill();
    }
    
    // Connections
    ctx.strokeStyle = 'rgba(0, 229, 255, 0.04)';
    ctx.lineWidth = 1;
    for (let i = 0; i < this.particles.length; i++) {
      for (let j = i + 1; j < this.particles.length; j++) {
        let p1 = this.particles[i];
        let p2 = this.particles[j];
        let dist = Math.hypot(p1.x - p2.x, p1.y - p2.y);
        if (dist < 130) {
          ctx.beginPath();
          ctx.moveTo(p1.x, p1.y);
          ctx.lineTo(p2.x, p2.y);
          ctx.stroke();
        }
      }
    }
  }
}

const canvas = document.getElementById("sphere-canvas");
const sphere = new SphereCanvas(canvas);

const bgCanvas = document.getElementById("bg-particles");
const bgParticles = new BackgroundParticles(bgCanvas);

function animate() {
  let vol = sphere.tick();
  sphere.draw(vol);
  bgParticles.tick();
  requestAnimationFrame(animate);
}
requestAnimationFrame(animate);

// ── Audio & Always-On Mic Logic ──────────────────────────────────────────
let isInitialized = false;
let audioContext, analyser, dataArray, micStream;
let recognition;
let shouldListen = false;

// Speech Synthesizer
function speakText(text) {
  if (!isInitialized || !window.speechSynthesis) return;
  window.speechSynthesis.cancel(); 
  
  let cleanText = text.replace(/\[[A-Z]+:[^\]]*\]/g, "");
  cleanText = cleanText.replace(/\[[A-Z]+\]/g, "").trim();
  if (!cleanText) return;

  const utterance = new SpeechSynthesisUtterance(cleanText);
  utterance.lang = "en-US";
  
  const voices = window.speechSynthesis.getVoices();
  const naturalVoice = voices.find(v => v.lang.includes("en-US") && (v.name.includes("Google") || v.name.includes("Natural"))) ||
                      voices.find(v => v.lang.includes("en-US")) ||
                      voices[0];
  if (naturalVoice) utterance.voice = naturalVoice;

  utterance.onstart = () => {
    sphere.setState("speaking");
  };
  
  utterance.onend = () => {
    if (shouldListen) sphere.setState("listening");
  };
  
  window.speechSynthesis.speak(utterance);
}

// Activate remote (triggered by tapping the sphere)
async function initializeRemote() {
  if (isInitialized) return;

  const overlay = document.getElementById("activation-overlay");
  const connDot = document.getElementById("conn-dot");
  const hubState = document.getElementById("hub-state");
  const statusDisp = document.getElementById("status-display");

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    showToast("Text-only mode active");
    if (statusDisp) statusDisp.textContent = "Microphone API not supported. Text-only control active.";
    isInitialized = true;
    if (overlay) overlay.classList.add("hidden");
    return;
  }

  try {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const source = audioContext.createMediaStreamSource(micStream);
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 64;
    source.connect(analyser);
    
    const bufferLength = analyser.frequencyBinCount;
    dataArray = new Uint8Array(bufferLength);
    
    sphere.audioAnalyser = analyser;
    sphere.audioDataArray = dataArray;

    try {
      if ("webkitSpeechRecognition" in window || "SpeechRecognition" in window) {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        recognition = new SR();
        recognition.continuous = true;
        recognition.interimResults = false;
        recognition.lang = "en-US";

        recognition.onstart = () => {
          shouldListen = true;
          sphere.setState("listening");
          if (hubState) {
            hubState.textContent = "LISTENING";
            hubState.style.color = "var(--green)";
          }
        };

        recognition.onend = () => {
          if (shouldListen) {
            try {
              recognition.start();
            } catch(e) {}
          }
        };

        recognition.onerror = (e) => {
          console.log("Speech recognition error: ", e);
          if (shouldListen && e.error !== "not-allowed") {
            setTimeout(() => {
              try { recognition.start(); } catch(err) {}
            }, 400);
          }
        };

        recognition.onresult = e => {
          const resultIdx = e.resultIndex;
          const t = e.results[resultIdx][0].transcript;
          
          if (t.trim()) {
            showToast('Speech: "' + t + '"');
            sendCommand(t);
          }
        };
      } else {
        showToast("Speech recognition not supported on this browser.");
      }
    } catch (srErr) {
      console.error("SpeechRecognition setup failed:", srErr);
      showToast("Speech recognition unavailable.");
      recognition = null;
    }

    isInitialized = true;
    shouldListen = true;
    
    if (overlay) overlay.classList.add("hidden");
    if (connDot) connDot.className = "status-dot waiting";
    
    speakText("Aria remote online.");
    if (statusDisp) statusDisp.textContent = "Aria remote online. Connected.";

    if (recognition) {
      try {
        recognition.start();
      } catch (startErr) {
        console.error("SpeechRecognition start failed:", startErr);
        showToast("Voice recognition failed to start.");
      }
    }

  } catch (err) {
    console.error("Initialization failed: ", err);
    showToast("Mic permission denied. Using text control.");
    if (statusDisp) statusDisp.textContent = "Microphone access denied. Voice controls disabled, but you can still use the console and shortcuts.";
    isInitialized = true;
    if (overlay) overlay.classList.add("hidden");
  }
}

// ── Live Firestore Status Listener ───────────────────────────────────────
function connectFirestore() {
  const connDot    = document.getElementById("conn-dot");
  const hubState   = document.getElementById("hub-state");
  const statusDisp = document.getElementById("status-display");

  let lastSpokenText = "";

  db.collection("status").doc("latest").onSnapshot(doc => {
    if (!doc.exists) return;
    const d = doc.data();
    if (connDot) connDot.className = "status-dot";

    if (statusDisp) statusDisp.textContent = d.last_response || "Connected.";
    
    const rawState = d.status || "idle";
    
    if (rawState !== "speaking") {
      sphere.setState(rawState);
      if (hubState) hubState.textContent = rawState.toUpperCase();
    }

    if (hubState) {
      if (rawState === "thinking") {
        hubState.style.color = "rgba(var(--yellow-rgb), 1)";
      } else if (rawState === "listening") {
        hubState.style.color = "var(--green)";
      } else if (rawState === "speaking") {
        hubState.style.color = "rgba(var(--purple-rgb), 1)";
      } else {
        hubState.style.color = "var(--accent)";
      }
    }

    if (d.last_response && d.last_response !== lastSpokenText) {
      if (d.status === "speaking" || (d.status === "idle" && !d.last_response.startsWith("Executing:") && !d.last_response.startsWith("Done:") && !d.last_response.startsWith("Error:"))) {
        speakText(d.last_response);
        lastSpokenText = d.last_response;
      }
    }
  }, err => {
    if (connDot) connDot.className = "status-dot offline";
    if (hubState) {
      hubState.textContent = "OFFLINE";
      hubState.style.color = "var(--red)";
    }
    sphere.setState("error");
  });
}

connectFirestore();

// ── Send Command ─────────────────────────────────────────────────────────
function sendCommand(text) {
  if (!text.trim()) return;
  return db.collection("commands").doc("latest").set({
    id:        "cmd_" + Date.now(),
    text:      text.trim(),
    timestamp: Date.now()
  });
}

function sendCustomCommand() {
  const el = document.getElementById("cmd-input");
  if (!el) return;
  const t  = el.value.trim();
  if (!t) return;
  sendCommand(t).then(() => showToast('Sent: "' + t + '"'));
  el.value = "";
}

const cmdInput = document.getElementById("cmd-input");
if (cmdInput) {
  cmdInput.addEventListener("keydown", e => {
    if (e.key === "Enter") sendCustomCommand();
  });
}

function sendMacro(el, cmd) {
  sendCommand(cmd).then(() => {
    el.classList.add("sent");
    setTimeout(() => el.classList.remove("sent"), 1200);
    showToast('Sent: "' + cmd + '"');
  });
}

function sendCtrl(cmd) {
  sendCommand(cmd).then(() => showToast(cmd));
}

// Smooth scroll
document.querySelectorAll('.scroll-indicator').forEach(anchor => {
  anchor.addEventListener('click', function (e) {
    e.preventDefault();
    const target = document.querySelector(this.getAttribute('href'));
    if (target) {
      target.scrollIntoView({
        behavior: 'smooth'
      });
    }
  });
});

let _toastTimer;
function showToast(msg) {
  const t = document.getElementById("toast");
  if (t) {
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => t.classList.remove("show"), 2200);
  }
}
