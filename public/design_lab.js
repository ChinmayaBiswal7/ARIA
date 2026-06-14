// ── WEB AUDIO SYNTHESIZER ──
const audioCtx = new (window.AudioContext || window.webkitAudioContext)();

function playSound(type) {
  if (audioCtx.state === 'suspended') {
    audioCtx.resume();
  }
  const osc = audioCtx.createOscillator();
  const gain = audioCtx.createGain();
  osc.connect(gain);
  gain.connect(audioCtx.destination);

  if (type === 'beep') {
    osc.frequency.setValueAtTime(1200, audioCtx.currentTime);
    gain.gain.setValueAtTime(0.05, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + 0.08);
    osc.start();
    osc.stop(audioCtx.currentTime + 0.08);
  } else if (type === 'double') {
    osc.frequency.setValueAtTime(1000, audioCtx.currentTime);
    gain.gain.setValueAtTime(0.05, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + 0.1);
    osc.start();
    osc.stop(audioCtx.currentTime + 0.1);
    
    setTimeout(() => {
      const osc2 = audioCtx.createOscillator();
      const gain2 = audioCtx.createGain();
      osc2.connect(gain2);
      gain2.connect(audioCtx.destination);
      osc2.frequency.setValueAtTime(1500, audioCtx.currentTime);
      gain2.gain.setValueAtTime(0.05, audioCtx.currentTime);
      gain2.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + 0.15);
      osc2.start();
      osc2.stop(audioCtx.currentTime + 0.15);
    }, 120);
  } else if (type === 'success') {
    osc.type = 'triangle';
    osc.frequency.setValueAtTime(800, audioCtx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(1800, audioCtx.currentTime + 0.25);
    gain.gain.setValueAtTime(0.05, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + 0.25);
    osc.start();
    osc.stop(audioCtx.currentTime + 0.25);
  } else if (type === 'error') {
    osc.type = 'sawtooth';
    osc.frequency.setValueAtTime(150, audioCtx.currentTime);
    gain.gain.setValueAtTime(0.1, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + 0.3);
    osc.start();
    osc.stop(audioCtx.currentTime + 0.3);
  }
}

// ── TOAST NOTIFICATION HELPERS ──
function showToast(msg, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type === 'warn' ? 'warn' : ''}`;
  toast.innerHTML = `<span>//</span> <span>${msg}</span>`;
  container.appendChild(toast);
  
  playSound(type === 'warn' ? 'error' : 'beep');

  setTimeout(() => {
    toast.style.animation = 'slideOut 0.3s forwards';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// ── SPEECH RECOGNITION (Web Speech API dictation & Hands-Free) ──
let speechRecognition;
let isListeningSpeech = false;

function initSpeechRecognition() {
  const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Speech) return;
  speechRecognition = new Speech();
  speechRecognition.continuous = false;
  speechRecognition.interimResults = false;
  speechRecognition.lang = 'en-US';

  speechRecognition.onstart = () => {
    isListeningSpeech = true;
    const btn = document.getElementById('btn-mic-dictate');
    if (btn) btn.classList.add('listening');
    showToast("Holographic micro-dictation starting...");
  };

  speechRecognition.onend = () => {
    isListeningSpeech = false;
    const btn = document.getElementById('btn-mic-dictate');
    if (btn) btn.classList.remove('listening');
  };

  speechRecognition.onerror = (e) => {
    showToast("Microphone capture issue: " + e.error, "warn");
  };

  speechRecognition.onresult = (e) => {
    const text = e.results[0][0].transcript;
    const input = document.getElementById('console-cmd-input');
    if (input) input.value = text;
    pushConsoleLog("User Dictated", text);
    sendConsoleCommand();
  };
}

function toggleVoiceSpeech() {
  if (!speechRecognition) {
    initSpeechRecognition();
  }
  if (!speechRecognition) {
    showToast("Your browser does not support local SpeechRecognition.", "warn");
    return;
  }
  if (isListeningSpeech) {
    speechRecognition.stop();
  } else {
    if (isHandsFree) stopHandsFree();
    speechRecognition.start();
  }
}

// ── CONTINUOUS HANDS-FREE MODE (Wake Word: ARIA) ──
let isHandsFree = false;
let handsFreeRecognition = null;

function initHandsFreeRecognition() {
  const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Speech) return;
  
  handsFreeRecognition = new Speech();
  handsFreeRecognition.continuous = true;
  handsFreeRecognition.interimResults = false;
  handsFreeRecognition.lang = 'en-US';

  handsFreeRecognition.onstart = () => {
    const btn = document.getElementById('btn-mic-handsfree');
    if (btn) btn.classList.add('listening-handsfree');
    const status = document.getElementById('hdr-status');
    if (status) {
      status.textContent = 'LISTENING';
      status.style.color = 'var(--accent)';
    }
  };

  handsFreeRecognition.onend = () => {
    if (isHandsFree) {
      try {
        handsFreeRecognition.start();
      } catch(err) {
        console.log("Speech restart ignored:", err);
      }
    } else {
      const btn = document.getElementById('btn-mic-handsfree');
      if (btn) btn.classList.remove('listening-handsfree');
      const status = document.getElementById('hdr-status');
      if (status) {
        status.textContent = 'IDLE';
        status.style.color = 'var(--warn)';
      }
    }
  };

  handsFreeRecognition.onerror = (e) => {
    console.warn("Hands-free mic error:", e.error);
    if (e.error === 'not-allowed') {
      showToast("Mic permission required for hands-free mode.", "warn");
      stopHandsFree();
    }
  };

  handsFreeRecognition.onresult = (e) => {
    const lastResultIndex = e.results.length - 1;
    const rawText = e.results[lastResultIndex][0].transcript.trim();
    if (!rawText) return;
    
    const textLower = rawText.toLowerCase();
    const wakeIdx = textLower.indexOf("aria");
    
    if (wakeIdx !== -1) {
      let command = rawText.substring(wakeIdx + 4).trim();
      command = command.replace(/^[,.\-\s]+/, '');
      
      if (command.length > 0) {
        pushConsoleLog("User (Voice)", command);
        executeHandsFreeCommand(command);
      } else {
        playSound('beep');
        showToast("ARIA: Listening...");
      }
    }
  };
}

