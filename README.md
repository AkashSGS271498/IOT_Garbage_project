# WasteAI

WasteAI is a Smart Waste Segregation System that uses the Gemini API to classify waste items from images and a simulated robotic arm (via Raspberry Pi Pico W on Wokwi) to sort them into correct categories (Metal, Wet Waste, Plastic, Dry Waste).

## Project Overview

The project is divided into three main components:

1. **Frontend (`index.html`, `app.js`, `style.css`)**: 
   A clean, interactive web interface where users can upload an image of a waste item. It sends the image to the backend for classification. Once classified, it visualizes the sorting process and publishes a command to a public MQTT broker to trigger the hardware.

2. **Backend (`server.py`)**: 
   A lightweight Python HTTP server that exposes an `/api/classify` endpoint. It receives the base64 image from the frontend and prompts the **Gemini 3.8 Flash** model to strictly classify the waste into one of the four categories.

3. **Hardware Simulation (`wokwi/main.py`, `wokwi/wokwi.toml`)**: 
   A MicroPython script running on a simulated Raspberry Pi Pico W (using Wokwi). It connects to WiFi and listens to the MQTT broker for classification commands. Upon receiving a command, it actuates simulated servos to drop the waste into the corresponding bin. It also supports a local sensor fallback mode using slide switches.

## Commands to Run the Project

### 1. Set up the Backend
Before running the backend, you must provide your Gemini API key.

1. Copy the example env file:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` and replace the placeholder with your actual key:
   ```
   GEMINI_API_KEY=your_real_api_key_here
   ```
   > Get a free key at https://aistudio.google.com/app/apikey

   Alternatively, you can export it directly in your shell:
   ```bash
   # macOS / Linux
   export GEMINI_API_KEY=your_real_api_key_here

   # Windows PowerShell
   $env:GEMINI_API_KEY="your_real_api_key_here"
   ```

### 2. Start the Server
Run the simple HTTP server using Python. This server will handle API requests and serve the frontend files.
```bash
python server.py
```
The application will be accessible at `http://localhost:5500`.

### 3. Run the Hardware Simulation (Wokwi)
To simulate the physical waste sorting mechanism:
- If you have the [Wokwi extension for VS Code](https://marketplace.visualstudio.com/items?itemName=Wokwi.wokwi-vscode) installed, open the `wokwi/wokwi.toml` file or run the command `Wokwi: Start Simulator` in your editor.
- The Pico W will boot up, connect to the virtual WiFi network, connect to the MQTT broker, and wait for commands from the web app.

### 4. Test the Pipeline
1. Open `http://localhost:5500` in your web browser.
2. Upload an image of a waste item.
3. Click "Classify Waste".
4. The backend will classify it, the frontend will show the result and the virtual robotic arm movement, and the Wokwi simulated Pico W will receive the MQTT command and move its servos accordingly!
