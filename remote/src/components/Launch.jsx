import React, { useState } from "react";

export default function Launch({ onSendCommand }) {
  const [copiedId, setCopiedId] = useState(null);
  const [launchedId, setLaunchedId] = useState(null);

  const agents = [
    {
      id: "claude",
      title: "Claude Code",
      description: "Anthropic's coding tool with subagents",
      command: "ollama launch claude",
      icon: (
        <svg viewBox="0 0 100 100" className="agent-icon-svg" style={{ backgroundColor: "#1e1e1e" }}>
          {/* Retro orange robot/character */}
          <rect x="25" y="30" width="50" height="40" rx="8" fill="#e05638" />
          <rect x="35" y="42" width="10" height="10" rx="2" fill="#fff" />
          <rect x="55" y="42" width="10" height="10" rx="2" fill="#fff" />
          <rect x="40" y="45" width="2" height="2" fill="#000" />
          <rect x="60" y="45" width="2" height="2" fill="#000" />
          <rect x="40" y="60" width="20" height="4" rx="2" fill="#111" />
          {/* Small antenna */}
          <rect x="48" y="20" width="4" height="10" fill="#e05638" />
          <circle cx="50" cy="18" r="4" fill="#ff7657" />
        </svg>
      )
    },
    {
      id: "codex-app",
      title: "Codex App",
      description: "An AI agent you can delegate real work to, by OpenAI",
      command: "ollama launch codex-app",
      icon: (
        <svg viewBox="0 0 100 100" className="agent-icon-svg" style={{ backgroundColor: "#2b4c7e" }}>
          {/* Blue icon with terminal/brain concept */}
          <rect x="20" y="25" width="60" height="50" rx="10" fill="#3b6eb4" />
          {/* Screen area */}
          <rect x="26" y="31" width="48" height="38" rx="6" fill="#1b2a47" />
          {/* Terminal prompt symbol */}
          <path d="M34 42 L42 50 L34 58" fill="none" stroke="#00e5ff" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
          <line x1="46" y1="58" x2="62" y2="58" stroke="#00e5ff" strokeWidth="4" strokeLinecap="round" />
        </svg>
      )
    },
    {
      id: "hermes",
      title: "Hermes Agent",
      description: "Self-improving AI agent built by Nous Research",
      command: "ollama launch hermes",
      icon: (
        <svg viewBox="0 0 100 100" className="agent-icon-svg" style={{ backgroundColor: "#111" }}>
          {/* Black circle with winged helmet */}
          <circle cx="50" cy="50" r="40" fill="#222" stroke="#444" strokeWidth="2" />
          {/* Helmet shape */}
          <path d="M35 55 C35 38, 65 38, 65 55 C65 60, 60 65, 50 65 C40 65, 35 60, 35 55 Z" fill="#999" />
          {/* Wing left */}
          <path d="M37 42 C25 40, 20 48, 33 50 C22 52, 24 58, 36 53" fill="#fff" stroke="#ccc" strokeWidth="1" />
          {/* Wing right */}
          <path d="M63 42 C75 40, 80 48, 67 50 C78 52, 76 58, 64 53" fill="#fff" stroke="#ccc" strokeWidth="1" />
          {/* Helmet eye slit */}
          <rect x="42" y="52" width="16" height="4" fill="#00e5ff" />
        </svg>
      )
    },
    {
      id: "openclaw",
      title: "OpenClaw",
      description: "Personal AI with 100+ skills",
      command: "ollama launch openclaw",
      icon: (
        <svg viewBox="0 0 100 100" className="agent-icon-svg" style={{ backgroundColor: "#221111" }}>
          {/* Red lobster claw */}
          <circle cx="50" cy="50" r="40" fill="#301515" />
          {/* Claw bottom */}
          <path d="M32 58 C32 40, 58 40, 62 55 C65 62, 58 68, 48 68 C38 68, 32 62, 32 58 Z" fill="#b91c1c" />
          {/* Claw pincher top */}
          <path d="M42 44 C42 30, 68 28, 62 48 C58 52, 50 50, 42 44 Z" fill="#ef4444" />
          {/* Claw joint */}
          <circle cx="38" cy="60" r="7" fill="#7f1d1d" />
        </svg>
      )
    },
    {
      id: "opencode",
      title: "OpenCode",
      description: "Anomaly's open-source coding agent",
      command: "ollama launch opencode",
      icon: (
        <svg viewBox="0 0 100 100" className="agent-icon-svg" style={{ backgroundColor: "#1e1e1e" }}>
          {/* Dark square with white terminal cursor */}
          <rect x="20" y="20" width="60" height="60" rx="12" fill="#2d2d2d" stroke="#444" strokeWidth="2" />
          {/* Cursor block */}
          <rect x="35" y="35" width="30" height="30" rx="4" fill="#fff" />
          {/* Small terminal bar inside */}
          <rect x="40" y="47" width="20" height="6" fill="#1e1e1e" />
        </svg>
      )
    }
  ];

  const handleCopy = (id, cmd) => {
    navigator.clipboard.writeText(cmd);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 1500);
  };

  const handleLaunch = (id, cmd) => {
    // Send standard laptop launch command
    onSendCommand(`laptop ${cmd}`);
    setLaunchedId(id);
    setTimeout(() => setLaunchedId(null), 2000);
  };

  return (
    <>
      <div className="section-label">Launch Agents</div>
      <div className="launch-section glass-card">
        <div className="launch-intro">
          <div className="launch-title">Ollama AI Agents</div>
          <div className="launch-subtitle">Launch directly on your PC or copy command to run manually</div>
        </div>

        <div className="agents-list">
          {agents.map((agent) => (
            <div key={agent.id} className="agent-card">
              <div className="agent-header">
                <div className="agent-icon-container">
                  {agent.icon}
                </div>
                <div className="agent-info">
                  <div className="agent-name">{agent.title}</div>
                  <div className="agent-desc">{agent.description}</div>
                </div>
              </div>
              
              <div className="agent-command-box">
                <code className="agent-code-text">{agent.command}</code>
                <div className="agent-actions">
                  <button 
                    className={`agent-action-btn copy-btn ${copiedId === agent.id ? "active" : ""}`}
                    onClick={() => handleCopy(agent.id, agent.command)}
                    title="Copy command"
                  >
                    {copiedId === agent.id ? "✓" : (
                      <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                        <path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>
                      </svg>
                    )}
                  </button>
                  <button 
                    className={`agent-action-btn launch-btn ${launchedId === agent.id ? "active" : ""}`}
                    onClick={() => handleLaunch(agent.id, agent.command)}
                    title="Launch on PC"
                  >
                    {launchedId === agent.id ? "▶" : (
                      <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                        <path d="M5 13h11.86l-5.43 5.43 1.42 1.42L21.14 12l-8.29-8.29-1.42 1.42L16.86 11H5v2z"/>
                      </svg>
                    )}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