async function executeHandsFreeCommand(cmd) {
  const status = document.getElementById('hdr-status');
  if (status) {
    status.textContent = 'COMPUTING';
    status.style.color = 'var(--accent)';
  }
  await sendCommand(cmd);
}

function toggleHandsFree() {
  if (!handsFreeRecognition) {
    initHandsFreeRecognition();
  }
  if (!handsFreeRecognition) {
    showToast("Your browser does not support SpeechRecognition.", "warn");
    return;
  }
  
  if (isHandsFree) {
    stopHandsFree();
  } else {
    startHandsFree();
  }
}

function startHandsFree() {
  if (speechRecognition && isListeningSpeech) {
    speechRecognition.stop();
  }
  isHandsFree = true;
  try {
    handsFreeRecognition.start();
  } catch(err) {
    console.error(err);
  }
  showToast("Hands-free active // Say 'ARIA' followed by command");
  playSound('double');
}

function stopHandsFree() {
  isHandsFree = false;
  if (handsFreeRecognition) {
    try {
      handsFreeRecognition.stop();
    } catch(err) {
      console.error(err);
    }
  }
  const btn = document.getElementById('btn-mic-handsfree');
  if (btn) btn.classList.remove('listening-handsfree');
  showToast("Hands-free system offline.");
  playSound('beep');
}

