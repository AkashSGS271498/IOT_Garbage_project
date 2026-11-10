import network
import time
import json
import random
import struct
import usocket as socket
from machine import Pin, PWM

# ---------------------------------------------------------------------------
# Inline umqtt.simple — faithful copy from micropython-lib
# (avoids the hanging mip.install in Wokwi)
# ---------------------------------------------------------------------------
class MQTTClient:
    def __init__(self, client_id, server, port=0, user=None, password=None,
                 keepalive=0, ssl=False, ssl_params={}):
        if isinstance(client_id, str):
            client_id = client_id.encode()
        self.client_id = client_id
        self.sock = None
        self.server = server
        self.port = port or (8883 if ssl else 1883)
        self.ssl = ssl
        self.ssl_params = ssl_params
        self.pid = 0
        self.cb = None
        self.user = user
        self.pswd = password
        self.keepalive = keepalive
        self.lw_topic = None
        self.lw_msg = None
        self.lw_qos = 0
        self.lw_retain = False

    def _send_str(self, s):
        if isinstance(s, str):
            s = s.encode()
        self.sock.write(struct.pack("!H", len(s)))
        self.sock.write(s)

    def _recv_len(self):
        n = 0
        sh = 0
        while 1:
            b = self.sock.read(1)[0]
            n |= (b & 0x7F) << sh
            if not b & 0x80:
                return n
            sh += 7

    def set_callback(self, f):
        self.cb = f

    def set_last_will(self, topic, msg, retain=False, qos=0):
        if isinstance(topic, str):
            topic = topic.encode()
        if isinstance(msg, str):
            msg = msg.encode()
        self.lw_topic = topic
        self.lw_msg = msg
        self.lw_qos = qos
        self.lw_retain = retain

    def connect(self, clean_session=True):
        self.sock = socket.socket()
        addr = socket.getaddrinfo(self.server, self.port)[0][-1]
        self.sock.connect(addr)
        if self.ssl:
            import ussl
            self.sock = ussl.wrap_socket(self.sock, **self.ssl_params)
        # Build variable header + payload
        plen = 10 + 2 + len(self.client_id)
        flags = (clean_session << 1)
        if self.user:
            flags |= 0xC0
            plen += 2 + len(self.user) + 2 + len(self.pswd or b"")
        if self.lw_topic:
            flags |= 0x04 | (self.lw_qos << 3) | (self.lw_retain << 5)
            plen += 2 + len(self.lw_topic) + 2 + len(self.lw_msg)
        # Fixed header
        hdr = bytearray()
        hdr.append(0x10)
        rlen = plen
        while rlen > 0x7F:
            hdr.append((rlen & 0x7F) | 0x80)
            rlen >>= 7
        hdr.append(rlen)
        self.sock.write(hdr)
        # Variable header
        self.sock.write(b"\x00\x04MQTT\x04")
        self.sock.write(bytes([flags]))
        self.sock.write(struct.pack("!H", self.keepalive))
        # Payload
        self._send_str(self.client_id)
        if self.lw_topic:
            self._send_str(self.lw_topic)
            self._send_str(self.lw_msg)
        if self.user:
            self._send_str(self.user)
            self._send_str(self.pswd or b"")
        # Read CONNACK — blocking
        self.sock.setblocking(True)
        resp = self.sock.read(4)
        if resp is None or len(resp) < 4:
            raise OSError("CONNACK not received")
        if resp[0] != 0x20 or resp[1] != 0x02:
            raise OSError("Invalid CONNACK")
        if resp[3] != 0:
            raise OSError("CONNACK error: %d" % resp[3])
        return resp[2] & 1

    def disconnect(self):
        self.sock.write(b"\xe0\0")
        self.sock.close()

    def ping(self):
        self.sock.write(b"\xc0\0")

    def publish(self, topic, msg, retain=False, qos=0):
        if isinstance(topic, str):
            topic = topic.encode()
        if isinstance(msg, str):
            msg = msg.encode()
        pkt_type = 0x30 | (qos << 1) | retain
        rlen = 2 + len(topic) + len(msg)
        if qos > 0:
            rlen += 2
        # Encode remaining length + send
        hdr = bytearray()
        hdr.append(pkt_type)
        rl = rlen
        while rl > 0x7F:
            hdr.append((rl & 0x7F) | 0x80)
            rl >>= 7
        hdr.append(rl)
        self.sock.write(hdr)
        self._send_str(topic)
        if qos > 0:
            self.pid += 1
            self.sock.write(struct.pack("!H", self.pid))
        self.sock.write(msg)
        if qos == 1:
            self.sock.setblocking(True)
            while 1:
                op = self._wait_msg()
                if op == 0x40:
                    sz = self.sock.read(1)
                    if sz != b"\x02":
                        raise OSError("PUBACK bad")
                    rcv_pid = self.sock.read(2)
                    if rcv_pid[0] << 8 | rcv_pid[1] == self.pid:
                        return

    def subscribe(self, topic, qos=0):
        if isinstance(topic, str):
            topic = topic.encode()
        self.pid += 1
        rlen = 2 + 2 + len(topic) + 1
        hdr = struct.pack("!BBH", 0x82, rlen, self.pid)
        self.sock.write(hdr)
        self._send_str(topic)
        self.sock.write(bytes([qos]))
        self.sock.setblocking(True)
        while 1:
            op = self._wait_msg()
            if op == 0x90:
                resp = self.sock.read(4)
                if resp[3] == 0x80:
                    raise OSError("SUBACK failure")
                return

    def _wait_msg(self):
        res = self.sock.read(1)
        self.sock.setblocking(True)
        if res is None:
            return None
        if res == b"":
            raise OSError(-1)
        if res == b"\xd0":  # PINGRESP
            self.sock.read(1)
            return None
        op = res[0]
        if op & 0xF0 != 0x30:
            return op
        sz = self._recv_len()
        topic_len = self.sock.read(2)
        topic_len = (topic_len[0] << 8) | topic_len[1]
        topic = self.sock.read(topic_len)
        sz -= topic_len + 2
        if op & 6:
            pid = self.sock.read(2)
            pid = pid[0] << 8 | pid[1]
            sz -= 2
        msg = self.sock.read(sz)
        self.cb(topic, msg)
        if op & 6 == 2:
            pkt = struct.pack("!BBH", 0x40, 2, pid)
            self.sock.write(pkt)
        elif op & 6 == 4:
            raise OSError("QoS 2 not supported")
        return op

    def check_msg(self):
        self.sock.setblocking(False)
        return self._wait_msg()

