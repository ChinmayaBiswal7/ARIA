import React, { useState, useEffect } from 'react';
import { doc, onSnapshot } from 'firebase/firestore';
import '../health.css';

export default function HealthWidget({ db }) {
  const [healthData, setHealthData] = useState({
    steps: 0,
    calories: 0,
    sleepHours: 0,
    sleepQuality: 'Unknown',
    heartRate: 0,
    spo2: 0,
    timestamp: 0
  });

  useEffect(() => {
    if (!db) return;
    const unsub = onSnapshot(doc(db, "health", "latest"), (docSnap) => {
      if (docSnap.exists()) {
        const data = docSnap.data();
        setHealthData({
          steps: data.steps || 0,
          calories: data.calories || 0,
          sleepHours: data.sleepHours || 0,
          sleepQuality: data.sleepQuality || 'Unknown',
          heartRate: data.heartRate || 0,
          spo2: data.spo2 || 0,
          timestamp: data.timestamp || 0
        });
      }
    });
    return () => unsub();
  }, [db]);

  const timeAgo = () => {
    if (!healthData.timestamp) return "Never synced";
    const mins = Math.floor((Date.now() / 1000 - healthData.timestamp) / 60);
    if (mins < 1) return "Just now";
    if (mins < 60) return `${mins}m ago`;
    return `${Math.floor(mins/60)}h ago`;
  };

  return (
    <div className="health-widget glass">
      <div className="health-header">
        <h3>Health & Fitness</h3>
        <span className="health-sync">Sync: {timeAgo()}</span>
      </div>
      
      <div className="health-grid">
        <div className="health-card">
          <div className="health-icon steps-icon">👟</div>
          <div className="health-val">{healthData.steps}</div>
          <div className="health-label">Steps</div>
        </div>
        
        <div className="health-card">
          <div className="health-icon cal-icon">🔥</div>
          <div className="health-val">{Math.round(healthData.calories)}</div>
          <div className="health-label">kcal</div>
        </div>

        <div className="health-card">
          <div className="health-icon sleep-icon">🌙</div>
          <div className="health-val">{healthData.sleepHours > 0 ? healthData.sleepHours.toFixed(1) : '-'}</div>
          <div className="health-label">{healthData.sleepQuality}</div>
        </div>

        <div className="health-card">
          <div className="health-icon hr-icon">❤️</div>
          <div className="health-val">{healthData.heartRate > 0 ? healthData.heartRate : '-'}</div>
          <div className="health-label">bpm</div>
        </div>
      </div>
    </div>
  );
}
