import http.server
import socketserver
import urllib.request
import urllib.error
import json
import os

# Load .env file if python-dotenv is installed (optional but recommended)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # fall back to real environment variables

# OpenRouter API key — set in .env as OPENROUTER_API_KEY
API_KEY = os.environ.get("OPENROUTER_API_KEY", "YOUR_API_KEY_HERE")

# OpenRouter model — gemini-2.0-flash supports vision and is fast
MODEL = "google/gemini-2.5-flash"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

PROMPT = (
    "Analyze this waste item. Classify it strictly into exactly one of these four categories: "
    "Metal, Wet Waste, Plastic, Dry Waste. "
    "Return ONLY the category name and nothing else. "
    "The category name must be exactly one of: Metal, Wet Waste, Plastic, Dry Waste."
)


class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/api/classify':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)

            try:
                data = json.loads(post_data)
            except json.JSONDecodeError:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": {"message": "Invalid JSON"}}')
                return

            image_base64 = data.get('image')
            mime_type = data.get('mime_type', 'image/jpeg')

            if not API_KEY or API_KEY == "YOUR_API_KEY_HERE":
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(
                    {"error": {"message": "OPENROUTER_API_KEY not configured. Set it in your .env file."}}
                ).encode('utf-8'))
                return

            # OpenRouter uses the OpenAI-compatible chat completions format
            payload = {
                "model": MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{image_base64}"
                                }
                            }
                        ]
                    }
                ],
                "temperature": 0,
                "max_tokens": 50,
            }

            req = urllib.request.Request(
                OPENROUTER_URL,
                data=json.dumps(payload).encode('utf-8'),
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {API_KEY}',
                    'HTTP-Referer': 'http://localhost:5500',
                    'X-Title': 'WasteAI',
                }
            )

            try:
                with urllib.request.urlopen(req) as response:
                    res_body = response.read()
                    or_data = json.loads(res_body)

                    # Extract plain text from OpenRouter response
                    text = (
                        or_data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                        .strip()
                    )

                    # Re-wrap in Gemini-compatible shape so app.js needs no changes
                    gemini_compat = {
                        "candidates": [{
                            "content": {"parts": [{"text": text}]},
                            "finishReason": "STOP"
                        }]
                    }

                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(gemini_compat).encode('utf-8'))

            except urllib.error.HTTPError as e:
                err_body = e.read()
                self.send_response(e.code)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(err_body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress noisy access log; only show our own prints
        pass


if __name__ == '__main__':
    PORT = 5500
    print(f"[WasteAI] Using model : {MODEL}")
    print(f"[WasteAI] API key set : {'YES' if API_KEY != 'YOUR_API_KEY_HERE' else 'NO — set OPENROUTER_API_KEY in .env'}")
    with socketserver.TCPServer(("", PORT), CustomHandler) as httpd:
        print(f"[WasteAI] Serving at  : http://localhost:{PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[WasteAI] Server stopped.")