// ── VOCAL RESPONSE SYNTHESIS (TTS confirmation feedback) ──
function speakVocalResponse(text) {
  if (!window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  
  const utterance = new SpeechSynthesisUtterance(text);
  const voices = window.speechSynthesis.getVoices();
  
  const preferred = voices.find(v => v.name.includes("Google") || v.name.includes("Natural") || v.name.includes("Zira") || v.name.includes("Hazel"));
  if (preferred) utterance.voice = preferred;
  
  utterance.rate = 1.05;
  utterance.pitch = 1.0;
  utterance.volume = 0.55;
  
  window.speechSynthesis.speak(utterance);
}

// ── MAIN STATE ──
let activeComponent = 'body';
let designData = null;
let viewMode = 'solid'; // solid, wire, xray
let isExploded = false;

// ── THREE.JS SETUP ──
const canvas = document.getElementById('canvas3d');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(canvas.clientWidth, canvas.clientHeight);
renderer.shadowMap.enabled = true;

const scene = new THREE.Scene();

const camera = new THREE.PerspectiveCamera(40, canvas.clientWidth / canvas.clientHeight, 0.1, 100);
camera.position.set(3.0, 1.0, 4.0);

const controls = new THREE.OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.05;
controls.maxPolarAngle = Math.PI / 2 - 0.02; // don't go below ground grid
controls.target.set(0, 0.5, 0); // focus on the suit/object center rather than grid floor

// Lights
let ambientLight = new THREE.AmbientLight(0x0a1530, 1.5);
scene.add(ambientLight);

let keyLight = new THREE.DirectionalLight(0x00f0ff, 1.5);
keyLight.position.set(5, 10, 5);
scene.add(keyLight);

let fillLight = new THREE.DirectionalLight(0xff6c00, 0.4);
fillLight.position.set(-5, 5, -5);
scene.add(fillLight);

let pointLight = new THREE.PointLight(0x00f0ff, 2, 10);
pointLight.position.set(0, 1, 0);
scene.add(pointLight);

// Cyber grid ground
let gridHelper = null;
function rebuildGridHelper() {
  if (gridHelper) scene.remove(gridHelper);
  const color1 = 0x00f0ff; // center line: bright cyan
  const color2 = 0x0a1e3f; // grid lines: deep cyber blue
  gridHelper = new THREE.GridHelper(20, 20, color1, color2);
  gridHelper.position.y = -0.45;
  scene.add(gridHelper);
}

function updateSceneTheme() {
  // Always use dark cyber-studio lights to match the hologram mockup
  ambientLight.color.setHex(0x0a1530);
  ambientLight.intensity = 1.5;
  keyLight.color.setHex(0x00f0ff);
  keyLight.intensity = 1.5;
  fillLight.color.setHex(0xff6c00);
  fillLight.intensity = 0.4;
  pointLight.color.setHex(0x00f0ff);
  pointLight.intensity = 2.0;
  rebuildGridHelper();
}

// Initialize default grid helper and lights
rebuildGridHelper();
updateSceneTheme();

// Main design group
const carGroup = new THREE.Group();
scene.add(carGroup);

// Geometries & Materials variables
const meshes = {};
let airflowSystem = null;

// Rebuild Three.js scene dynamically from component parameters
function rebuildThreeScene() {
  if (!designData) return;
  
  // Clear old meshes
  while (carGroup.children.length > 0) {
    carGroup.remove(carGroup.children[0]);
  }

  // Clear old meshes cache
  for (let k in meshes) {
    delete meshes[k];
  }
  
  const comps = designData.components;
  for (let key in comps) {
    const comp = comps[key];
    
    let mat;
    let showWireframeOverlay = true;
    
    // Simulation color mappings
    const stabilityBtn = document.getElementById('btn-sim-stability');
    const thermalBtn = document.getElementById('btn-sim-thermal');
    const hasStability = stabilityBtn && stabilityBtn.classList.contains('active');
    const hasThermal = thermalBtn && thermalBtn.classList.contains('active');

    if (hasStability && (key === getPrimaryComponentKey())) {
      mat = stressMaterial;
      showWireframeOverlay = false;
    } else if (hasThermal && (key === getHeatSourceComponentKey())) {
      mat = thermalMaterial;
      showWireframeOverlay = false;
    } else {
      // Stark Cyber-Hologram Material Stack: cyan-blue translucent fill
      let baseColor = 0x0088ff;
      let emissiveColor = 0x00f0ff;
      let emissiveInt = 0.7;
      let fillOpacity = 0.25;
      
      const isSelected = (key === activeComponent);
      const isReactor = (key === 'arc_reactor' || key === 'engine' || key.toLowerCase().includes('reactor') || key.toLowerCase().includes('engine'));
      
      if (isSelected) {
        baseColor = 0xff5500; // orange for selected
        emissiveColor = 0xff6c00;
        emissiveInt = 1.0;
        fillOpacity = 0.4;
      } else if (isReactor) {
        baseColor = 0x00ffff; // bright cyan/white-hot for reactor
        emissiveColor = 0xffffff;
        emissiveInt = 1.2;
        fillOpacity = 0.45;
      }
      
      mat = new THREE.MeshPhongMaterial({
        color: baseColor,
        emissive: emissiveColor,
        emissiveIntensity: emissiveInt,
        transparent: true,
        opacity: fillOpacity,
        depthWrite: false,
        blending: THREE.NormalBlending,
        side: THREE.DoubleSide
      });
      
      if (viewMode === 'wire') {
        mat.wireframe = true;
        mat.transparent = true;
        mat.opacity = 0.9;
        showWireframeOverlay = false;
      } else if (viewMode === 'xray') {
        mat.wireframe = false;
        mat.transparent = true;
        mat.opacity = isSelected ? 0.2 : (isReactor ? 0.22 : 0.12);
        mat.depthWrite = false;
        mat.blending = THREE.AdditiveBlending;
      }
    }
    
    let mesh;
    
    if (comp.type === 'wheels' || key === 'wheels') {
      const wheelsGroup = new THREE.Group();
      const r = comp.radius || 0.45;
      const w = comp.width || 0.3;
      const wGeo = new THREE.CylinderGeometry(r, r, w, 24);
      wGeo.rotateZ(Math.PI / 2);
      
      const wb = comps.chassis ? (comps.chassis.wheelbase || 2.8) / 2.0 : 1.4;
      
      const fl = new THREE.Mesh(wGeo, mat); fl.position.set(-1.0, -0.1, wb);
      const fr = fl.clone(); fr.position.x = 1.0;
      const rl = fl.clone(); rl.position.set(-1.0, -0.1, -wb);
      const rr = rl.clone(); rr.position.x = 1.0;
      
      wheelsGroup.add(fl); wheelsGroup.add(fr); wheelsGroup.add(rl); wheelsGroup.add(rr);
      mesh = wheelsGroup;
    } else if (comp.type === 'spoiler' || key === 'spoiler') {
      const spGroup = new THREE.Group();
      const size = comp.size || 1.0;
      const wingGeo = new THREE.BoxGeometry(2.2 * size, 0.05, 0.5);
      const wing = new THREE.Mesh(wingGeo, mat); wing.position.y = 0.5;
      
      const pillarGeo = new THREE.BoxGeometry(0.1, 0.5, 0.1);
      const leftP = new THREE.Mesh(pillarGeo, mat); leftP.position.set(-0.8 * size, 0.25, 0);
      const rightP = leftP.clone(); rightP.position.x = 0.8 * size;
      
      spGroup.add(wing); spGroup.add(leftP); spGroup.add(rightP);
      mesh = spGroup;
    } else if (comp.type === 'sphere') {
      const r = comp.radius || 0.5;
      const geo = new THREE.SphereGeometry(r, 32, 32);
      mesh = new THREE.Mesh(geo, mat);
    } else if (comp.type === 'capsule') {
      const r = comp.radius || 0.4;
      const len = comp.length || 1.0;
      const capGroup = new THREE.Group();
      const cylGeo = new THREE.CylinderGeometry(r, r, len, 24);
      const cyl = new THREE.Mesh(cylGeo, mat);
      const sphGeo = new THREE.SphereGeometry(r, 24, 24);
      const topSph = new THREE.Mesh(sphGeo, mat); topSph.position.y = len/2;
      const botSph = new THREE.Mesh(sphGeo, mat); botSph.position.y = -len/2;
      capGroup.add(cyl); capGroup.add(topSph); capGroup.add(botSph);
      mesh = capGroup;
    } else if (comp.type === 'cone') {
      const r = comp.radius || 0.5;
      const len = comp.length || 1.0;
      const geo = new THREE.ConeGeometry(r, len, 32);
      mesh = new THREE.Mesh(geo, mat);
    } else if (comp.type === 'cylinder') {
      const r = comp.radius || 0.3;
      const len = comp.length || comp.height || 1.0;
      const geo = new THREE.CylinderGeometry(r, r, len, 32);
      mesh = new THREE.Mesh(geo, mat);
    } else {
      const l = comp.length || 1.0;
      const w = comp.width || 1.0;
      const h = comp.height || comp.radius || 1.0;
      const geo = new THREE.BoxGeometry(l, h, w);
      mesh = new THREE.Mesh(geo, mat);
    }
    
    mesh.position.set(comp.pos_x || 0, comp.pos_y || 0, comp.pos_z || 0);
    mesh.rotation.y = comp.rot_y || 0;
    
    mesh.name = key;
    mesh.userData = { componentKey: key };
    mesh.traverse(child => {
      child.name = key;
      child.userData = { componentKey: key };
    });
    
    // Add detailed edges outlines for Stark-style hologram contours
    if (mesh && showWireframeOverlay) {
      const meshesToClone = [];
      mesh.traverse(child => {
        if (child.isMesh && !child.userData.isEdgeOutline) {
          meshesToClone.push(child);
        }
      });
      
      meshesToClone.forEach(child => {
        const isSelected = (key === activeComponent);
        const isReactor = (key === 'arc_reactor' || key === 'engine' || key.toLowerCase().includes('reactor') || key.toLowerCase().includes('engine'));
        
        let outlineColor = 0x00f0ff;
        if (isSelected) {
          outlineColor = 0xff9900; // Orange outlines for selected
        } else if (isReactor) {
          outlineColor = 0xffffff; // White outlines for reactor
        }
        
        const edgesGeo = new THREE.EdgesGeometry(child.geometry);
        const lineMat = new THREE.LineBasicMaterial({
          color: outlineColor,
          transparent: true,
          opacity: (viewMode === 'xray') ? 0.3 : 1.0,
          blending: THREE.AdditiveBlending
        });
        const edgeLines = new THREE.LineSegments(edgesGeo, lineMat);
        edgeLines.userData = { isEdgeOutline: true };
        child.add(edgeLines);
      });
    }
    
    meshes[key] = mesh;
  }

  // Assemble hierarchy
  for (let key in comps) {
    const comp = comps[key];
    const mesh = meshes[key];
    if (!mesh) continue;

    if (comp.parent && meshes[comp.parent]) {
      meshes[comp.parent].add(mesh);
    } else {
      carGroup.add(mesh);
    }
  }
  
  if (comMesh) {
    const primaryKey = getPrimaryComponentKey();
    const secondaryKey = getHeatSourceComponentKey();
    const pMesh = meshes[primaryKey];
    const sMesh = meshes[secondaryKey];
    if (pMesh) {
      const pZ = pMesh.position.z;
      const sZ = sMesh ? sMesh.position.z : 0;
      comMesh.position.set(0, 0.1, (pZ + sZ) / 2.0);
    }
  }
}

rebuildThreeScene();

// Raycast selector for Three.js click events
const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();

window.addEventListener('click', (e) => {
  // limit intersection to viewport bounds
  const rect = renderer.domElement.getBoundingClientRect();
  if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) {
    return;
  }
  mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
  mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

  raycaster.setFromCamera(mouse, camera);
  
  // test intersection with all component objects
  const intersects = raycaster.intersectObjects(carGroup.children, true);
  if (intersects.length > 0) {
    let hitObject = intersects[0].object;
    // find group parent if inside sub-group
    let parent = hitObject;
    while (parent.parent && parent.parent !== carGroup) {
      parent = parent.parent;
    }
    
    // Match key
    for (let key in meshes) {
      if (meshes[key] === parent) {
        selectComponent(key);
        playSound('beep');
        break;
      }
    }
  }
});

