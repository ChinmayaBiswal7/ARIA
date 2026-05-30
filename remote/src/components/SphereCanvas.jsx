import React, { useEffect, useRef } from "react";

// ── 3D Particle Sphere class (Cinematic Jarvis Hologram - Optimized) ─────
class SphereRenderer {
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

    // Rich palettes (colors with opacity inside values)
    this.palettes = {
      "OFFLINE":   { core: "rgba(100, 110, 120, 0.95)", glow: "rgba(40, 45, 50, 0.4)", line: "rgba(80, 90, 100, 0.15)", glowColor: "#646e78" },
      "IDLE":      { core: "rgba(0, 140, 255, 0.95)",  glow: "rgba(0, 70, 180, 0.35)",  line: "rgba(0, 100, 220, 0.12)", glowColor: "#008cff" },
      "LISTENING": { core: "rgba(0, 229, 255, 0.95)",  glow: "rgba(0, 180, 220, 0.45)",  line: "rgba(0, 180, 220, 0.2)",  glowColor: "#00e5ff" },
      "THINKING":  { core: "rgba(255, 140, 0, 0.95)",   glow: "rgba(220, 90, 0, 0.45)",   line: "rgba(220, 100, 0, 0.2)",  glowColor: "#ff8c00" }, // Fiery orange/amber
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

    // Get mic volume level (optimized, no array allocation)
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

    // Mock volume if speaking and Web Speech API has no visual analyser node
    if (this.state === "SPEAKING" && micVolume === 0) {
      micVolume = 0.12 + Math.abs(Math.sin(this.time * 6)) * 0.22;
    }

    // Sphere breathing pulse
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

    // Spin dashboard orbits
    this.orbits.forEach(orb => {
      let orbitSpeed = orb.speed * (1.0 + micVolume * 3.0);
      orb.angle = (orb.angle + orbitSpeed) % 360;
    });

    // Dynamic visualizer values
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

    // CRITICAL PERFORMANCE: Disable shadowBlur (blurs at 60 FPS cause heavy browser lag)
    this.ctx.shadowBlur = 0; 

    // 1. Ambient Background glow (radial gradient - hardware accelerated)
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
        
        // Outer Ring
        this.ctx.beginPath();
        this.ctx.arc(centerX, centerY, rOrb, 0, 2 * Math.PI);
        this.ctx.strokeStyle = pal.line;
        this.ctx.lineWidth = 1;
        this.ctx.setLineDash(orb.dash);
        this.ctx.stroke();
        
        // Rotating heavy block markings
        this.ctx.save();
        this.ctx.translate(centerX, centerY);
        this.ctx.rotate(orb.angle * Math.PI / 180);
        
        for (let a = 0; a < 360; a += 120) { // 3 blocks instead of 4 to optimize path draw calls
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

    // 3. Project 3D Nodes with voice displacement
    let projected = this.basePts.map(bp => {
      let cy = Math.cos(this.ry), sy = Math.sin(this.ry);
      let rx1 = bp.x * cy + bp.z * sy;
      let ry1 = bp.y;
      let rz1 = -bp.x * sy + bp.z * cy;

      let cx = Math.cos(this.rx), sx = Math.sin(this.rx);
      let rx2 = rx1;
      let ry2 = ry1 * cx - rz1 * sx;
      let rz2 = ry1 * sx + rz1 * cx;

      // Sonic vibration multiplier!
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

    // 4. Draw mesh lines (Optimized connections - only in foreground & higher sample steps)
    for (let i = 0; i < projected.length; i += 3) {
      if (projected[i].z < -0.25) continue; // Skip lines in far background
      
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

    // 7. Radial Equalizer sweeper lines (Jarvis Movie VFX)
    if (this.state === "SPEAKING" || this.state === "LISTENING") {
      let spikeCount = 30; // 30 spikes is plenty for detail while saving processing
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

export default function SphereCanvas({ state, audioAnalyser, audioDataArray }) {
  const canvasRef = useRef(null);
  const rendererRef = useRef(null);

  useEffect(() => {
    if (canvasRef.current) {
      rendererRef.current = new SphereRenderer(canvasRef.current);
    }
  }, []);

  useEffect(() => {
    if (rendererRef.current) {
      rendererRef.current.setState(state);
    }
  }, [state]);

  useEffect(() => {
    if (rendererRef.current) {
      rendererRef.current.audioAnalyser = audioAnalyser;
      rendererRef.current.audioDataArray = audioDataArray;
    }
  }, [audioAnalyser, audioDataArray]);

  useEffect(() => {
    let animationId;
    const loop = () => {
      if (rendererRef.current) {
        let vol = rendererRef.current.tick();
        rendererRef.current.draw(vol);
      }
      animationId = requestAnimationFrame(loop);
    };
    animationId = requestAnimationFrame(loop);

    return () => cancelAnimationFrame(animationId);
  }, []);

  return <canvas id="sphere-canvas" ref={canvasRef} width="340" height="340" />;
}
