import network
import time
import json
from machine import Pin, PWM
from umqtt.simple import MQTTClient

# ─────────────────────────────────────────────────────────
#  WasteAI — MicroPython MQTT Client for Raspberry Pi Pico W
#  Board:  wokwi-pi-pico-w
#  Broker: broker.hivemq.com  (public, no auth needed)
#  Topic:  skit/garbage_sorter/command
#  Payload: plain text  → "Metal" | "Wet Waste" | "Plastic" | "Dry Waste"
# ─────────────────────────────────────────────────────────

# ── PIN ASSIGNMENTS ──────────────────────────────────────
# Physical / manual override sensors (slide switches in Wokwi)
ir_sensor      = Pin(17, Pin.IN, Pin.PULL_DOWN)   # IR: object detected
metal_sensor   = Pin(27, Pin.IN, Pin.PULL_DOWN)   # Slide-switch → Metal
moisture_sensor= Pin(22, Pin.IN, Pin.PULL_DOWN)   # Slide-switch → Wet
plastic_sensor = Pin(26, Pin.IN, Pin.PULL_DOWN)   # Slide-switch → Plastic

# Servos at 50 Hz
servo_base    = PWM(Pin(18)); servo_base.freq(50)    # Arm rotation
servo_gripper = PWM(Pin(19)); servo_gripper.freq(50) # Gripper open/close

# ── SERVO UTILITIES ──────────────────────────────────────
def set_angle(servo, angle):
    """Map 0-180° to 16-bit duty (0.5ms–2.5ms pulse at 50 Hz)."""
    duty = int(1638 + (angle / 180.0) * (8192 - 1638))
    servo.duty_u16(duty)

def actuate_gripper(action):
    if action == "close":
        set_angle(servo_gripper, 0)      # Clamp shut
        print("  → Gripper: CLOSED")
    elif action == "open":
        set_angle(servo_gripper, 90)     # Release
        print("  → Gripper: OPEN")
    time.sleep(0.8)

# ── CATEGORY → BIN ANGLE MAP ─────────────────────────────
BIN_ANGLES = {
    "Metal":     15,
    "Wet Waste": 60,
    "Plastic":   105,
    "Dry Waste": 150,
}

# ── SORT SEQUENCE ─────────────────────────────────────────
def sort_waste(category):
    drop_angle = BIN_ANGLES.get(category, 150)   # Default → Dry Waste bin
    print(f"\n[WasteAI] Sorting: {category}  →  Bin @ {drop_angle}°")

    actuate_gripper("close")          # Pick item

    print(f"  → Rotating arm to {drop_angle}°")
    set_angle(servo_base, drop_angle)
    time.sleep(1.5)

    actuate_gripper("open")           # Drop item

    print("  → Returning to HOME (180°)")
    set_angle(servo_base, 180)
    time.sleep(1.5)
    print("  [Done] Ready for next item.\n")

# ── LOCAL SENSOR FALLBACK ─────────────────────────────────
def read_local_sensors():
    """Determine category from slide-switch states (manual override)."""
    if metal_sensor.value() == 1:
        return "Metal"
    if moisture_sensor.value() == 1:
        return "Wet Waste"
    if plastic_sensor.value() == 1:
        return "Plastic"
    return "Dry Waste"

# ── MQTT CALLBACK ─────────────────────────────────────────
def on_mqtt_message(topic, msg):
    """Called when WasteAI web app publishes a Gemini classification."""
    raw = msg.decode("utf-8").strip()
    print(f"[MQTT] Received on '{topic.decode()}': {raw}")

    # Accept plain text OR JSON {"category": "Plastic"}
    category = None
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            category = data.get("category", "").strip()
        except Exception:
            pass
    else:
        category = raw

    if category in BIN_ANGLES:
        sort_waste(category)
    else:
        print(f"  [WARN] Unknown category '{category}', defaulting to Dry Waste")
        sort_waste("Dry Waste")

# ── WIFI CONNECTION ───────────────────────────────────────
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return wlan
    print("[WiFi] Connecting to Wokwi-GUEST…")
    wlan.connect("Wokwi-GUEST", "")
    timeout = 15
    while not wlan.isconnected() and timeout > 0:
        time.sleep(0.5)
        timeout -= 1
    if wlan.isconnected():
        print(f"[WiFi] Connected! IP: {wlan.ifconfig()[0]}")
    else:
        print("[WiFi] WARNING: Could not connect. Running in LOCAL mode.")
    return wlan

# ── MQTT CONNECTION ───────────────────────────────────────
BROKER  = "broker.hivemq.com"
TOPIC   = b"wasteai/sorter/command"
CLIENT_ID = b"pico_wasteai_001"

def connect_mqtt():
    client = MQTTClient(CLIENT_ID, BROKER, keepalive=60)
    client.set_callback(on_mqtt_message)
    try:
        client.connect()
        client.subscribe(TOPIC)
        print(f"[MQTT] Connected to {BROKER}")
        print(f"[MQTT] Subscribed to: {TOPIC.decode()}")
        return client
    except Exception as e:
        print(f"[MQTT] Connection failed: {e}")
        return None

# ── MAIN ─────────────────────────────────────────────────
def main():
    # Initialise servos to home position
    set_angle(servo_gripper, 90)   # Gripper open
    set_angle(servo_base, 180)     # Arm at home
    time.sleep(1)

    print("=" * 50)
    print("  WasteAI — Smart Waste Segregation System")
    print("  Mode: MQTT (WiFi) + Local Sensor Fallback")
    print("=" * 50)

    wlan = connect_wifi()
    mqtt_client = None

    if wlan.isconnected():
        time.sleep(1)
        mqtt_client = connect_mqtt()

    if mqtt_client:
        print("\n[System] MQTT mode active.")
        print("  Waiting for Gemini classification commands…")
        print("  IR sensor also active for local override.\n")

        mqtt_reconnect_timer = 0
        while True:
            # ─ Check MQTT messages (non-blocking) ─
            try:
                mqtt_client.check_msg()
            except Exception as e:
                print(f"[MQTT] Lost connection: {e}. Reconnecting…")
                mqtt_client = None
                time.sleep(3)
                mqtt_client = connect_mqtt()

            # ─ Also respond to physical IR sensor (local trigger) ─
            if ir_sensor.value() == 1:
                print("\n[IR] Object detected on conveyor (local sensor).")
                category = read_local_sensors()
                sort_waste(category)
                time.sleep(1)

            time.sleep(0.1)

    else:
        # ─ Fallback: sensor-only mode ─────────────────────
        print("\n[System] LOCAL mode (no WiFi). Using sensors only.")
        print("  Activate IR sensor (btn) to trigger sorting.\n")

        while True:
            if ir_sensor.value() == 1:
                print("\n[IR] Object detected on conveyor.")
                time.sleep(0.3)
                category = read_local_sensors()
                sort_waste(category)
                time.sleep(1)
            time.sleep(0.05)

main()
