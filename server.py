import http.server
import socketserver
import urllib.request
import urllib.error
import json
import sys
import os

# Load .env file if python-dotenv is installed (optional but recommended)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; fall back to real environment variables

# Get API key from environment variable.
# Set GEMINI_API_KEY in your shell or in a .env file (never commit your real key).
API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_API_KEY_HERE")

class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/api/classify':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            
            try:
                data = json.loads(post_data)
            except json.JSONDecodeError:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error": {"message": "Invalid JSON"}}')
                return
            
            image_base64 = data.get('image')
            mime_type = data.get('mime_type')
            
            if not API_KEY or API_KEY == "YOUR_API_KEY_HERE":
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": {"message": "API key not configured in server.py"}}).encode('utf-8'))
                return

            prompt = (
                "Analyze this waste item. Classify it strictly into exactly one of these four categories: "
                "Metal, Wet Waste, Plastic, Dry Waste. "
                "Return ONLY the category name and nothing else. "
                "The category name must be exactly one of: Metal, Wet Waste, Plastic, Dry Waste."
            )
            
            payload = {
                "contents": [{
                    "parts": [
                        { "text": prompt },
                        { "inline_data": { "mime_type": mime_type, "data": image_base64 } }
                    ]
                }],
                "generationConfig": {
                    "temperature": 0,
                    "maxOutputTokens": 2048,
                }
            }
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={API_KEY}"
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
            
            try:
                with urllib.request.urlopen(req) as response:
                    res_body = response.read()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(res_body)
            except urllib.error.HTTPError as e:
                self.send_response(e.code)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(e.read())
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == '__main__':
    PORT = 5500
    with socketserver.TCPServer(("", PORT), CustomHandler) as httpd:
        print(f"Serving at http://localhost:{PORT}")
        print("Please edit server.py to set your API_KEY.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
