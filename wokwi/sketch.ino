#include <WiFi.h>
#include <HTTPClient.h>

// WiFi Configuration for Wokwi Simulation
const char* ssid = "Wokwi-GUEST";
const char* password = "";

// UPDATE THIS TO YOUR LAPTOP'S LOCAL IP ADDRESS
// e.g. "http://192.168.1.100:8000/checkin"
const char* serverUrl = "http://192.168.1.6:8000/checkin"; 

// Analog Pins for Mock Sensors
const int PIN_HR = 34;
const int PIN_SPO2 = 35;
const int PIN_ACCEL = 32;

unsigned long lastUpdate = 0;
const long updateInterval = 5000; // Checkin every 5 seconds for the POC

void setup() {
  Serial.begin(115200);
  
  // Connect to WiFi
  Serial.print("Connecting to WiFi");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nConnected!");
  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());
}

void loop() {
  unsigned long currentMillis = millis();

  if (currentMillis - lastUpdate >= updateInterval) {
    lastUpdate = currentMillis;

    // Read mocked values from potentiometers
    int hrRaw = analogRead(PIN_HR);
    int spo2Raw = analogRead(PIN_SPO2);
    int accelRaw = analogRead(PIN_ACCEL);

    // Map raw analog (0-4095) to realistic values
    int hr = map(hrRaw, 0, 4095, 60, 150); // 60-150 bpm
    int spo2 = map(spo2Raw, 0, 4095, 80, 100); // 80-100 %
    float accel = (float)map(accelRaw, 0, 4095, 5, 40) / 10.0; // 0.5 - 4.0 g

    // Mock arrays for the Random Forest pipeline (which expects signal windows)
    // We send a tiny window just so the backend parses it.
    String payload = "{";
    payload += "\"hr\": " + String(hr) + ", ";
    payload += "\"spo2\": " + String(spo2) + ", ";
    payload += "\"accel_magnitude\": " + String(accel) + ", ";
    payload += "\"acc_x\": [" + String(accel) + ", " + String(accel) + "], ";
    payload += "\"acc_y\": [0, 0], ";
    payload += "\"acc_z\": [0, 0], ";
    payload += "\"bvp\": [" + String(hr) + ", " + String(hr) + "], ";
    
    // Calculate a mock GSR value that slightly increases with HR
    float gsr = hr > 100 ? 0.8 : 0.5; 
    payload += "\"gsr\": [" + String(gsr) + ", " + String(gsr) + "]";
    payload += "}";

    Serial.println("Sending payload:");
    Serial.println(payload);

    if (WiFi.status() == WL_CONNECTED) {
      HTTPClient http;
      http.begin(serverUrl);
      // We must send it as form data since the backend expects physio_json=...
      http.addHeader("Content-Type", "application/x-www-form-urlencoded");
      
      String formData = "physio_json=" + payload;
      int httpResponseCode = http.POST(formData);

      if (httpResponseCode > 0) {
        Serial.print("HTTP Response code: ");
        Serial.println(httpResponseCode);
        String response = http.getString();
        Serial.println(response);
      } else {
        Serial.print("Error code: ");
        Serial.println(httpResponseCode);
      }
      http.end();
    } else {
      Serial.println("WiFi Disconnected");
    }
  }
}
