#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>

#define PIR_PIN     13
#define RELAY_PIN   26
#define BUZZER_PIN  27
#define LED_GREEN   32
#define LED_RED     33

const char* WIFI_SSID = "lediot";
const char* WIFI_PASSWORD = "goodluck";
const char* MDNS_HOST = "edge-face";

WebServer server(80);

bool pirPreviousState = false;
bool systemArmed = true;
unsigned long motionCount = 0;
unsigned long lastMotionAt = 0;
String lastEvent = "BOOT";
int nextEventId = 1;

struct EventEntry {
  int id;
  String name;
  String detail;
};

EventEntry eventBuffer[12];
int eventCount = 0;

void pushEvent(const String& name, const String& detail) {
  EventEntry event;
  event.id = nextEventId++;
  event.name = name;
  event.detail = detail;

  if (eventCount < 12) {
    eventBuffer[eventCount++] = event;
    return;
  }

  for (int i = 1; i < 12; i++) {
    eventBuffer[i - 1] = eventBuffer[i];
  }
  eventBuffer[11] = event;
}

void playTone(int frequency, int durationMs) {
  tone(BUZZER_PIN, frequency, durationMs);
  delay(durationMs + 40);
  noTone(BUZZER_PIN);
}

void beepSuccess() {
  playTone(1200, 150);
  playTone(1600, 150);
}

void beepAlert() {
  playTone(650, 1200);
}

void doUnlock() {
  digitalWrite(RELAY_PIN, HIGH);
  digitalWrite(LED_GREEN, HIGH);
  digitalWrite(LED_RED, LOW);
  beepSuccess();
  delay(3000);
  digitalWrite(RELAY_PIN, LOW);
  digitalWrite(LED_GREEN, LOW);
  lastEvent = "UNLOCKED";
  pushEvent("UNLOCKED", "relay pulse complete");
}

void doAlert() {
  digitalWrite(LED_RED, HIGH);
  digitalWrite(LED_GREEN, LOW);
  beepAlert();
  delay(2000);
  digitalWrite(LED_RED, LOW);
  lastEvent = "ALERTED";
  pushEvent("ALERTED", "buzzer pattern complete");
}

void testGreenLed() {
  digitalWrite(LED_RED, LOW);
  digitalWrite(LED_GREEN, HIGH);
  delay(1000);
  digitalWrite(LED_GREEN, LOW);
  lastEvent = "GREEN_LED_TEST";
  pushEvent("GREEN_LED_TEST", "green led pulse complete");
}

void testRedLed() {
  digitalWrite(LED_GREEN, LOW);
  digitalWrite(LED_RED, HIGH);
  delay(1000);
  digitalWrite(LED_RED, LOW);
  lastEvent = "RED_LED_TEST";
  pushEvent("RED_LED_TEST", "red led pulse complete");
}

String escapeJson(const String& value) {
  String out = value;
  out.replace("\\", "\\\\");
  out.replace("\"", "\\\"");
  return out;
}

void sendJson(const String& body) {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", body);
}

void handleRoot() {
  sendJson("{\"device\":\"esp32-face-bridge\",\"ok\":true}");
}

void handleStatus() {
  String ip = WiFi.localIP().toString();
  bool pirState = digitalRead(PIR_PIN) == HIGH;
  String body = "{";
  body += "\"device\":\"esp32-face-bridge\",";
  body += "\"ok\":true,";
  body += "\"armed\":" + String(systemArmed ? "true" : "false") + ",";
  body += "\"pirState\":" + String(pirState ? "true" : "false") + ",";
  body += "\"motionCount\":" + String(motionCount) + ",";
  body += "\"lastMotionAt\":" + String(lastMotionAt) + ",";
  body += "\"lastEvent\":\"" + escapeJson(lastEvent) + "\",";
  body += "\"ip\":\"" + ip + "\",";
  body += "\"mdns\":\"" + String(MDNS_HOST) + ".local\"";
  body += "}";
  sendJson(body);
}

void handleEvents() {
  int since = server.hasArg("since") ? server.arg("since").toInt() : 0;

  String body = "{\"device\":\"esp32-face-bridge\",\"events\":[";
  bool first = true;
  for (int i = 0; i < eventCount; i++) {
    if (eventBuffer[i].id <= since) {
      continue;
    }
    if (!first) {
      body += ",";
    }
    first = false;
    body += "{";
    body += "\"id\":" + String(eventBuffer[i].id) + ",";
    body += "\"name\":\"" + escapeJson(eventBuffer[i].name) + "\",";
    body += "\"detail\":\"" + escapeJson(eventBuffer[i].detail) + "\"";
    body += "}";
  }
  body += "]}";
  sendJson(body);
}

