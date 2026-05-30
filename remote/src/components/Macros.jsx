import React, { useState } from "react";

export default function Macros({ onSendCommand }) {
  const [activeMacroId, setActiveMacroId] = useState(null);

  const macros = [
    { id: "m0", icon: "WA", title: "WhatsApp", desc: "Open on phone", cmd: "open WhatsApp" },
    { id: "m1", icon: "YT", title: "YouTube", desc: "Open on phone", cmd: "open YouTube" },
    { id: "m2", icon: "CAM", title: "Camera", desc: "Open phone camera", cmd: "open camera" },
    { id: "m3", icon: "CHR", title: "Chrome", desc: "Open browser", cmd: "open Chrome" },
    { id: "m4", icon: "MAP", title: "Maps", desc: "Open maps", cmd: "open maps" },
    { id: "m5", icon: "SET", title: "Settings", desc: "Open settings", cmd: "open settings" }
  ];

  const handleMacroClick = (id, cmd) => {
    setActiveMacroId(id);
    onSendCommand(cmd);
    setTimeout(() => {
      setActiveMacroId(null);
    }, 1200);
  };

  return (
    <>
      <div className="section-label">Phone Apps</div>
      <div className="macros-grid">
        {macros.map((m) => (
          <div
            key={m.id}
            className={`macro-card ${activeMacroId === m.id ? "sent" : ""}`}
            onClick={() => handleMacroClick(m.id, m.cmd)}
          >
            <span className="macro-icon">{m.icon}</span>
            <div className="macro-title">{m.title}</div>
            <div className="macro-desc">{m.desc}</div>
          </div>
        ))}
      </div>
    </>
  );
}