// ── AIRFLOW PARTICLE SYSTEM (Wind tunnel simulation) ──
function createAirflowSystem() {
  const particleCount = 200;
  const geo = new THREE.BufferGeometry();
  const positions = new Float32Array(particleCount * 3);
  const speeds = [];

  for(let i=0; i<particleCount; i++) {
    // distribute along front X & Y plane
    positions[i*3] = (Math.random() - 0.5) * 3.0; // X
    positions[i*3+1] = Math.random() * 1.5;       // Y
    positions[i*3+2] = 4.0 + Math.random() * 4.0; // Z
    speeds.push(0.08 + Math.random() * 0.05);
  }

  geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  const mat = new THREE.PointsMaterial({
    color: 0x00f0ff,
    size: 0.12,
    transparent: true,
    opacity: 0.6,
    blending: THREE.AdditiveBlending
  });

  const points = new THREE.Points(geo, mat);
  airflowSystem = { points, speeds, count: particleCount };
  scene.add(points);
  points.visible = false;
}

createAirflowSystem();

function updateAirflow() {
  if (!airflowSystem || !airflowSystem.points.visible) return;
  const positions = airflowSystem.points.geometry.attributes.position.array;
  const speeds = airflowSystem.speeds;
  
  for(let i=0; i<airflowSystem.count; i++) {
    // flow Z backwards
    positions[i*3+2] -= speeds[i];
    
    // bend Y upwards based on proximity to car center
    const z = positions[i*3+2];
    const x = positions[i*3];
    if (z > -2 && z < 2 && Math.abs(x) < 1.0) {
      // push particle up smoothly around cockpit curve
      positions[i*3+1] += (0.8 - positions[i*3+1]) * 0.03;
    }

    // reset when behind car
    if (positions[i*3+2] < -4.0) {
      positions[i*3] = (Math.random() - 0.5) * 3.0;
      positions[i*3+1] = Math.random() * 1.5;
      positions[i*3+2] = 4.0;
    }
  }
  airflowSystem.points.geometry.attributes.position.needsUpdate = true;
}

// ── STABILITY HEAT MAP & THERMAL GRADIENT SHADERS ──
const stressMaterial = new THREE.MeshStandardMaterial({
  color: 0xff3300,
  wireframe: true,
  roughness: 0.5,
  metalness: 0.5
});