void handleControl() {
  if (!server.hasArg("plain")) {
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"missing json body\"}");
    return;
  }

  String body = server.arg("plain");
  body.trim();
  body.toUpperCase();

  String response = "{\"ok\":true";
  bool pirState = digitalRead(PIR_PIN) == HIGH;

  if (body.indexOf("UNLOCK") >= 0) {
    doUnlock();
    response += ",\"command\":\"UNLOCK\"";
  } else if (body.indexOf("ALERT") >= 0) {
    doAlert();
    response += ",\"command\":\"ALERT\"";
  } else if (body.indexOf("ARM") >= 0 && body.indexOf("DISARM") < 0) {
    systemArmed = true;
    lastEvent = "ARMED";
    pushEvent("ARMED", "system armed");
    response += ",\"command\":\"ARM\"";
  } else if (body.indexOf("DISARM") >= 0) {
    systemArmed = false;
    lastEvent = "DISARMED";
    pushEvent("DISARMED", "system disarmed");
    response += ",\"command\":\"DISARM\"";
  } else if (body.indexOf("PING") >= 0) {
    lastEvent = "PONG";
    pushEvent("PONG", "ping response");
    response += ",\"command\":\"PING\"";
  } else if (body.indexOf("TEST_RELAY") >= 0) {
    doUnlock();
    response += ",\"command\":\"TEST_RELAY\"";
  } else if (body.indexOf("TEST_BUZZER") >= 0) {
    doAlert();
    response += ",\"command\":\"TEST_BUZZER\"";
  } else if (body.indexOf("TEST_GREEN") >= 0) {
    testGreenLed();
    response += ",\"command\":\"TEST_GREEN\"";
  } else if (body.indexOf("TEST_RED") >= 0) {
    testRedLed();
    response += ",\"command\":\"TEST_RED\"";
  } else if (body.indexOf("TEST_PIR") >= 0) {
    lastEvent = "PIR_TEST";
    pushEvent("PIR_TEST", pirState ? "pir high" : "pir low");
    response += ",\"command\":\"TEST_PIR\"";
    response += ",\"pirState\":" + String(pirState ? "true" : "false");
  } else {
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"unsupported command\"}");
    return;
  }

  response += "}";
  sendJson(response);
}

void handleOptions() {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Access-Control-Allow-Headers", "Content-Type");
  server.sendHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  server.send(204);
}

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
  }
}

void handlePIR() {
  if (!systemArmed) {
    return;
  }

  bool pirCurrentState = digitalRead(PIR_PIN);
  if (pirCurrentState == HIGH && pirPreviousState == LOW) {
    motionCount++;
    lastMotionAt = millis();
    lastEvent = "MOTION_DETECTED";
    pushEvent("MOTION_DETECTED", "pir rising edge");
  }
  pirPreviousState = pirCurrentState;
}

void setup() {
  Serial.begin(115200);

  pinMode(PIR_PIN, INPUT);
  pinMode(RELAY_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_RED, OUTPUT);

  digitalWrite(RELAY_PIN, LOW);
  digitalWrite(BUZZER_PIN, LOW);
  digitalWrite(LED_GREEN, LOW);
  digitalWrite(LED_RED, LOW);

  for (int i = 0; i < 3; i++) {
    digitalWrite(LED_GREEN, HIGH);
    digitalWrite(LED_RED, HIGH);
    delay(200);
    digitalWrite(LED_GREEN, LOW);
    digitalWrite(LED_RED, LOW);
    delay(200);
  }

  connectWifi();
  if (MDNS.begin(MDNS_HOST)) {
    MDNS.addService("edgeface", "tcp", 80);
  }

  pushEvent("BOOT", "esp32 ready");

  server.on("/", HTTP_GET, handleRoot);
  server.on("/api/status", HTTP_GET, handleStatus);
  server.on("/api/events", HTTP_GET, handleEvents);
  server.on("/api/control", HTTP_POST, handleControl);
  server.on("/api/control", HTTP_OPTIONS, handleOptions);
  server.begin();

  Serial.println("ESP32 READY");
  Serial.println(WiFi.localIP());
}

void loop() {
  server.handleClient();
  handlePIR();
  delay(50);
}
