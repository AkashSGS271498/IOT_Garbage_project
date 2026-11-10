# WasteAI — Smart Waste Segregation System

WasteAI is an AI-powered waste segregation system that uses **Gemini** (via OpenRouter) to classify waste items from images and a simulated robotic arm (Raspberry Pi Pico W on Wokwi) to sort them into the correct bin — **Metal**, **Wet Waste**, **Plastic**, or **Dry Waste**.

## Architecture

```
┌──────────────┐    POST /api/classify    ┌──────────────┐    OpenRouter API     ┌─────────────┐
│   Frontend   │ ───────────────────────► │   Backend    │ ──────────────────►   │  Gemini 2.5 │
│  index.html  │ ◄─────────────────────── │  server.py   │ ◄──────────────────   │    Flash    │
│   app.js     │    classification result │  (Python)    │    category text      └─────────────┘
└──────┬───────┘                          └──────────────┘
       │
       │  MQTT (HiveMQ public broker)
       │  topic: skit/akash_project/command
       ▼
┌──────────────┐
│  Pico W      │  wokwi/main.py
│  (Wokwi)     │  Servos sort waste into bins
└──────────────┘
```

## Components

### 1. Frontend (`index.html`, `app.js`, `style.css`)
- Interactive web UI with drag-and-drop image upload
- Calls the backend `/api/classify` endpoint
- Connects to HiveMQ public MQTT broker over WebSocket
- Visualizes the robotic arm sorting animation on a canvas
- Shows real-time Pico status (Online / Offline) and delivery acknowledgements

### 2. Backend (`server.py`)
- Lightweight Python HTTP server (no dependencies beyond `python-dotenv`)
- Proxies image classification requests to **OpenRouter** (`google/gemini-2.5-flash`)
- Converts the OpenRouter (OpenAI-compatible) response to a Gemini-compatible shape so the frontend needs no special handling

### 3. Hardware Simulation (`wokwi/main.py`, `wokwi/diagram.json`)
- MicroPython running on a simulated **Raspberry Pi Pico W** via [Wokwi](https://wokwi.com/)
- Connects to WiFi and subscribes to MQTT commands from the web app
- Actuates two servos (base arm + gripper) to sort waste into the corresponding bin
- Publishes acknowledgements (`received` → `done`) back to the web app
- Supports local sensor fallback via slide switches and a push-button

## Getting Started

### Prerequisites
- **Python 3.10+**
- An **OpenRouter API key** — get one free at [openrouter.ai/keys](https://openrouter.ai/keys)
- [Wokwi VS Code Extension](https://marketplace.visualstudio.com/items?itemName=Wokwi.wokwi-vscode) (for the hardware simulation)

### 1. Set Up the API Key

```bash
# Copy the example env file
cp .env.example .env
```

Open `.env` and paste your OpenRouter key:

```
OPENROUTER_API_KEY=sk-or-v1-your_key_here
```

### 2. Start the Server

```bash
python server.py
```

You should see:

```
[WasteAI] Using model : google/gemini-2.5-flash
[WasteAI] API key set : YES
[WasteAI] Serving at  : http://localhost:5500
```

### 3. Run the Hardware Simulation (Wokwi)

1. Open `wokwi/diagram.json` or `wokwi/wokwi.toml` in VS Code
2. Run the command **`Wokwi: Start Simulator`**
3. The Pico W console should show:
   ```
   --- WasteAI System Starting ---
   [WiFi] Connected, IP: 10.10.0.1
   [MQTT] Connected and subscribed to skit/akash_project/command
   ```

### 4. Test the Full Pipeline

1. Open [http://localhost:5500](http://localhost:5500) in your browser
2. Wait for **MQTT: Connected** and **Pico: ONLINE 🟢** in the header
3. Upload an image of a waste item
4. Click **Classify Waste**
5. The backend classifies it via Gemini → the frontend shows the result → the Pico receives the MQTT command and moves its servos to the correct bin

## MQTT Topics

| Topic | Direction | Purpose |
|-------|-----------|---------|
| `skit/akash_project/command` | Web → Pico | Classification command (JSON `{id, category}`) |
| `skit/akash_project/ack` | Pico → Web | Acknowledgement (`received` / `done` / `error`) |
| `skit/akash_project/status` | Pico → Web | Online / Offline (LWT) |

## Project Structure

```
├── index.html          # Frontend UI
├── app.js              # Frontend logic + MQTT + servo animation
├── style.css           # Styling
├── server.py           # Python backend (OpenRouter proxy)
├── .env.example        # Template for API key
├── .gitignore
├── README.md
└── wokwi/
    ├── main.py         # MicroPython code for Pico W
    ├── diagram.json    # Wokwi circuit layout
    └── wokwi.toml      # Wokwi config
```
