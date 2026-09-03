#pragma once

// Copy this file to secrets.h and enter the rover Wi-Fi credentials.
// secrets.h is ignored by Git and must never be committed.
constexpr char WIFI_SSID[] = "YOUR_WIFI_NAME";
constexpr char WIFI_PASSWORD[] = "YOUR_WIFI_PASSWORD";

// Fallback hotspot (AP mode) used when STA fails or no creds are set.

constexpr char AP_SSID[] = "PitDiver-Rover";
constexpr char AP_PASSWORD[] = "pitdiver123";   // >= 8 chars or ESP-IDF rejects it

