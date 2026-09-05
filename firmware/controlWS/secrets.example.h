#pragma once

// controlWS access-point credentials.
//
// This file is OPTIONAL. If you do not create secrets.h, the rover comes up as
// an OPEN access point named "RoverPit" (see the defaults in controlWS.ino) —
// which is all you need for a quick bench test.
//
// To lock the AP down: copy this file to secrets.h and edit the values below.
// secrets.h is ignored by Git (see the repo .gitignore) and must never be
// committed. Both values must be string-literal #defines.
//
//   * AP_SSID : the network name the phone connects to.
//   * AP_PASS : WPA2 password (>= 8 chars), or "" for an open AP.

#define AP_SSID "RoverPit"
#define AP_PASS ""          // "" = open AP; set an 8+ char password to secure it