const thermalMaterial = new THREE.MeshPhysicalMaterial({
  color: 0xffa500,
  emissive: 0xff3300,
  emissiveIntensity: 0.5,
  roughness: 0.3
});

// Weight center of mass indicator
const comGeometry = new THREE.SphereGeometry(0.12, 16, 16);
const comMaterial = new THREE.MeshBasicMaterial({ color: 0xff6c00, transparent: true, opacity: 0 });
const comMesh = new THREE.Mesh(comGeometry, comMaterial);
scene.add(comMesh);

// Update materials and edge outline properties dynamically
function updateMaterialsTheme() {
  for (let key in meshes) {
    const m = meshes[key];
    if (!m) continue;
    
    m.traverse(child => {
      if (child.isMesh) {
        const mat = child.material;
        if (!mat) return;
        
        // Check if it is a simulation material
        if (mat === stressMaterial || mat === thermalMaterial) return;
        
        const compKey = child.userData.componentKey || key;
        const isSelected = (compKey === activeComponent);
        const isReactor = (compKey === 'arc_reactor' || compKey === 'engine' || compKey.toLowerCase().includes('reactor') || compKey.toLowerCase().includes('engine'));
        
        let baseColor = 0x0088ff;
        let emissiveColor = 0x00f0ff;
        let emissiveInt = 0.7;
        let fillOpacity = 0.25;
        
        if (isSelected) {
          baseColor = 0xff5500;
          emissiveColor = 0xff6c00;
          emissiveInt = 1.0;
          fillOpacity = 0.4;
        } else if (isReactor) {
          baseColor = 0x00ffff;
          emissiveColor = 0xffffff;
          emissiveInt = 1.2;
          fillOpacity = 0.45;
        }
        
        mat.color.setHex(baseColor);
        mat.emissive.setHex(emissiveColor);
        mat.emissiveIntensity = emissiveInt;
        mat.transparent = true;
        mat.depthWrite = false;
        mat.blending = THREE.NormalBlending;
        mat.wireframe = (viewMode === 'wire') ? true : false;
        
        if (viewMode === 'wire') {
          mat.opacity = 0.9;
        } else if (viewMode === 'xray') {
          mat.opacity = isSelected ? 0.2 : (isReactor ? 0.22 : 0.12);
        } else {
          mat.opacity = fillOpacity;
        }
        
        // Update children outlines
        child.children.forEach(sub => {
          if (sub.userData && sub.userData.isEdgeOutline) {
            const lineMat = sub.material;
            if (!lineMat) return;
            
            let outlineColor = 0x00f0ff;
            if (isSelected) {
              outlineColor = 0xff9900;
            } else if (isReactor) {
              outlineColor = 0xffffff;
            }
            
            lineMat.color.setHex(outlineColor);
            lineMat.blending = THREE.AdditiveBlending;
            lineMat.opacity = (viewMode === 'xray') ? 0.3 : 1.0;
            sub.visible = (viewMode === 'wire') ? false : true;
          }
        });
      }
    });
  }
}

// Synchronize 3D meshes with designData values
function syncModelMeshes() {
  rebuildThreeScene();
}

// Toggle view styling modes
function setViewMode(mode) {
  viewMode = mode;
  document.querySelectorAll('.view-controls button').forEach(b => b.classList.remove('active'));
  const btn = document.getElementById(`btn-shade-${mode === 'solid' ? 'solid' : mode === 'wire' ? 'wire' : 'xray'}`);
  if (btn) btn.classList.add('active');
  
  playSound('beep');
  updateMaterialsTheme();
}

function getPrimaryComponentKey() {
  if (!designData) return 'body';
  const pType = (designData.project_type || "car").toLowerCase();
  if (pType === 'suit') return 'torso';
  if (pType === 'drone') return 'core';
  if (pType === 'house') return 'foundation';
  if (pType === 'room') return 'floor';
  return 'body';
}

function getHeatSourceComponentKey() {
  if (!designData) return 'engine';
  const pType = (designData.project_type || "car").toLowerCase();
  if (pType === 'suit') return 'arc_reactor';
  if (pType === 'drone') return 'core';
  if (pType === 'house') return 'foundation';
  if (pType === 'room') return 'monitor';
  return 'engine';
}

// Explode view animation (generic radial displacement)
function toggleExplode() {
  isExploded = !isExploded;
  const btn = document.getElementById('btn-explode');
  if (btn) btn.classList.toggle('active', isExploded);
  playSound('double');
  
  const speed = 0.08;
  
  if (window.explodeInterval) clearInterval(window.explodeInterval);
  
  window.explodeInterval = setInterval(() => {
    let done = true;
    const comps = designData.components;
    
    for (let key in comps) {
      const mesh = meshes[key];
      if (!mesh) continue;
      
      const comp = comps[key];
      const defX = comp.pos_x || 0;
      const defY = comp.pos_y || 0;
      const defZ = comp.pos_z || 0;
      
      let tarX = defX;
      let tarY = defY;
      let tarZ = defZ;
      
      if (isExploded) {
        tarX = defX * 1.8;
        tarY = defY * 1.8;
        tarZ = defZ * 1.8;
        
        if (Math.abs(defX) < 0.1 && Math.abs(defZ) < 0.1) {
          tarY = defY + (defY >= 0 ? 0.8 : -0.8);
        } else {
          tarX = defX + (defX >= 0 ? 0.6 : -0.6);
          tarZ = defZ + (defZ >= 0 ? 0.6 : -0.6);
        }
      }
      
      const dx = tarX - mesh.position.x;
      const dy = tarY - mesh.position.y;
      const dz = tarZ - mesh.position.z;
      
      if (Math.abs(dx) > 0.01 || Math.abs(dy) > 0.01 || Math.abs(dz) > 0.01) {
        mesh.position.x += dx * speed;
        mesh.position.y += dy * speed;
        mesh.position.z += dz * speed;
        done = false;
      }
    }
    
    if (done) clearInterval(window.explodeInterval);
  }, 16);
}

