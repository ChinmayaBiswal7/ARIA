import React, { useState, useEffect, useRef } from "react";
import { initializeApp } from "firebase/app";
import { getFirestore, doc, onSnapshot, setDoc, collection, addDoc } from "firebase/firestore";
import { getStorage, ref as storageRef, uploadBytes, getDownloadURL } from "firebase/storage";

import SphereCanvas from "./components/SphereCanvas";
import Console from "./components/Console";
import HealthWidget from "./components/HealthWidget";
import SplashScreen from "./components/SplashScreen";

// ── Firebase Configuration ──────────────────────────────────────────────────
const firebaseConfig = {
  apiKey:            "AIzaSyA5l74ebBKR8-veakGNISlwkIdasA-vQaQ",
  authDomain:        "aria-3e1da.firebaseapp.com",
  projectId:         "aria-3e1da",
  storageBucket:     "aria-3e1da.firebasestorage.app",
  messagingSenderId: "968886942490",
  appId:             "1:968886942490:web:8ab8c8a061ae6d79a94aa3"
};

const app = initializeApp(firebaseConfig);
const db = getFirestore(app);
const storage = getStorage(app);

export default function App() {
  const [showSplash, setShowSplash] = useState(true);
  const [status, setStatus] = useState("OFFLINE");
  const [pcStatus, setPcStatus] = useState("OFFLINE");
  const [lastResponse, setLastResponse] = useState("Tap the sphere above to connect to ARIA");
  const [isInitialized, setIsInitialized] = useState(false);
  const [toast, setToast] = useState({ show: false, message: "" });
  const [connectionDotClass, setConnectionDotClass] = useState("status-dot offline");
  const [screenshot, setScreenshot] = useState(null);
  const [screenW, setScreenW] = useState(1920);
  const [screenH, setScreenH] = useState(1080);
  const [isMicActive, setIsMicActive] = useState(false);
  const [isSpeechActive, setIsSpeechActive] = useState(false);

  // Web Audio refs/states
  const [audioAnalyser, setAudioAnalyser] = useState(null);
  const [audioDataArray, setAudioDataArray] = useState(null);

  const audioContextRef = useRef(null);
  const streamRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const isRecordingRef = useRef(false);
  const shouldListenRef = useRef(false);
  const screenImageContainerRef = useRef(null);
  const lastSpokenTextRef = useRef("");
  const currentStatusRef = useRef("OFFLINE");
  const lastStatusTimestampRef = useRef(0);
  const sessionStartedAtRef = useRef(Date.now() / 1000);
  const pendingLaptopCommandIdRef = useRef(null);
  const recognitionRef = useRef(null);
  const lastSpeechTextRef = useRef("");
  const [isFullscreenActive, setIsFullscreenActive] = useState(false);
  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [isInstallable, setIsInstallable] = useState(false);

  // Debug telemetry states & refs
  const [firebaseState, setFirebaseState] = useState("Connecting...");
  const [heartbeatAge, setHeartbeatAge] = useState(null);
  const [lastScreenshotAge, setLastScreenshotAge] = useState(null);
  const [micStatus, setMicStatus] = useState("Inactive");
  const [screenQuality, setScreenQuality] = useState("medium");
  const lastScreenshotTimestampRef = useRef(0);

  useEffect(() => {
    const handleBeforeInstall = (e) => {
      e.preventDefault();
      setDeferredPrompt(e);
      setIsInstallable(true);
      showToast("ARIA Remote is ready to install!");
    };
    window.addEventListener("beforeinstallprompt", handleBeforeInstall);
    return () => window.removeEventListener("beforeinstallprompt", handleBeforeInstall);
  }, []);

  const handleInstallClick = async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    console.log("Install prompt outcome:", outcome);
    setDeferredPrompt(null);
    setIsInstallable(false);
  };

  useEffect(() => {
    const handleFsChange = () => {
      setIsFullscreenActive(!!(document.fullscreenElement || document.webkitFullscreenElement));
    };

    document.addEventListener("fullscreenchange", handleFsChange);
    document.addEventListener("webkitfullscreenchange", handleFsChange);

    return () => {
      document.removeEventListener("fullscreenchange", handleFsChange);
      document.removeEventListener("webkitfullscreenchange", handleFsChange);
    };
  }, []);

  useEffect(() => {
    currentStatusRef.current = status;
  }, [status]);

  // Offline detection heartbeat watchdog
  useEffect(() => {
    const interval = setInterval(() => {
      if (lastStatusTimestampRef.current === 0) return;
      
      const nowSeconds = Date.now() / 1000;
      const timeDiff = nowSeconds - lastStatusTimestampRef.current;
      
      // If we haven't received a heartbeat in 9 seconds, declare server OFFLINE
      if (timeDiff > 9.0) {
        setStatus("OFFLINE");
        setPcStatus("OFFLINE");
        setConnectionDotClass("status-dot offline");
        setLastResponse("ARIA is offline. Please launch the laptop server.");
      }
    }, 2000);
    
    return () => clearInterval(interval);
  }, []);

  // Heartbeat & screenshot age update timer
  useEffect(() => {
    const interval = setInterval(() => {
      const nowSeconds = Date.now() / 1000;
      
      if (lastStatusTimestampRef.current > 0) {
        setHeartbeatAge(Math.round(nowSeconds - lastStatusTimestampRef.current));
      } else {
        setHeartbeatAge(null);
      }

      if (lastScreenshotTimestampRef.current > 0) {
        setLastScreenshotAge(Math.round(nowSeconds - lastScreenshotTimestampRef.current));
      } else {
        setLastScreenshotAge(null);
      }
    }, 1000);
    
    return () => clearInterval(interval);
  }, []);

  // ── Show Toast Helper ─────────────────────────────────────────────────────
  const showToast = (message) => {
    setToast({ show: true, message });
    setTimeout(() => {
      setToast({ show: false, message: "" });
    }, 2200);
  };

  // ── Send Command to Firestore ─────────────────────────────────────────────
  const sendLaptopCommand = async (text, imageB64 = null) => {
    if (!text.trim() && !imageB64) return;
    try {
      const commandId = "cmd_" + Date.now();
      pendingLaptopCommandIdRef.current = commandId;
      const data = {
        id: commandId,
        source: "phone",
        text: text.trim() || "Analyze this photo",
        timestamp: Date.now()
      };
      if (imageB64) {
        data.image_b64 = imageB64;
      }
      await setDoc(doc(db, "commands", "latest"), data);
      return commandId;
    } catch (e) {
      console.error("Firestore command send failed:", e);
      pendingLaptopCommandIdRef.current = null;
    }
  };

  const openPhoneTarget = (url, label) => {
    setLastResponse(`Opening ${label} on this phone.`);
    showToast(`Opening ${label}`);
    window.location.href = url;
  };

  const sendCommand = async (text, imageB64 = null) => {
    const cleanText = (text || "").trim();
    const lower = cleanText.toLowerCase();
    if (!cleanText && !imageB64) return;

    if (lower.startsWith("laptop ") || lower.startsWith("pc ")) {
      const laptopText = cleanText.replace(/^(laptop|pc)\s+/i, "");
      setLastResponse(`Sending to laptop: ${laptopText}`);
      await sendLaptopCommand(laptopText, imageB64);
      return;
    }

    if (imageB64) {
      setLastResponse("Photo captured on this phone. Say laptop analyze this photo if you want ARIA on the laptop to process it.");
      showToast("Photo kept on phone");
      return;
    }

    if (lower.includes("whatsapp")) return openPhoneTarget("intent://#Intent;package=com.whatsapp;end", "WhatsApp");
    if (lower.includes("youtube")) return openPhoneTarget("intent://#Intent;package=com.google.android.youtube;end", "YouTube");
    if (lower.includes("chrome") || lower.includes("browser")) return openPhoneTarget("intent://#Intent;package=com.android.chrome;end", "Chrome");
    if (lower.includes("camera")) return openPhoneTarget("intent://#Intent;action=android.media.action.IMAGE_CAPTURE;end", "Camera");
    if (lower.includes("maps") || lower.includes("map")) return openPhoneTarget("geo:0,0?q=", "Maps");
    if (lower.includes("gmail") || lower.includes("mail")) return openPhoneTarget("intent://#Intent;package=com.google.android.gm;end", "Gmail");
    if (lower.includes("instagram")) return openPhoneTarget("intent://#Intent;package=com.instagram.android;end", "Instagram");
    if (lower.includes("phone") || lower.includes("dialer") || lower.startsWith("call ")) return openPhoneTarget("tel:", "Phone");
    if (lower.includes("message") || lower.includes("sms")) return openPhoneTarget("sms:", "Messages");
    if (lower.includes("settings")) return openPhoneTarget("intent://#Intent;package=com.android.settings;end", "Settings");
    if (lower.startsWith("search ") || lower.startsWith("google ")) {
      const query = cleanText.replace(/^(search|google)\s+/i, "");
      return openPhoneTarget(`https://www.google.com/search?q=${encodeURIComponent(query)}`, "Google Search");
    }

    // Fallback: Send any unmatched commands to the laptop/PC server
    setLastResponse(`Sending to laptop: ${cleanText}`);
    showToast("Sent to laptop");
    await sendLaptopCommand(cleanText, imageB64);
  };

  // ── Speech Synthesizer (Text to Speech) ───────────────────────────────────
  const speakText = (text) => {
    if (!window.speechSynthesis) return;
    window.speechSynthesis.cancel();

    // Clean up bracketed action tags
    let cleanText = text.replace(/\[[A-Z]+:[^\]]*\]/g, "");
    cleanText = cleanText.replace(/\[[A-Z]+\]/g, "").trim();
    if (!cleanText) return;

    const utterance = new SpeechSynthesisUtterance(cleanText);
    utterance.lang = "en-US";

    const voices = window.speechSynthesis.getVoices();
    const naturalVoice =
      voices.find(v => v.lang.includes("en-US") && (v.name.includes("Google") || v.name.includes("Natural"))) ||
      voices.find(v => v.lang.includes("en-US")) ||
      voices[0];

    if (naturalVoice) utterance.voice = naturalVoice;

    utterance.onstart = () => {
      setStatus("SPEAKING");
    };

    const handleTtsEnd = () => {
      setStatus("IDLE");
      suppressRecognitionUntilRef.current = Date.now() + 1500;
    };

    utterance.onend = handleTtsEnd;
    utterance.onerror = handleTtsEnd;

    window.speechSynthesis.speak(utterance);
  };

  // ── Upload Base64 voice audio directly to Firestore (no Firebase Storage) ──
  const uploadVoiceAudio = async (audioBlob) => {
    const sizeKb = (audioBlob.size / 1024).toFixed(1);
    console.log(`[Phone] Audio size: ${sizeKb} KB`);
    
    try {
      setMicStatus("Sending...");
      const ts = Date.now();
      
      console.log("[Phone] Converting blob to Base64...");
      const base64String = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onloadend = () => {
          const base64 = reader.result.split(',')[1];
          resolve(base64);
        };
        reader.onerror = (err) => {
          console.error("[Phone] Base64 conversion error:", err);
          reject(err);
        };
        reader.readAsDataURL(audioBlob);
      });
      
      console.log("[Phone] Base64 conversion success");
      
      console.log("[Phone] Writing audio document to Firestore 'voice_audio' collection...");
      const docRef = await addDoc(collection(db, "voice_audio"), {
        audio_base64: base64String,
        timestamp_ms: ts,
        processed: false,
        transcribing: false,
        transcript: "",
        user: "remote",
      });
      console.log("[Phone] Firestore write success. Doc ID:", docRef.id);
      
      setMicStatus("Sending...");
      showToast("Voice sent — transcribing...");
      
      // Real-time listener on this document to track transcription and execution
      const unsub = onSnapshot(doc(db, "voice_audio", docRef.id), (snap) => {
        if (!snap.exists()) return;
        const data = snap.data();
        if (data.transcribing && !data.processed) {
          console.log("[Phone] Transcribing...");
          setMicStatus("Transcribing...");
        }
        if (data.processed) {
          if (data.transcript) {
            const transcript = data.transcript;
            console.log(`[Phone] Whisper result: "${transcript}"`);
            setMicStatus(`Heard: "${transcript}"`);
            setLastResponse(`Heard: "${transcript}"`);
            showToast(`Heard: "${transcript}"`);
          } else {
            console.log("[Phone] Processed with empty transcript");
            setMicStatus("Ready");
          }
          unsub(); // Stop listening
          setTimeout(() => setMicStatus("Ready"), 4000);
        }
      }, (err) => {
        console.error("[Phone] voice_audio snapshot error:", err);
        unsub();
      });
      
    } catch (e) {
      console.error("[Phone] Firestore voice send failed:", e);
      showToast("Send failed. Check connection.");
      setMicStatus("Ready");
    }
  };

  // ── Push-to-talk: hold sphere to record, release to send ─────────────────
  const startVoiceCapture = async () => {
    console.log("[VoiceAudio] startVoiceCapture initiated. isRecordingRef:", isRecordingRef.current, "isInitialized:", isInitialized);
    if (isRecordingRef.current) return;
    if (!isInitialized || !streamRef.current) {
      console.log("[VoiceAudio] Remote not initialized or mic stream missing. Initializing first...");
      await initializeRemote();
      setTimeout(startVoiceCapture, 400);
      return;
    }
    try {
      console.log("[Phone] Recording started");
      audioChunksRef.current = [];
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";
      console.log("[VoiceAudio] Starting MediaRecorder with MIME type:", mimeType);
      const recorder = new MediaRecorder(streamRef.current, { mimeType });
      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
          audioChunksRef.current.push(e.data);
        }
      };
      recorder.onstop = async () => {
        console.log("[VoiceAudio] MediaRecorder stopped. Chunks count:", audioChunksRef.current.length);
        isRecordingRef.current = false;
        setIsSpeechActive(false);
        
        if (audioChunksRef.current.length === 0) {
          console.warn("[VoiceAudio] No audio chunks collected.");
          setMicStatus("Ready");
          return;
        }
        const blob = new Blob(audioChunksRef.current, { type: mimeType });
        console.log("[VoiceAudio] Created Audio Blob. Size in bytes:", blob.size);
        if (blob.size < 1000) {
          console.warn("[VoiceAudio] Audio blob too small (< 1000 bytes). Aborting upload.");
          showToast("Too short — hold longer to speak.");
          setMicStatus("Ready");
          return;
        }
        await uploadVoiceAudio(blob);
      };
      
      mediaRecorderRef.current = recorder;
      recorder.start(100); // collect chunks every 100ms
      isRecordingRef.current = true;
      setIsMicActive(true);
      setIsSpeechActive(true);
      setMicStatus("🔴 Recording");
      console.log("[VoiceAudio] MediaRecorder started successfully. Recording status set to true.");
    } catch (e) {
      console.error("[VoiceAudio] startVoiceCapture failed:", e);
      showToast("Could not start recording.");
    }
  };

  const stopVoiceCapture = () => {
    console.log("[VoiceAudio] stopVoiceCapture requested. isRecordingRef:", isRecordingRef.current);
    if (!isRecordingRef.current || !mediaRecorderRef.current) return;
    
    console.log("[Phone] Recording stopped");

    if (mediaRecorderRef.current.state !== "inactive") {
      console.log("[VoiceAudio] Stopping MediaRecorder. State was:", mediaRecorderRef.current.state);
      mediaRecorderRef.current.stop();
    }
    setMicStatus("Processing...");
  };

  // ── Initialize mic stream + audio analyser (no STT needed here) ──────────
  const initializeRemote = async () => {
    if (isInitialized) return;

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showToast("Text-only mode active");
      setLastResponse("Microphone API not supported in this browser. Running in text-only mode.");
      setIsInitialized(true);
      setMicStatus("Unsupported");
      return;
    }

    // ── Step 1: Get hardware mic access ──────────────────────────────────────
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (permErr) {
      console.error("Microphone permission denied:", permErr);
      showToast("Mic permission denied. Check app settings.");
      setLastResponse("Microphone denied. Go to Settings → Apps → ARIA → Permissions → Microphone → Allow.");
      setIsInitialized(false);
      setMicStatus("Denied");
      return;
    }

    // ── Step 2: Set up audio analyser for sphere visualizer ──────────────────
    streamRef.current = stream;

    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      const audioCtx = new AudioCtx();
      audioContextRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);
      const analyserNode = audioCtx.createAnalyser();
      analyserNode.fftSize = 64;
      source.connect(analyserNode);
      const dataArray = new Uint8Array(analyserNode.frequencyBinCount);
      setAudioAnalyser(analyserNode);
      setAudioDataArray(dataArray);
    } catch (err) {
      console.warn("AudioContext setup failed (non-fatal):", err);
    }

    // ── Step 3: Ready — push-to-talk via Firebase Storage + Groq Whisper ─────
    setIsInitialized(true);
    setIsMicActive(true);
    setMicStatus("Ready");
    sessionStartedAtRef.current = Date.now() / 1000;

    speakText("Aria remote online.");
    setLastResponse("Mic ready. Hold the sphere to speak to ARIA.");
  };

  const handleScreenClick = async (e) => {
    const container = screenImageContainerRef.current;
    if (!container) return;
    
    const rect = container.getBoundingClientRect();
    const containerW = rect.width;
    const containerH = rect.height;
    
    // PC screen resolution aspect ratio
    const imageRatio = screenW / screenH;
    const containerRatio = containerW / containerH;
    
    let actualImageW = containerW;
    let actualImageH = containerH;
    let offsetX = 0;
    let offsetY = 0;
    
    if (containerRatio > imageRatio) {
      // Pillarbox (black bars left and right)
      actualImageW = containerH * imageRatio;
      offsetX = (containerW - actualImageW) / 2;
    } else {
      // Letterbox (black bars top and bottom)
      actualImageH = containerW / imageRatio;
      offsetY = (containerH - actualImageH) / 2;
    }
    
    const clickX = e.clientX - rect.left;
    const clickY = e.clientY - rect.top;
    
    const relativeX = clickX - offsetX;
    const relativeY = clickY - offsetY;
    
    if (relativeX >= 0 && relativeX <= actualImageW && relativeY >= 0 && relativeY <= actualImageH) {
      const nx = relativeX / actualImageW;
      const ny = relativeY / actualImageH;
      
      const x = Math.round(nx * screenW);
      const y = Math.round(ny * screenH);
      
      const clickCmd = `[CLICK: ${x},${y}]`;
      showToast(`Clicked PC at ${x}, ${y}`);
      await sendLaptopCommand(clickCmd);
    } else {
      console.log("Click ignored: outside actual screen area.");
    }
  };

  const toggleMicrophone = async () => {
    if (!isInitialized || !streamRef.current) {
      await initializeRemote();
      return;
    }
    
    if (shouldListenRef.current) {
      shouldListenRef.current = false;
      setIsMicActive(false);
      setStatus("IDLE");
      if (recognitionRef.current) {
        try { recognitionRef.current.stop(); } catch(e) {}
      }
      showToast("Microphone muted");
    } else {
      shouldListenRef.current = true;
      setIsMicActive(true);
      setStatus("LISTENING");
      if (recognitionRef.current) {
        try { recognitionRef.current.start(); } catch(e) {}
      }
      showToast("Microphone listening");
    }
  };

  useEffect(() => {
    const unsubscribe = connectFirestore();
    return () => {
      if (unsubscribe) unsubscribe();
    };
  }, []);

  // ── Firestore Status Sync ─────────────────────────────────────────────────
  const connectFirestore = () => {
    setFirebaseState("Connecting...");
    
    // Listen to PC status updates
    const unsubscribeStatus = onSnapshot(doc(db, "status", "latest"), (docSnap) => {
      setFirebaseState("Connected");
      if (!docSnap.exists()) return;
      const d = docSnap.data();

      setConnectionDotClass("status-dot"); // reset from waiting/offline

      if (d.timestamp) {
        lastStatusTimestampRef.current = d.timestamp;
      } else {
        lastStatusTimestampRef.current = Date.now() / 1000;
      }
      const rawState = d.status || "idle";
      setPcStatus(rawState.toUpperCase());
      if (rawState !== "speaking" && currentStatusRef.current !== "SPEAKING") {
        setStatus(rawState.toUpperCase());
      }

      if (d.screenshot) {
        setScreenshot(d.screenshot);
        lastScreenshotTimestampRef.current = Date.now() / 1000;
      }
      if (d.screenshot_quality) {
        setScreenQuality(d.screenshot_quality);
      }
      if (d.screen_w) {
        setScreenW(d.screen_w);
      }
      if (d.screen_h) {
        setScreenH(d.screen_h);
      }

      const isPhoneReply =
        d.reply_target === "phone" &&
        d.command_id &&
        d.command_id === pendingLaptopCommandIdRef.current;

      if (isPhoneReply && d.last_response && d.last_response !== lastSpokenTextRef.current) {
        const isSystemMsg =
          d.last_response.startsWith("Executing:") ||
          d.last_response.startsWith("Done:");

        if (!isSystemMsg) {
          setLastResponse(d.last_response);
          speakText(d.last_response);
          lastSpokenTextRef.current = d.last_response;
          if (rawState === "idle") {
            pendingLaptopCommandIdRef.current = null;
          }
        }
      }
    }, err => {
      console.error("Firestore snapshot error:", err);
      setFirebaseState("Error");
      setConnectionDotClass("status-dot offline");
      setStatus("ERROR");
      setLastResponse("Firestore connection error");
    });

    // Listen to dedicated phone reply notifications
    const unsubscribeReply = onSnapshot(doc(db, "phone_reply", "latest"), (docSnap) => {
      if (!docSnap.exists()) return;
      const d = docSnap.data();
      const tsSec = d.timestamp;
      if (tsSec && tsSec > sessionStartedAtRef.current && d.response) {
        if (d.response !== lastSpokenTextRef.current) {
          console.log("[Phone] Received phone_reply:", d.response);
          setLastResponse(d.response);
          speakText(d.response);
          lastSpokenTextRef.current = d.response;
        }
      }
    }, err => {
      console.error("Firestore phone_reply snapshot error:", err);
    });

    // Combined unsubscribe callback
    return () => {
      unsubscribeStatus();
      unsubscribeReply();
    };
  };

  const getCanvasState = () => {
    if (status === "OFFLINE" || pcStatus === "OFFLINE") return "OFFLINE";
    if (pcStatus === "THINKING") return "THINKING";
    if (pcStatus === "SPEAKING" || status === "SPEAKING") return "SPEAKING";
    if (isSpeechActive) return "LISTENING";
    return pcStatus;
  };

  const toggleFullScreen = () => {
    const nextFs = !isFullscreenActive;
    setIsFullscreenActive(nextFs);
    
    // Call Android interface if present
    if (window.AndroidInterface && typeof window.AndroidInterface.setImmersive === "function") {
      try {
        window.AndroidInterface.setImmersive(nextFs);
      } catch (err) {
        console.error("AndroidInterface.setImmersive failed:", err);
      }
    }

    const el = screenImageContainerRef.current;
    if (el) {
      if (nextFs) {
        const req = el.requestFullscreen || el.webkitRequestFullscreen;
        if (req) {
          req.call(el).then(() => {
            if (window.screen.orientation && window.screen.orientation.lock) {
              window.screen.orientation.lock("landscape").catch(() => {});
            }
          }).catch(err => {
            console.log("Native fullscreen request failed (safe to ignore in Android WebView):", err);
          });
        }
      } else {
        const exit = document.exitFullscreen || document.webkitExitFullscreen;
        if (exit) {
          exit.call(document).then(() => {
            if (window.screen.orientation && window.screen.orientation.unlock) {
              window.screen.orientation.unlock();
            }
          }).catch(err => {
            console.log("Native exit fullscreen failed (safe to ignore in Android WebView):", err);
          });
        }
      }
    }
  };

  return (
    <>
      {showSplash && <SplashScreen onComplete={() => setShowSplash(false)} />}
      
      {/* Top Bar */}
      <div className="topbar">
        <div className="topbar-logo">
          <div className="logo-text">ARIA</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
          {isInstallable && (
            <button className="pwa-install-btn" onClick={handleInstallClick}>
              📲 Install App
            </button>
          )}
          <div className={connectionDotClass} id="conn-dot"></div>
        </div>
      </div>

      {/* Hero Panel */}
      <div className="hero-panel">
        <div
          className="sphere-container"
          onClick={!isInitialized ? toggleMicrophone : undefined}
          onPointerDown={isInitialized ? startVoiceCapture : undefined}
          onPointerUp={isInitialized ? stopVoiceCapture : undefined}
          onPointerLeave={isInitialized ? stopVoiceCapture : undefined}
          style={{ touchAction: "none", userSelect: "none" }}
        >
          <SphereCanvas
            state={getCanvasState()}
            audioAnalyser={audioAnalyser}
            audioDataArray={audioDataArray}
          />
          {/* Overlay to unlock browser audio context */}
          <div className={`activation-overlay ${isInitialized ? "hidden" : ""}`}>
            <button className="activation-btn">Activate Remote</button>
          </div>
        </div>

        <div className="hero-info">
          <div
            className="hero-status"
            id="hub-state"
            style={{
              display: "flex",
              justifyContent: "center",
              alignItems: "center",
              gap: "8px",
              textTransform: "uppercase",
              letterSpacing: "2px",
              fontSize: "0.72rem",
              fontWeight: "800"
            }}
          >
            <span style={{
              color:
                pcStatus === "THINKING"
                  ? "rgba(251, 191, 36, 1)"
                  : pcStatus === "SPEAKING"
                  ? "rgba(167, 139, 250, 1)"
                  : pcStatus === "ERROR"
                  ? "#ef4444"
                  : "#00e5ff"
            }}>
              PC: {pcStatus}
            </span>
            <span style={{ color: "rgba(255,255,255,0.15)" }}>|</span>
            <span style={{
              color: isMicActive ? "#10b981" : "#64748b",
              display: "flex",
              alignItems: "center",
              gap: "4px"
            }}>
              <span style={{ 
                display: "inline-block", 
                width: "6px", 
                height: "6px", 
                borderRadius: "50%", 
                background: isMicActive ? "#10b981" : "#64748b",
                animation: isMicActive ? "blink 1.5s infinite" : "none"
              }}></span>
              MIC: {isMicActive ? "ON" : "MUTED"}
            </span>
          </div>
          
          {/* Debug Telemetry Indicators */}
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              justifyContent: "center",
              gap: "8px",
              marginTop: "8px",
              marginBottom: "8px",
              fontSize: "0.65rem",
              fontFamily: "monospace",
              color: "rgba(255, 255, 255, 0.45)"
            }}
          >
            <span style={{ padding: "2px 6px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: "4px" }}>
              FIREBASE: <span style={{ color: firebaseState === "Connected" ? "#10b981" : firebaseState === "Error" ? "#ef4444" : "#fbbf24" }}>{firebaseState}</span>
            </span>
            <span style={{ padding: "2px 6px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: "4px" }}>
              HEARTBEAT: <span style={{ color: heartbeatAge === null ? "#64748b" : heartbeatAge > 9 ? "#ef4444" : "#00e5ff" }}>{heartbeatAge === null ? "N/A" : `${heartbeatAge}s`}</span>
            </span>
            <span style={{ padding: "2px 6px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: "4px" }}>
              SCREEN: <span style={{ color: lastScreenshotAge === null ? "#64748b" : lastScreenshotAge > 15 ? "#fbbf24" : "#00e5ff" }}>{lastScreenshotAge === null ? "N/A" : `${lastScreenshotAge}s`}</span>
            </span>
            <span style={{ padding: "2px 6px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: "4px" }}>
              MIC: <span style={{ color: micStatus === "Active" ? "#10b981" : micStatus === "Denied" ? "#ef4444" : "#64748b" }}>{micStatus}</span>
            </span>
          </div>

          <div className="hero-transcript" id="status-display">
            {lastResponse}
          </div>
        </div>

        <a href="#controls" className="scroll-indicator">
          <span>Controls</span>
          <svg viewBox="0 0 24 24">
            <path d="M7.41,8.58L12,13.17L16.59,8.58L18,10L12,16L6,10L7.41,8.58Z" />
          </svg>
        </a>
      </div>

      {/* Screen Feedback Panel */}
      {screenshot && (
        <div className="screen-feedback">
          <div className="screen-feedback-title-bar" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <span className="screen-feedback-title">PC Live Screen</span>
              <span className="screen-feedback-subtitle">Tap screen to click</span>
            </div>
            <div style={{ display: "flex", gap: "6px" }}>
              <button 
                onClick={(e) => { e.stopPropagation(); setScreenQuality("low"); sendCommand("screenshot quality low"); }}
                style={{ fontSize: "0.6rem", padding: "3px 8px", background: screenQuality === "low" ? "rgba(0, 229, 255, 0.15)" : "rgba(255,255,255,0.03)", border: screenQuality === "low" ? "1px solid #00e5ff" : "1px solid rgba(255,255,255,0.1)", borderRadius: "4px", color: screenQuality === "low" ? "#00e5ff" : "#64748b", cursor: "pointer", fontWeight: "bold" }}
              >LOW</button>
              <button 
                onClick={(e) => { e.stopPropagation(); setScreenQuality("medium"); sendCommand("screenshot quality medium"); }}
                style={{ fontSize: "0.6rem", padding: "3px 8px", background: screenQuality === "medium" ? "rgba(0, 229, 255, 0.15)" : "rgba(255,255,255,0.03)", border: screenQuality === "medium" ? "1px solid #00e5ff" : "1px solid rgba(255,255,255,0.1)", borderRadius: "4px", color: screenQuality === "medium" ? "#00e5ff" : "#64748b", cursor: "pointer", fontWeight: "bold" }}
              >MED</button>
              <button 
                onClick={(e) => { e.stopPropagation(); setScreenQuality("high"); sendCommand("screenshot quality high"); }}
                style={{ fontSize: "0.6rem", padding: "3px 8px", background: screenQuality === "high" ? "rgba(0, 229, 255, 0.15)" : "rgba(255,255,255,0.03)", border: screenQuality === "high" ? "1px solid #00e5ff" : "1px solid rgba(255,255,255,0.1)", borderRadius: "4px", color: screenQuality === "high" ? "#00e5ff" : "#64748b", cursor: "pointer", fontWeight: "bold" }}
              >HIGH</button>
            </div>
          </div>
          <div 
            ref={screenImageContainerRef}
            className={`screen-image-container ${isFullscreenActive ? "fullscreen-active" : ""}`} 
          >
            <img 
              src={`data:image/jpeg;base64,${screenshot}`} 
              alt="PC Screen" 
              className="screen-image"
              onClick={handleScreenClick}
            />
            {/* Floating Fullscreen / Exit Button */}
            <button
              onClick={(e) => {
                e.stopPropagation();
                toggleFullScreen();
              }}
              className="fullscreen-toggle-overlay-btn"
              title={isFullscreenActive ? "Exit Fullscreen" : "Enter Fullscreen"}
            >
              {isFullscreenActive ? "📴 Exit Fullscreen" : "📺 Fullscreen"}
            </button>
          </div>
        </div>
      )}

      {/* Controls Container */}
      <div className="controls-container" id="controls">
        <HealthWidget db={db} />
        <Console onSendCommand={sendCommand} isListening={isMicActive} onToggleMic={toggleMicrophone} />
      </div>

      {/* Toast Notification */}
      <div className={`toast ${toast.show ? "show" : ""}`} id="toast">
        {toast.message}
      </div>
    </>
  );
}
