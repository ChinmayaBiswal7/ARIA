import React, { useState, useEffect, useRef } from "react";
import { initializeApp } from "firebase/app";
import { getFirestore, doc, onSnapshot, setDoc } from "firebase/firestore";

import SphereCanvas from "./components/SphereCanvas";
import Console from "./components/Console";
import Launch from "./components/Launch";
import Macros from "./components/Macros";
import Shortcuts from "./components/Shortcuts";

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

export default function App() {
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
  const recognitionRef = useRef(null);
  const shouldListenRef = useRef(false);
  const screenImageContainerRef = useRef(null);
  const lastSpokenTextRef = useRef("");
  const currentStatusRef = useRef("OFFLINE");
  const lastStatusTimestampRef = useRef(0);
  const sessionStartedAtRef = useRef(Date.now() / 1000);
  const pendingLaptopCommandIdRef = useRef(null);
  const [isFullscreenActive, setIsFullscreenActive] = useState(false);
  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [isInstallable, setIsInstallable] = useState(false);

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
      if (!isInitialized) return;
      
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
  }, [isInitialized]);

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

  // ── Start Web Microphone & Speech Recognition ────────────────────────────
  const initializeRemote = async () => {
    if (isInitialized) return;

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showToast("Open in Chrome/Safari");
      setLastResponse("Mic API not supported in this Webview. Please open this website directly in Google Chrome or Safari.");
      return;
    }

    try {
      // 1. Web Audio Stream & Analyser Setup
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      const audioCtx = new AudioCtx();
      audioContextRef.current = audioCtx;

      const source = audioCtx.createMediaStreamSource(stream);
      const analyserNode = audioCtx.createAnalyser();
      analyserNode.fftSize = 64;
      source.connect(analyserNode);

      const bufferLength = analyserNode.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);

      setAudioAnalyser(analyserNode);
      setAudioDataArray(dataArray);

      // 2. Continuous Speech Recognition
      if ("webkitSpeechRecognition" in window || "SpeechRecognition" in window) {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        const recognition = new SR();
        recognition.continuous = false;
        recognition.interimResults = false;
        recognition.lang = "en-US";

        recognition.onstart = () => {
          shouldListenRef.current = true;
          setIsMicActive(true);
          setStatus("LISTENING");
          setConnectionDotClass("status-dot waiting");
        };

        recognition.onspeechstart = () => {
          setIsSpeechActive(true);
        };

        recognition.onspeechend = () => {
          setIsSpeechActive(false);
        };

        recognition.onend = () => {
          setIsSpeechActive(false);
          if (shouldListenRef.current) {
            try {
              recognition.start();
            } catch (e) {
              // Already listening
            }
          } else {
            setIsMicActive(false);
          }
        };

        recognition.onerror = (e) => {
          console.error("Speech recognition error:", e);
          setIsSpeechActive(false);
          if (shouldListenRef.current && e.error !== "not-allowed") {
            setTimeout(() => {
              try { recognition.start(); } catch (err) {}
            }, 400);
          }
        };

        recognition.onresult = (e) => {
          setIsSpeechActive(false);
          if (Date.now() < suppressRecognitionUntilRef.current) return;
          if (status === "SPEAKING" || pcStatus === "SPEAKING") return; // Ignore if speaking
          const resultIdx = e.resultIndex;
          const transcript = e.results[resultIdx][0].transcript;
          const cleanTranscript = transcript.trim();
          const lowerTranscript = cleanTranscript.toLowerCase();
          const startupEcho =
            lowerTranscript.includes("aria remote online") ||
            lowerTranscript.includes("listening");

          if (cleanTranscript && !startupEcho) {
            showToast(`Speech: "${cleanTranscript}"`);
            sendCommand(cleanTranscript);
          }
        };

        recognitionRef.current = recognition;
      } else {
        showToast("Speech recognition not supported on this browser.");
      }

      // Mark initialized
      setIsInitialized(true);
      shouldListenRef.current = true;
      sessionStartedAtRef.current = Date.now() / 1000;
      suppressRecognitionUntilRef.current = Date.now() + 2500;

      // Speak Greeting to unlock TTS
      speakText("Aria remote online. Listening.");
      setLastResponse("Aria remote online. Say a command when ready.");

      if (recognitionRef.current) {
        recognitionRef.current.start();
      }

      // 3. Connect to Firestore Status
      connectFirestore();

    } catch (e) {
      console.error("Mic access denied or initialization error:", e);
      showToast("Mic access required for always-on voice.");
    }
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
    if (!isInitialized) {
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

  // ── Firestore Status Sync ─────────────────────────────────────────────────
  const connectFirestore = () => {
    const unsubscribe = onSnapshot(doc(db, "status", "latest"), (docSnap) => {
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
      setConnectionDotClass("status-dot offline");
      setStatus("ERROR");
      setLastResponse("Firestore connection error");
    });

    return unsubscribe;
  };

  const getCanvasState = () => {
    if (status === "OFFLINE" || pcStatus === "OFFLINE") return "OFFLINE";
    if (pcStatus === "THINKING") return "THINKING";
    if (pcStatus === "SPEAKING" || status === "SPEAKING") return "SPEAKING";
    if (isSpeechActive) return "LISTENING";
    return pcStatus;
  };

  const toggleFullScreen = () => {
    const el = screenImageContainerRef.current;
    if (!el) return;
    
    if (!document.fullscreenElement && !document.webkitFullscreenElement) {
      const req = el.requestFullscreen || el.webkitRequestFullscreen;
      if (req) {
        const p = req.call(el);
        if (p && p.then) {
          p.then(() => {
            if (window.screen.orientation && window.screen.orientation.lock) {
              window.screen.orientation.lock("landscape").catch(err => {
                console.log("Orientation lock failed:", err);
              });
            }
          }).catch(err => {
            console.error("Fullscreen fail:", err);
          });
        } else {
          // iOS Safari fallback
          setTimeout(() => {
            if (window.screen.orientation && window.screen.orientation.lock) {
              window.screen.orientation.lock("landscape").catch(() => {});
            }
          }, 300);
        }
      }
    } else {
      const exit = document.exitFullscreen || document.webkitExitFullscreen;
      if (exit) {
        const p = exit.call(document);
        if (p && p.then) {
          p.then(() => {
            if (window.screen.orientation && window.screen.orientation.unlock) {
              window.screen.orientation.unlock();
            }
          }).catch(err => {
            console.error("Exit fullscreen fail:", err);
          });
        } else {
          if (window.screen.orientation && window.screen.orientation.unlock) {
            window.screen.orientation.unlock();
          }
        }
      }
    }
  };

  return (
    <>
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
        <div className="sphere-container" onClick={toggleMicrophone}>
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
          <div className="screen-feedback-title-bar">
            <span className="screen-feedback-title">PC Live Screen</span>
            <span className="screen-feedback-subtitle">Tap screen to click</span>
          </div>
          <div 
            ref={screenImageContainerRef}
            className="screen-image-container" 
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
        <Console onSendCommand={sendCommand} isListening={isMicActive} onToggleMic={toggleMicrophone} />
        <Launch onSendCommand={sendCommand} />
        <Macros onSendCommand={sendCommand} />
        <Shortcuts onSendCommand={sendCommand} />
      </div>

      {/* Toast Notification */}
      <div className={`toast ${toast.show ? "show" : ""}`} id="toast">
        {toast.message}
      </div>
    </>
  );
}
