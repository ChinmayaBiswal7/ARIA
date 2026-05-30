import React from "react";

export default function Shortcuts({ onSendCommand }) {
  const shortcuts = [
    { icon: "CALL", label: "Phone", cmd: "open phone" },
    { icon: "SMS", label: "Messages", cmd: "open messages" },
    { icon: "MAIL", label: "Gmail", cmd: "open Gmail" },
    { icon: "IG", label: "Instagram", cmd: "open Instagram" },
    { icon: "WEB", label: "Search", cmd: "search latest news" },
    { icon: "PC", label: "Laptop Ping", cmd: "laptop pc status" }
  ];

  return (
    <>
      <div className="section-label">Phone Shortcuts</div>
      <div className="controls-grid">
        {shortcuts.map((s, i) => (
          <div
            key={i}
            className="ctrl-btn"
            onClick={() => onSendCommand(s.cmd)}
          >
            <span className="ctrl-icon">{s.icon}</span>
            <div className="ctrl-label">{s.label}</div>
          </div>
        ))}
      </div>
    </>
  );
}