# ---------------------------------------------------------------------------
# WasteAI — CONFIG
# ---------------------------------------------------------------------------
BROKER        = "broker.hivemq.com"
CMD_TOPIC     = b"skit/akash_project/command"
ACK_TOPIC     = b"skit/akash_project/ack"
STATUS_TOPIC  = b"skit/akash_project/status"
KEEPALIVE     = 30
PING_EVERY_MS = 10000

# --- PINS ---
ir_sensor       = Pin(17, Pin.IN, Pin.PULL_DOWN)
metal_sensor    = Pin(27, Pin.IN, Pin.PULL_DOWN)
moisture_sensor = Pin(22, Pin.IN, Pin.PULL_DOWN)
plastic_sensor  = Pin(26, Pin.IN, Pin.PULL_DOWN)

# --- SERVOS ---
servo_base    = PWM(Pin(18)); servo_base.freq(50)
servo_gripper = PWM(Pin(19)); servo_gripper.freq(50)

def set_angle(servo, angle):
    servo.duty_u16(int(1638 + (angle / 180.0) * (8192 - 1638)))

def actuate_gripper(action):
    set_angle(servo_gripper, 0 if action == "close" else 90)
    print(" -> Gripper:", action.upper())
    time.sleep(0.8)

BIN_ANGLES = {"Metal": 15, "Wet Waste": 60, "Plastic": 105, "Dry Waste": 150}

def normalize(text):
    t = str(text).strip().strip(".\"'").lower()
    for k in BIN_ANGLES:
        if k.lower() == t:
            return k
    return None

