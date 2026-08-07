import sys
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

import httpx
import threading
import asyncio
import json

try:
    import websockets
except ImportError:
    websockets = None

class MockRoot:
    def mainloop(self):
        try:
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

class DominusUI:
    def __init__(self, face_path):
        self.face_path = face_path
        self.muted = False
        self.on_text_command = None
        self.on_remote_clicked = None
        self.on_interrupt = None
        self.root = MockRoot()
        self._win = self
        self._ready = True

        # Khoi chay WebSocket client lang nghe lenh dieu khien
        if websockets:
            threading.Thread(target=self._start_ws_client, daemon=True).start()
        else:
            print("[Warning] websockets library not installed. Headless control disabled.")

    def _start_ws_client(self):
        async def listen():
            uri = "ws://127.0.0.1:8003/api/gateway/ws"
            while True:
                try:
                    async with websockets.connect(uri) as websocket:
                        print("[Assistant WS] Connected to Gateway control channel.")
                        while True:
                            message = await websocket.recv()
                            data = json.loads(message)
                            
                            # Xu ly cac lenh dieu khien tu UI Next.js
                            msg_type = data.get("type")
                            if msg_type == "control_mic":
                                self.muted = data.get("muted", False)
                                print(f"[Assistant WS] Mic muted set to {self.muted}")
                            elif msg_type == "control_interrupt":
                                print("[Assistant WS] Interrupt trigger received!")
                                if self.on_interrupt:
                                    self.on_interrupt()
                            elif msg_type == "control_camera":
                                active = data.get("active", False)
                                print(f"[Assistant WS] Camera active set to {active}")
                                if active:
                                    self.start_camera_stream()
                                else:
                                    self.stop_camera_stream()
                            elif msg_type == "text_command":
                                text = data.get("text")
                                print(f"[Assistant WS] Text command received: {text}")
                                if self.on_text_command and text:
                                    self.on_text_command(text)
                except Exception as e:
                    # Tu dong ket noi lai sau 3 giay neu mat ket noi
                    await asyncio.sleep(3)
                    
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(listen())

    def write_log(self, text):
        print(f"[LOG] {text}")
        def send():
            try:
                httpx.post("http://127.0.0.1:8003/api/gateway/ui/log", json={"text": text}, timeout=1.0)
            except Exception:
                pass
        threading.Thread(target=send, daemon=True).start()

    def set_state(self, state):
        print(f"[STATE] {state}")
        def send():
            try:
                httpx.post("http://127.0.0.1:8003/api/gateway/ui/state", json={"state": state}, timeout=1.0)
            except Exception:
                pass
        threading.Thread(target=send, daemon=True).start()

    def prompt_reconfig(self):
        print("[UI] Prompt reconfig requested")

    def start_camera_stream(self):
        print("[UI] Camera stream start requested")

    def stop_camera_stream(self):
        print("[UI] Camera stream stop requested")

    def wait_for_api_key(self):
        import time
        import json
        from pathlib import Path
        
        def check_key():
            try:
                from src.database.connection import get_db_session
                from src.database.models.assistant import DominusAssistantConfig
                with get_db_session() as session:
                    cfg = session.query(DominusAssistantConfig).first()
                    if cfg and cfg.gemini_api_key:
                        return cfg.gemini_api_key
            except Exception:
                pass
            
            try:
                config_path = Path(__file__).resolve().parent / "config" / "api_keys.json"
                if config_path.exists():
                    with open(config_path, "r", encoding="utf-8") as f:
                        return json.load(f).get("gemini_api_key", "")
            except Exception:
                pass
            return ""

        print("[Assistant UI] Checking for Gemini API Key...")
        while not check_key():
            print("[Assistant UI] API Key not found. Please set Gemini API Key in Settings.")
            time.sleep(5)
        print("[Assistant UI] API Key detected. Starting Dominus Assistant...")