// Toggle simulation views (rebuilds scene to apply material overlay)
function toggleSimulation(sim) {
  if (!designData) return;
  
  const btn = document.getElementById(`btn-sim-${sim}`);
  const active = btn ? !btn.classList.contains('active') : false;
  if (btn) btn.classList.toggle('active', active);

  playSound('beep');

  if (sim === 'airflow') {
    if (airflowSystem) airflowSystem.points.visible = active;
  } else if (sim === 'weight') {
    if (comMesh) comMesh.material.opacity = active ? 0.8 : 0.0;
    showToast(`Center of Mass marker ${active ? 'visible' : 'hidden'}.`);
  } else {
    rebuildThreeScene();
  }
}

// Render loop
function animate() {
  requestAnimationFrame(animate);
  controls.update();
  updateAirflow();
  
  // rotate wheels when airflow is active
  if (airflowSystem && airflowSystem.points.visible && meshes.wheels) {
    meshes.wheels.children.forEach(w => {
      w.rotation.x += 0.05;
    });
  }

  renderer.render(scene, camera);
}

// adjust viewport on resize
window.addEventListener('resize', () => {
  camera.aspect = canvas.clientWidth / canvas.clientHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(canvas.clientWidth, canvas.clientHeight);
});

animate();

// ── DATA AND BACKEND FETCH SYNC ──
async function loadProject() {
  try {
    const res = await fetch('/api/design/project');
    const data = await res.json();
    designData = data;
    updateUI();
    syncModelMeshes();
  } catch (err) {
    console.error("Failed to load design project state", err);
  }
}

function selectComponent(comp) {
  activeComponent = comp;
  document.querySelectorAll('.tree-node').forEach(n => n.classList.remove('selected'));
  const activeNode = document.getElementById(`node-${comp}`);
  if (activeNode) activeNode.classList.add('selected');
  
  updateInspector();
  updateMaterialsTheme();
}

function updateUI() {
  if (!designData) return;
  
  // header stats
  const projectHdr = document.getElementById('hdr-project');
  const verHdr = document.getElementById('hdr-ver');
  if (projectHdr) projectHdr.textContent = designData.project_name.toUpperCase();
  if (verHdr) verHdr.textContent = designData.current_version.toUpperCase();
  
  const pType = (designData.project_type || "car").toLowerCase();
  const lbl = document.getElementById('hdr-stat-label');
  const val = document.getElementById('hdr-drag');
  
  if (lbl && val) {
    if (pType === 'suit') {
      lbl.textContent = "Arc Energy";
      val.textContent = "95% (Stable)";
    } else if (pType === 'drone') {
      lbl.textContent = "Thrust Ratio";
      val.textContent = "2.4:1 (Optimal)";
    } else if (pType === 'house') {
      lbl.textContent = "Footprint";
      val.textContent = "320 m²";
    } else if (pType === 'room') {
      lbl.textContent = "Ergonomics";
      val.textContent = "A+ (Premium)";
    } else {
      lbl.textContent = "Model Drag";
      const dragVal = designData.components.body && designData.components.body.aerodynamics ? `Cd ${designData.components.body.aerodynamics.toFixed(2)}` : "Cd 0.32";
      val.textContent = dragVal;
    }
  }
  
  // render project tree dynamically
  const treeContainer = document.getElementById('project-tree-container');
  if (treeContainer) {
    const keys = Object.keys(designData.components);
    if (!keys.includes(activeComponent) && keys.length > 0) {
      activeComponent = keys[0];
    }
    
    treeContainer.innerHTML = keys.map(key => {
      const comp = designData.components[key];
      const label = key.replace(/_/g, ' ').toUpperCase();
      let meta = "";
      
      if (key === 'body' || key === 'torso' || key === 'foundation' || key === 'floor') {
        meta = comp.aerodynamics ? `Cd: ${comp.aerodynamics.toFixed(2)}` : "PRIMARY";
      } else if (key === 'engine') {
        meta = comp.horsepower ? `${comp.horsepower} HP` : "V8 BLOCK";
      } else if (key === 'arc_reactor') {
        meta = comp.radius ? `${Math.round(comp.radius * 830)}% PWR` : "ARC REACTOR";
      } else if (key === 'wheels') {
        meta = comp.radius ? `R: ${comp.radius.toFixed(2)}` : "TIRES";
      } else if (comp.parent) {
        meta = `-> ${comp.parent.replace(/_/g, ' ').toUpperCase()}`;
      } else if (comp.type) {
        meta = comp.type.toUpperCase();
      } else {
        meta = "MODULE";
      }
      return `
        <div class="tree-node ${activeComponent === key ? 'selected' : ''}" id="node-${key}" onclick="selectComponent('${key}')">
          <span>${label}</span>
          <span class="tree-node-meta" id="meta-${key}">${meta}</span>
        </div>
      `;
    }).join('');
  }
  
  // render version history switcher
  const histContainer = document.getElementById('version-list-container');
  if (histContainer) {
    histContainer.innerHTML = designData.version_history.map(v => `
      <div class="history-item ${designData.current_version === v.version ? 'active' : ''}" onclick="loadVersion('${v.version}')">
        <div class="history-meta">
          <span class="history-ver">${v.version.toUpperCase()}</span>
          <span class="history-time">${v.timestamp}</span>
        </div>
        <div class="history-desc">${v.description}</div>
      </div>
    `).reverse().join('');
  }

  // render AI concept choices
  const conceptContainer = document.getElementById('ai-suggestions-container');
  if (conceptContainer) {
    conceptContainer.innerHTML = designData.ai_concepts.map(c => {
      let metricText = `Power Target: ${c.power} HP`;
      if (pType === 'suit') metricText = `Arc Resonance: ${c.power}%`;
      else if (pType === 'drone') metricText = `Power Draw: ${c.power} W`;
      else if (pType === 'house' || pType === 'room') metricText = `Efficiency: ${c.power}%`;

      return `
        <div class="concept-card" onclick="applyConcept('${c.id}')">
          <div class="concept-header">
            <span>${c.label}</span>
            <span>${pType === 'car' || pType === 'drone' ? `Cd ${c.drag.toFixed(2)}` : 'AI SPEC'}</span>
          </div>
          <div class="concept-desc">${c.description}</div>
          <div class="concept-metrics">${metricText}</div>
        </div>
      `;
    }).join('');
  }

  updateInspector();
}

