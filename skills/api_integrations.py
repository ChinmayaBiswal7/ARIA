"""
api_integrations.py — Jarvis-style core API integrations for ARIA
==================================================================
Implements:
1. Tavily Search API
2. CricAPI / RapidAPI Cricbuzz (with Cricbuzz scraper fallback)
3. OpenWeatherMap API (with offline fallback)
4. Whisper STT transcription (via Groq API endpoint)
5. ElevenLabs TTS voice synthesis (with Edge-TTS fallback)
6. GitHub API automation helper
7. Telegram Bot remote control thread
"""

import os
import requests
import json
import time
import threading
from bs4 import BeautifulSoup

PROJECT_DIR = r"c:\D FOLDER\Projects\AI"

class APIIntegrations:
    def __init__(self):
        self.tavily_key = self._load_key("tavily_api_key.txt", "TAVILY_API_KEY")
        self.cric_key = self._load_key("cric_api_key.txt", "CRIC_API_KEY")
        self.weather_key = self._load_key("openweather_api_key.txt", "OPENWEATHER_API_KEY")
        self.eleven_key = self._load_key("elevenlabs_api_key.txt", "ELEVENLABS_API_KEY")
        self.github_token = self._load_key("github_token.txt", "GITHUB_TOKEN")
        self.telegram_token = self._load_key("telegram_bot_token.txt", "TELEGRAM_BOT_TOKEN")
        
        # Load Groq API Key for Whisper fallback
        self.groq_key = self._load_key("groq_api_key.txt", "GROQ_API_KEY")

    def _load_key(self, filename, env_var):
        """Load API Key from file or environment variable."""
        if os.environ.get(env_var):
            return os.environ.get(env_var).strip()
        
        path = os.path.join(PROJECT_DIR, filename)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:
                pass
        return None

    # --- 1. Tavily Search API ---
    def tavily_search(self, query, limit=5):
        """Query Tavily Search API. Falls back to None if key missing."""
        if not self.tavily_key:
            print("[Integrations/Tavily] Key missing. Skipping Tavily search...")
            return None
            
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": self.tavily_key,
            "query": query,
            "search_depth": "basic",
            "max_results": limit
        }
        
        try:
            print(f"[Integrations/Tavily] Querying: {query}...")
            response = requests.post(url, json=payload, timeout=8)
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                summary_lines = []
                for idx, r in enumerate(results):
                    summary_lines.append(f"Source: {r.get('title')} ({r.get('url')})\nSnippet: {r.get('content')}")
                return "\n\n".join(summary_lines)
            else:
                print(f"[Integrations/Tavily] Error {response.status_code}: {response.text}")
        except Exception as e:
            print(f"[Integrations/Tavily] Request failed: {e}")
        return None

    # --- 2. CricAPI / RapidAPI Cricbuzz (Live Score & Fallback Scraper) ---
    def get_live_cricket(self, match_query="RCB"):
        """Get live cricket score from API, falling back to scrapers."""
        if self.cric_key:
            # Let's try RapidAPI Cricbuzz endpoint first
            url = "https://cricbuzz-cricket.p.rapidapi.com/matches/v1/live"
            headers = {
                "X-RapidAPI-Key": self.cric_key,
                "X-RapidAPI-Host": "cricbuzz-cricket.p.rapidapi.com"
            }
            try:
                response = requests.get(url, headers=headers, timeout=6)
                if response.status_code == 200:
                    data = response.json()
                    print("[Integrations/Cricket] API success. Parsing Live Matches...")
                    # Return custom parsing or match formatting
                    return self._parse_cricbuzz_api(data, match_query)
            except Exception as e:
                print(f"[Integrations/Cricket] API request error: {e}")

        # Fallback Scraper (scrape Cricbuzz live match scores page)
        print("[Integrations/Cricket] Calling fallback Cricbuzz scraper...")
        return self.scrape_cricbuzz_live_scores(match_query)

    def _parse_cricbuzz_api(self, data, query):
        """Format Cricbuzz API output into a human-readable match summary."""
        try:
            matches = data.get("typeMatches", [])
            query_lower = query.lower()
            
            for m_type in matches:
                for match_entry in m_type.get("seriesMatches", []):
                    for match in match_entry.get("seriesAdWrapper", {}).get("matches", []):
                        m_info = match.get("matchInfo", {})
                        m_state = match.get("matchState", {}).get("state", "")
                        team1 = m_info.get("team1", {}).get("teamName", "")
                        team2 = m_info.get("team2", {}).get("teamName", "")
                        
                        if query_lower in team1.lower() or query_lower in team2.lower():
                            status = match.get("matchInfo", {}).get("status", "")
                            score_str = f"Live Match: {team1} vs {team2}. State: {m_state}. Status: {status}."
                            return score_str
            return f"No live matches found matching query '{query}' in Cricbuzz API."
        except Exception as e:
            return f"Error parsing Cricbuzz API: {e}"

    def scrape_cricbuzz_live_scores(self, match_query):
        """Scrape live scores directly from Cricbuzz."""
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            res = requests.get("https://www.cricbuzz.com/cricket-match/live-scores", headers=headers, timeout=6)
            if res.status_code != 200:
                return f"Could not retrieve scores. Status code: {res.status_code}"
                
            soup = BeautifulSoup(res.text, "html.parser")
            matched_cards = []
            q_lower = match_query.lower()
            
            for a in soup.find_all("a"):
                txt = a.get_text()
                if not txt:
                    continue
                txt_lower = txt.lower()
                is_match = any(x in txt_lower for x in ["/", "won by", "beat", "preview", "opt to", "choose to", "runs", "wickets"])
                if is_match and q_lower in txt_lower:
                    card_text = " | ".join([s.strip() for s in a.get_text(separator=" | ").split("|") if s.strip()])
                    matched_cards.append(card_text)
                    
            if matched_cards:
                return "\n".join(matched_cards)
            return f"No live scores or match cards found on Cricbuzz matching '{match_query}'."
        except Exception as e:
            return f"Error scraping Cricbuzz: {e}"

    # --- 3. OpenWeatherMap API ---
    def get_weather(self, city="Delhi"):
        """Fetch current weather for a city."""
        if not self.weather_key:
            print("[Integrations/Weather] Key missing. Using offline search mock weather...")
            return f"Weather for {city}: API Key missing. Please set OpenWeatherMap API key."
            
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={self.weather_key}&units=metric"
        try:
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                temp = data["main"]["temp"]
                feels_like = data["main"]["feels_like"]
                humidity = data["main"]["humidity"]
                desc = data["weather"][0]["description"]
                wind = data["wind"]["speed"]
                return f"Current Weather in {city.capitalize()}: {temp}°C, {desc.capitalize()}. Feels like {feels_like}°C, Humidity: {humidity}%, Wind Speed: {wind} m/s."
            elif res.status_code == 404:
                return f"City '{city}' not found in OpenWeatherMap directory."
            else:
                return f"Weather API error: {res.status_code}."
        except Exception as e:
            return f"Failed to retrieve weather: {e}"

    # --- 4. Whisper STT Transcription (via Groq API) ---
    def transcribe_audio_groq(self, file_path):
        """Transcribe an audio file using Groq's high-speed Whisper API endpoint."""
        if not self.groq_key or not os.path.exists(file_path):
            print("[Integrations/Whisper] Groq API Key or audio file missing.")
            return None
            
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self.groq_key}"}
        
        try:
            with open(file_path, "rb") as f:
                files = {
                    "file": (os.path.basename(file_path), f, "audio/mp3"),
                    "model": (None, "whisper-large-v3"),
                    "response_format": (None, "json"),
                    "language": (None, "en")
                }
                res = requests.post(url, headers=headers, files=files, timeout=12)
                if res.status_code == 200:
                    return res.json().get("text", "").strip()
                else:
                    print(f"[Integrations/Whisper] Transcribe failed {res.status_code}: {res.text}")
        except Exception as e:
            print(f"[Integrations/Whisper] Request error: {e}")
        return None

    # --- 5. ElevenLabs TTS Voice Synthesis ---
    def speak_elevenlabs(self, text, output_path="speech.mp3", voice_id="21m00Tcm4TlvDq8ikWAM"):
        """Synthesize ultra-realistic speech using ElevenLabs API."""
        if not self.eleven_key:
            print("[Integrations/ElevenLabs] Key missing. Skipping Premium ElevenLabs voice.")
            return False
            
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": self.eleven_key
        }
        payload = {
            "text": text,
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75
            }
        }
        
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=15)
            if res.status_code == 200:
                with open(output_path, "wb") as f:
                    f.write(res.content)
                return True
            else:
                print(f"[Integrations/ElevenLabs] TTS generation failed: {res.status_code} - {res.text}")
        except Exception as e:
            print(f"[Integrations/ElevenLabs] Request error: {e}")
        return False

    # --- 6. GitHub API Automation Helper ---
    def github_helper(self, action="list", repo_name=None, extra_params=None):
        """Automate GitHub tasks like listing repositories or commits."""
        if not self.github_token:
            return "GitHub Token missing. Please save it to github_token.txt."
            
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        base_url = "https://api.github.com"
        
        try:
            if action == "list":
                url = f"{base_url}/user/repos?sort=updated&per_page=5"
                res = requests.get(url, headers=headers, timeout=6)
                if res.status_code == 200:
                    repos = res.json()
                    lines = [f"- {r['name']} (URL: {r['html_url']}, Description: {r['description']})" for r in repos]
                    return "Your 5 most recently updated GitHub repositories:\n" + "\n".join(lines)
                    
            elif action == "commits" and repo_name:
                url = f"{base_url}/repos/{repo_name}/commits?per_page=5"
                res = requests.get(url, headers=headers, timeout=6)
                if res.status_code == 200:
                    commits = res.json()
                    lines = [f"- {c['commit']['committer']['name']}: {c['commit']['message']} ({c['sha'][:7]})" for c in commits]
                    return f"Last 5 commits in repository '{repo_name}':\n" + "\n".join(lines)
            
            elif action == "create_issue" and repo_name and extra_params:
                title = extra_params.get("title", "ARIA Auto-created Issue")
                body = extra_params.get("body", "Created automatically by ARIA Desktop Assistant.")
                url = f"{base_url}/repos/{repo_name}/issues"
                payload = {"title": title, "body": body}
                res = requests.post(url, headers=headers, json=payload, timeout=6)
                if res.status_code == 201:
                    issue = res.json()
                    return f"Successfully created issue #{issue['number']}: '{title}' at {issue['html_url']}."
                
            return f"Action '{action}' failed or not fully supported."
        except Exception as e:
            return f"GitHub API call failed: {e}"

    # --- 7. Telegram Bot Remote Control Integration ---
    def start_telegram_bot(self, aria_instance):
        """Starts a background Telegram Bot thread to remotely execute commands on ARIA."""
        if not self.telegram_token:
            print("[Integrations/Telegram] Bot token missing. Remote control Telegram Bot not started.")
            return
            
        def bot_loop():
            offset = None
            print("[Integrations/Telegram] Remote Control Bot started and polling...")
            
            while True:
                url = f"https://api.telegram.org/bot{self.telegram_token}/getUpdates"
                params = {"timeout": 30}
                if offset:
                    params["offset"] = offset
                    
                try:
                    res = requests.get(url, params=params, timeout=35)
                    if res.status_code == 200:
                        data = res.json()
                        for update in data.get("result", []):
                            offset = update["update_id"] + 1
                            message = update.get("message", {})
                            chat_id = message.get("chat", {}).get("id")
                            text = message.get("text", "")
                            
                            if chat_id and text:
                                self._handle_telegram_message(aria_instance, chat_id, text)
                    else:
                        time.sleep(5)
                except Exception as e:
                    print(f"[Integrations/Telegram] Polling error: {e}")
                    time.sleep(5)
                    
        t = threading.Thread(target=bot_loop, daemon=True)
        t.start()

    def _handle_telegram_message(self, aria_instance, chat_id, text):
        """Process remote commands sent via Telegram Bot."""
        print(f"[Integrations/Telegram] Received remote command from Chat ID {chat_id}: '{text}'")
        
        reply_url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        photo_url = f"https://api.telegram.org/bot{self.telegram_token}/sendPhoto"

        # Security Whitelist Enforcement
        if not hasattr(aria_instance, "security") or not aria_instance.security.is_telegram_authorized(chat_id):
            print(f"[SecurityGuard] Rejected remote command from unauthorized Chat ID {chat_id}")
            msg = f"Access Denied. Chat ID {chat_id} is not authorized on this host.\n" \
                  f"To whitelist, add it to C:\\D FOLDER\\Projects\\AI\\telegram_authorized_chat_id.txt"
            requests.post(reply_url, json={"chat_id": chat_id, "text": msg})
            return
        
        if text.lower() == "/start":
            msg = "Welcome to ARIA Remote Control Bot!\n\nCommands:\n/status - Get current screen/app state\n/screenshot - Get live screenshot of the PC\n/cmd [text] - Send user input command directly to ARIA brain"
            requests.post(reply_url, json={"chat_id": chat_id, "text": msg})
            return
            
        if text.lower() == "/status":
            try:
                from dashboard import CognitionState
                status_txt = f"Goal: {CognitionState.active_goal}\nSubtask: {CognitionState.active_subtask}\nModel: {CognitionState.model_in_use}\nActive Window: {CognitionState.active_window}"
                requests.post(reply_url, json={"chat_id": chat_id, "text": status_txt})
            except Exception as e:
                requests.post(reply_url, json={"chat_id": chat_id, "text": f"Error fetching status: {e}"})
            return

        if text.lower() == "/screenshot":
            try:
                from PIL import ImageGrab
                import io
                screenshot = ImageGrab.grab()
                img_byte_arr = io.BytesIO()
                screenshot.save(img_byte_arr, format='PNG')
                img_byte_arr.seek(0)
                
                files = {'photo': ('screenshot.png', img_byte_arr, 'image/png')}
                requests.post(photo_url, data={'chat_id': chat_id, 'caption': 'Live PC Screen View'}, files=files)
            except Exception as e:
                requests.post(reply_url, json={"chat_id": chat_id, "text": f"Failed to take screenshot: {e}"})
            return
            
        if text.lower().startswith("/cmd "):
            cmd = text[5:].strip()
            requests.post(reply_url, json={"chat_id": chat_id, "text": f"Forwarding command to ARIA: '{cmd}'..."})
            
            # Execute on ARIA instance asynchronously
            def run_remote_cmd():
                try:
                    # Execute command in ARIA (which runs in main thread/gui context)
                    # We send response back to telegram when done
                    response = aria_instance._handle_input(cmd, remote=True)
                    clean_res = re.sub(r'\[[A-Z]+:[^\]]*\]', '', response or "")
                    clean_res = re.sub(r'\[[A-Z]+\]', '', clean_res).strip()
                    requests.post(reply_url, json={"chat_id": chat_id, "text": f"ARIA Response:\n{clean_res}"})
                except Exception as e:
                    requests.post(reply_url, json={"chat_id": chat_id, "text": f"Error executing command: {e}"})
            
            import re
            threading.Thread(target=run_remote_cmd, daemon=True).start()
            return
            
        requests.post(reply_url, json={"chat_id": chat_id, "text": "Unknown command. Use /start to list available commands."})
