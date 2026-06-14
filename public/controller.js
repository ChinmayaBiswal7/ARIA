// Initialize Firebase Web Configuration
const firebaseConfig = {
  apiKey: "AIzaSyA5l74ebBKR8-veakGNISlwkIdasA-vQaQ",
  authDomain: "aria-3e1da.firebaseapp.com",
  projectId: "aria-3e1da",
  storageBucket: "aria-3e1da.firebasestorage.app",
  messagingSenderId: "968886942490",
  appId: "1:968886942490:web:8ab8c8a061ae6d79a94aa3",
  measurementId: "G-Y1PTEHQV8Q"
};

firebase.initializeApp(firebaseConfig);
const db = firebase.firestore();

// ── Live Status Listener (Firestore Document Snapshot) ──────────────────
db.collection("status").doc("latest").onSnapshot((doc) => {
  if (doc.exists) {
    const data = doc.data();
    document.getElementById("status-display").innerText = data.last_response || "No reports.";
    const badge = document.getElementById("hub-state");
    if (badge) {
      badge.innerText = data.status || "online";
      if (data.status === "thinking") {
        badge.style.color = "#fbbf24";
      } else if (data.status === "listening") {
        badge.style.color = "#10b981";
      } else {
        badge.style.color = "var(--accent-color)";
      }
    }
  }
}, (error) => {
  console.error("Firestore Listen Error:", error);
});

// ── Send Command API (Firestore Document Write) ─────────────────────────
function sendCommand(text) {
  if (!text.trim()) return;
  const cmdId = "cmd_" + Date.now();
  
  db.collection("commands").doc("latest").set({
    id: cmdId,
    text: text.trim(),
    timestamp: Date.now()
  }).then(() => {
    console.log("Command pushed to Firestore:", text);
  }).catch(err => {
    alert("Firestore write error: " + err.message + "\n\nMake sure Firestore Security Rules are open (e.g. read/write allowed).");
  });
}

function sendCustomCommand() {
  const input = document.getElementById("cmd-input");
  if (input) {
    sendCommand(input.value);
    input.value = "";
  }
}

function sendShortcut(text) {
  sendCommand(text);
}

// ── Speech Recognition Integration ────────────────────────────────────
let recognition;
let isListening = false;

if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
  const SpeechGen = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechGen();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = 'en-US';

  recognition.onstart = () => {
    isListening = true;
    const mic = document.getElementById("mic-trigger");
    if (mic) mic.classList.add("listening");
  };

  recognition.onend = () => {
    isListening = false;
    const mic = document.getElementById("mic-trigger");
    if (mic) mic.classList.remove("listening");
  };

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    console.log("Speech transcript:", transcript);
    sendCommand(transcript);
    const display = document.getElementById("status-display");
    if (display) display.innerText = "Voice captured: \"" + transcript + "\". Transmitting...";
  };

  recognition.onerror = (e) => {
    console.error("Speech Recognition Error", e);
    const mic = document.getElementById("mic-trigger");
    if (mic) mic.classList.remove("listening");
  };
}

function toggleVoiceDictation() {
  if (!recognition) {
    alert("Web Speech API is not supported in this browser. Try opening in Chrome or Safari.");
    return;
  }

  if (isListening) {
    recognition.stop();
  } else {
    recognition.start();
  }
}
