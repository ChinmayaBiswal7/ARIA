import React, { useState, useRef } from "react";

export default function Console({ onSendCommand }) {
  const [inputValue, setInputValue] = useState("");
  const fileInputRef = useRef(null);

  const handleSend = () => {
    if (!inputValue.trim()) return;
    onSendCommand(inputValue);
    setInputValue("");
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter") {
      handleSend();
    }
  };

  const handleCameraClick = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onloadend = () => {
      const img = new Image();
      img.onload = () => {
        // Resize and compress the image to keep Firestore doc size small
        const canvas = document.createElement("canvas");
        const maxDim = 640;
        let width = img.width;
        let height = img.height;
        if (width > maxDim || height > maxDim) {
          if (width > height) {
            height = Math.round((height * maxDim) / width);
            width = maxDim;
          } else {
            width = Math.round((width * maxDim) / height);
            height = maxDim;
          }
        }
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, 0, 0, width, height);
        
        // Compress as jpeg with 0.7 quality
        const compressedB64 = canvas.toDataURL("image/jpeg", 0.7);
        onSendCommand(inputValue.trim() || "Describe what is visible in this photo", compressedB64);
        setInputValue("");
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  };

  return (
    <>
      <div className="section-label first">Command Console</div>
      <div className="glass-card input-section">
        <button className="camera-btn" onClick={handleCameraClick} title="Capture Photo">
          📷
        </button>
        <input
          type="file"
          accept="image/*"
          capture="environment"
          style={{ display: "none" }}
          ref={fileInputRef}
          onChange={handleFileChange}
        />
        <input
          type="text"
          placeholder="Type a command or photo query..."
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          autoComplete="off"
          autoCorrect="off"
          spellCheck="false"
        />
        <button className="send-btn" onClick={handleSend}>
          Send
        </button>
      </div>
    </>
  );
}