def sort_waste(category):
    angle = BIN_ANGLES[category]
    print("\n[WasteAI] Sorting:", category, "-> bin @", angle)
    actuate_gripper("close")
    set_angle(servo_base, angle); time.sleep(1.5)
    actuate_gripper("open")
    set_angle(servo_base, 180);  time.sleep(1.5)
    print(" [Done] Ready for next item.\n")

def read_local_sensors():
    if metal_sensor.value():    return "Metal"
    if moisture_sensor.value(): return "Wet Waste"
    if plastic_sensor.value():  return "Plastic"
    return "Dry Waste"

# --- WIFI ---
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("[WiFi] Connecting to Wokwi-GUEST...")
        wlan.connect("Wokwi-GUEST", "")
        for _ in range(40):
            if wlan.isconnected():
                break
            time.sleep(0.5)
    if wlan.isconnected():
        print("[WiFi] Connected, IP:", wlan.ifconfig()[0])
    else:
        print("[WiFi] WARNING: Could not connect!")
    return wlan

# --- MQTT ---
pending  = []
seen_ids = []

def on_mqtt_message(topic, msg):
    raw = msg.decode("utf-8").strip()
    print("[MQTT RX]", raw)
    cmd_id, category = None, raw
    if raw.startswith("{"):
        try:
            d = json.loads(raw)
            category = d.get("category", "")
            cmd_id   = d.get("id")
        except Exception:
            pass
    pending.append((cmd_id, category))

def publish_ack(client, cmd_id, state, category=""):
    try:
        client.publish(ACK_TOPIC,
                       json.dumps({"id": cmd_id, "state": state, "category": category}),
                       qos=0)
    except Exception as e:
        print("[ACK] publish failed:", e)

def mqtt_connect():
    cid = "pico_akash_%06x" % random.getrandbits(24)
    print("[MQTT] Connecting as", cid, "...")
    c = MQTTClient(cid, BROKER, keepalive=KEEPALIVE)
    c.set_callback(on_mqtt_message)
    c.set_last_will(STATUS_TOPIC, b"offline", retain=True)
    c.connect()
    c.subscribe(CMD_TOPIC, 1)
    c.publish(STATUS_TOPIC, b"online", retain=True)
    print("[MQTT] Connected and subscribed to", CMD_TOPIC.decode())
    return c

def handle_pending(client):
    while pending:
        cmd_id, raw_cat = pending.pop(0)
        if cmd_id is not None and cmd_id in seen_ids:
            print("[MQTT] Duplicate", cmd_id, "- re-acking only")
            publish_ack(client, cmd_id, "done")
            continue
        cat = normalize(raw_cat)
        if cat is None:
            print("[WARN] Unknown category:", raw_cat)
            publish_ack(client, cmd_id, "error", str(raw_cat))
            continue
        if cmd_id is not None:
            seen_ids.append(cmd_id)
            if len(seen_ids) > 20:
                seen_ids.pop(0)
        publish_ack(client, cmd_id, "received", cat)
        sort_waste(cat)
        publish_ack(client, cmd_id, "done", cat)

# --- MAIN ---
set_angle(servo_gripper, 90)
set_angle(servo_base, 180)
time.sleep(0.5)
print("\n--- WasteAI System Starting ---")

wlan      = connect_wifi()
client    = None
last_ping = time.ticks_ms()

while True:
    try:
        if not wlan.isconnected():
            wlan = connect_wifi()
        if client is None:
            client    = mqtt_connect()
            last_ping = time.ticks_ms()

        client.check_msg()

        if time.ticks_diff(time.ticks_ms(), last_ping) > PING_EVERY_MS:
            client.ping()
            last_ping = time.ticks_ms()

        handle_pending(client)

        if ir_sensor.value() == 1:
            print("[IR] Local object detected")
            sort_waste(read_local_sensors())
            time.sleep(1)

        time.sleep(0.05)

    except Exception as e:
        print("[ERROR]", repr(e), "- reconnecting in 2s")
        try:
            client.disconnect()
        except Exception:
            pass
        client = None
        time.sleep(2)
