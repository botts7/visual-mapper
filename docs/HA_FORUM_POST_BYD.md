# Visual Mapper - App-Based Solution for BYD SOC

Hey everyone! I've been following this thread and wanted to share a tool I built that takes the "app scraping" approach mentioned earlier to a complete solution.

**Visual Mapper** is an open-source Home Assistant add-on that connects to an Android device via ADB, navigates through the BYD app, captures UI values, and publishes them as HA sensors via MQTT.

## How It Compares to Other Approaches

| Approach | Pros | Cons |
|----------|------|------|
| **OBD-II (WiCAN/OVMS)** | Direct car data, works offline | Hardware cost, installation, some PIDs give wrong values |
| **Third-party (enode.io)** | Easy setup | Cloud dependency, subscription, privacy |
| **BYD API (oip.byd.com)** | Official data | Complex auth, limited documentation |
| **Visual Mapper (this)** | Free, works with any app data, no hardware | Needs spare Android device, slower updates |

## What You Can Capture

Anything visible in the BYD app:
- Battery SOC (%)
- Estimated range
- Charging status & power
- Door lock status
- Climate/preconditioning
- Odometer, trip data, etc.

Works with **Atto 3, Sealion 7, Dolphin** - any BYD model with the app.

## How It Works

1. Install the HA add-on
2. Connect a spare Android device (old phone/tablet) via WiFi ADB
3. Use the visual Flow Wizard to record: Open BYD app → Navigate to battery screen → Select the SOC element
4. Schedule to run every 10-15 minutes
5. Sensors appear in HA via MQTT auto-discovery

It handles pull-to-refresh, app re-login, and navigation automatically.

## Quick Demo

**Flow Wizard recording navigation:**
![image|690x358](upload://A8NXKeKfFImnvuaND0XEBmAcPj5.jpeg)

**Selecting an element to capture as sensor:**
![image|398x500](upload://3nfRApAOovevl5GefdEoZP6r9wd.png)

## Installation

Add to your HA add-on store:
```
https://github.com/botts7/visual-mapper-addon
```

## Requirements

- Spare Android device with BYD app
- WiFi ADB (Android 11+) or USB
- Mosquitto MQTT broker

## Limitations

- Updates every 10-15 min (not real-time like OBD)
- Needs the Android device to stay powered/connected
- Won't work while you're actively using the BYD app on that device

## Links

| Resource | Link |
|----------|------|
| Full Announcement | https://community.home-assistant.io/t/visual-mapper-control-android-devices-create-sensors-from-any-app-ui/974332 |
| Add-on Repo | https://github.com/botts7/visual-mapper-addon |
| GitHub Issues | https://github.com/botts7/visual-mapper/issues |

---

Happy to help anyone get this set up for their BYD. It's been working well for my Sealion 7 - captures SOC, range, and charging status every 10 minutes.

**Current version: v0.3.1**