function updateInspector() {
  if (!designData) return;
  const comp = designData.components[activeComponent];
  if (!comp) return;
  const container = document.getElementById('inspector-container');
  if (!container) return;
  
  let html = `<div style="font-weight: 800; border-bottom: 1px solid rgba(0,240,255,0.1); padding-bottom: 8px; color: var(--accent);">${activeComponent.replace(/_/g, ' ').toUpperCase()} PROPERTIES</div>`;
  
  for (let attr in comp) {
    let val = comp[attr];
    let displayVal = typeof val === 'number' ? val.toFixed(2) : val;
    let isAccent = attr === 'color' || attr === 'horsepower' || attr === 'aerodynamics' || attr === 'parent';
    
    html += `
      <div class="inspect-row">
        <span class="inspect-label">${attr.replace('_', ' ').toUpperCase()}</span>
        <span class="inspect-val ${isAccent ? 'inspect-val-accent' : ''}">${displayVal}</span>
      </div>
    `;
  }
  
  container.innerHTML = html;
}

async function applyConcept(optId) {
  const char = optId.split('_')[1]; // a, b, c
  showToast(`Merging Co-Designer Option ${char.toUpperCase()} parameters...`);
  await sendCommand(`apply option ${char}`);
}

async function loadVersion(verName) {
  showToast(`Loading layout constraints for ${verName.toUpperCase()}...`);
  await sendCommand(`load version ${verName}`);
}

// Console logs push
function pushConsoleLog(prefix, text, type = 'user') {
  const container = document.getElementById('console-logs-container');
  if (!container) return;
  const log = document.createElement('div');
  log.className = 'log-line';
  let preClass = 'log-prefix';
  if (prefix === 'ARIA') preClass = 'log-prefix aria';
  if (prefix === 'Error') preClass = 'log-prefix err';

  log.innerHTML = `<span class="${preClass}">[${prefix}]</span> <span class="log-text">${text}</span>`;
  container.appendChild(log);
  container.scrollTop = container.scrollHeight;
}

async function sendConsoleCommand() {
  const input = document.getElementById('console-cmd-input');
  if (!input) return;
  const cmd = input.value.trim();
  if (!cmd) return;
  
  input.value = '';
  pushConsoleLog('User', cmd);
  const status = document.getElementById('hdr-status');
  if (status) {
    status.textContent = 'COMPUTING';
    status.style.color = 'var(--accent)';
  }
  
  await sendCommand(cmd);
}

async function sendCommand(cmd) {
  try {
    const res = await fetch('/api/design/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: cmd })
    });
    const data = await res.json();
    
    const status = document.getElementById('hdr-status');
    if (status) {
      status.textContent = 'IDLE';
      status.style.color = 'var(--warn)';
    }

    if (data.status === 'success') {
      pushConsoleLog('ARIA', data.message);
      speakVocalResponse(data.message);
      designData = data.project;
      updateUI();
      syncModelMeshes();
      playSound('success');
      
      // if simulation toggled, update local sim checkboxes/buttons
      if (data.action === 'SIMULATION_TOGGLE') {
        const sim = data.simulation;
        const btn = document.getElementById(`btn-sim-${sim}`);
        if (btn) btn.classList.toggle('active', data.state);
        
        // force update state
        if (sim === 'airflow') {
          if (airflowSystem) airflowSystem.points.visible = data.state;
        }
        if (sim === 'weight') {
          if (comMesh) comMesh.material.opacity = data.state ? 0.8 : 0.0;
        }
        if (sim === 'stability' || sim === 'heat_map') {
          rebuildThreeScene();
        }
      }
      
      // if immersive mode voice command triggered
      if (data.action === 'TOGGLE_IMMERSIVE') {
        const shouldBeImmersive = data.immersive;
        const currentImmersive = document.body.classList.contains('immersive-mode');
        if (shouldBeImmersive !== currentImmersive) {
          toggleImmersiveMode();
        }
      }
    } else {
      pushConsoleLog('Error', data.message);
      speakVocalResponse(data.message);
      playSound('error');
    }
  } catch (err) {
    const status = document.getElementById('hdr-status');
    if (status) {
      status.textContent = 'IDLE';
      status.style.color = 'var(--warn)';
    }
    pushConsoleLog('Error', "Server communication failed.");
    playSound('error');
  }
}

// ── HOLOGRAPHIC IMMERSIVE MODE CONTROLS ──
function resizeViewport() {
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height);
}

function toggleImmersiveMode() {
  document.body.classList.toggle('immersive-mode');
  const isImmersive = document.body.classList.contains('immersive-mode');
  
  updateSceneTheme();
  updateMaterialsTheme();
  
  // Force Three.js canvas size reflow
  setTimeout(resizeViewport, 50);
  
  showToast(isImmersive ? "Entering immersive Hologram mode. HUD offline." : "HUD online.", "info");
  playSound('double');
}

// Keyboard shortcuts for immersive mode (H, Tab, Esc)
window.addEventListener('keydown', (e) => {
  if (document.activeElement && (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA')) {
    return; // Ignore keyboard shortcuts when typing in inputs
  }
  
  const key = e.key.toLowerCase();
  if (key === 'h' || e.key === 'Tab' || e.key === 'Escape') {
    e.preventDefault();
    toggleImmersiveMode();
  }
});

// handle Enter key inside console
const cmdInput = document.getElementById('console-cmd-input');
if (cmdInput) {
  cmdInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendConsoleCommand();
  });
}

// ── GESTURE TRACKING (MediaPipe integration) ──
let isTrackingGestures = false;
let cameraStream = null;
let handsMP = null;
let cameraMP = null;
let gestureSmoothing = { lastX: 0, lastY: 0, initialized: false };

function onGestureResults(results) {
  if (!isTrackingGestures || !results.multiHandLandmarks) return;
  if (results.multiHandLandmarks.length === 0) return;

  const landmarks = results.multiHandLandmarks[0];
  
  // Index finger tip (8) and Thumb tip (4)
  const thumb = landmarks[4];
  const index = landmarks[8];
  
  // calculate distance (pinch detection)
  const dx = thumb.x - index.x;
  const dy = thumb.y - index.y;
  const dz = thumb.z - index.z;
  const dist = Math.sqrt(dx*dx + dy*dy + dz*dz);
  
  // Pinch is detected if distance is tiny (< 0.08)
  const isPinching = dist < 0.08;
  
  // Use index tip position for movement coords
  const currentX = index.x;
  const currentY = index.y;

  if (isPinching) {
    if (!gestureSmoothing.initialized) {
      gestureSmoothing.lastX = currentX;
      gestureSmoothing.lastY = currentY;
      gestureSmoothing.initialized = true;
      // play audio synth click indicating grab!
      playSound('beep');
      showToast("Gesture grab active // Selected: " + activeComponent);
    } else {
      // relative drag delta
      const deltaX = currentX - gestureSmoothing.lastX;
      const deltaY = currentY - gestureSmoothing.lastY;

      // rotate or move selected part in Three.js
      const speed = 4.0;
      carGroup.rotation.y += deltaX * speed;
      carGroup.rotation.x += deltaY * speed;

      gestureSmoothing.lastX = currentX;
      gestureSmoothing.lastY = currentY;
    }
  } else {
    gestureSmoothing.initialized = false;
  }
}

async function toggleGestureTracking() {
  const btn = document.getElementById('btn-gesture');
  const pip = document.getElementById('pip-gesture-window');
  const video = document.getElementById('webcam-video');

  isTrackingGestures = !isTrackingGestures;
  if (btn) btn.classList.toggle('active', isTrackingGestures);
  playSound('beep');

  if (isTrackingGestures) {
    showToast("Accessing visual capture device...");
    if (pip) pip.style.display = 'block';

    try {
      // Release camera lock in python backend first
      await fetch('/api/camera/release', { method: 'POST' });
      // Small delay to let OS release the device handle
      await new Promise(r => setTimeout(r, 400));

      cameraStream = await navigator.mediaDevices.getUserMedia({
        video: true
      });
      if (video) video.srcObject = cameraStream;

      // Initialize MediaPipe
      if (!handsMP) {
        handsMP = new Hands({
          locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/hands/${file}`
        });
        handsMP.setOptions({
          maxNumHands: 1,
          modelComplexity: 1,
          minDetectionConfidence: 0.65,
          minTrackingConfidence: 0.65
        });
        handsMP.onResults(onGestureResults);
      }

      if (!cameraMP && video) {
        cameraMP = new Camera(video, {
          onFrame: async () => {
            await handsMP.send({ image: video });
          },
          width: 320,
          height: 240
        });
      }
      if (cameraMP) cameraMP.start();
      showToast("Stark-style gestures initialized. Pinch index + thumb to grab & rotate.", "info");
    } catch (err) {
      showToast("Webcam access failed: " + err.message, "warn");
      isTrackingGestures = false;
      if (btn) btn.classList.remove('active');
      if (pip) pip.style.display = 'none';
      // Re-acquire camera in backend if browser access failed
      fetch('/api/camera/acquire', { method: 'POST' }).catch(console.error);
    }
  } else {
    if (pip) pip.style.display = 'none';
    if (cameraStream) {
      cameraStream.getTracks().forEach(t => t.stop());
    }
    if (cameraMP) {
      cameraMP.stop();
    }
    showToast("Gesture tracking system offline.");
    // Re-acquire camera lock in python backend
    await fetch('/api/camera/acquire', { method: 'POST' }).catch(console.error);
  }
}

// Load project data on start
loadProject();

// Reacquire camera lock if page is closed/refreshed
window.addEventListener('unload', () => {
  navigator.sendBeacon('/api/camera/acquire');
});

// Force fullscreen canvas size reflow on window load
window.addEventListener('load', () => {
  setTimeout(resizeViewport, 100);
  setTimeout(resizeViewport, 300);
  setTimeout(resizeViewport, 500);
});
