# Reverse Engineering the De'Longhi Coffee Link App

The De'Longhi Eletta Explore communicates via the **Ayla Networks IoT cloud platform**. To control the machine programmatically, you need three pieces of information that are embedded in the Coffee Link mobile app:

1. **`app_id`** — Ayla application identifier (a string like `DeLonghi-CoffeeLink-id` or a UUID)
2. **`app_secret`** — Paired secret for authentication
3. **Property names** — The actual Ayla property identifiers for power, brew commands, status readings, etc.

## Method A: MITM Proxy (Recommended)

Intercept the HTTPS traffic between the Coffee Link app and Ayla's servers.

### Tools

- **mitmproxy** (free, cross-platform): `uv pip install mitmproxy`
- Alternatives: [Proxyman](https://proxyman.io/) (macOS), [Charles Proxy](https://www.charlesproxy.com/)

### Setup

1. Install mitmproxy on your computer:
   ```bash
   uv pip install mitmproxy
   mitmweb
   ```
   This starts the proxy on port 8080 and opens a web UI at http://127.0.0.1:8081.

2. Find your computer's local IP address (e.g., `192.168.1.100`).

3. On your iPhone, go to **Settings > Wi-Fi > (your network) > Configure Proxy > Manual**:
   - Server: `192.168.1.100`
   - Port: `8080`

4. On your iPhone's Safari, visit **mitm.it** and download the iOS certificate.

5. Go to **Settings > General > VPN & Device Management** and install the downloaded profile.

6. Go to **Settings > General > About > Certificate Trust Settings** and enable full trust for the mitmproxy CA certificate.

### Capture Credentials

1. Open the De'Longhi Coffee Link app on your iPhone.
2. Log in (or the app will auto-login with stored credentials).
3. In the mitmproxy web UI, look for a POST request to:
   ```
   https://user-field-eu.aylanetworks.com/users/sign_in.json
   ```
   (or `user-field.aylanetworks.com` for non-EU accounts)

4. In the request body, you'll find:
   ```json
   {
     "user": {
       "email": "your-email",
       "password": "your-password",
       "application": {
         "app_id": "THIS IS WHAT YOU NEED",
         "app_secret": "AND THIS"
       }
     }
   }
   ```

5. Copy `app_id` and `app_secret` to your `.env` file.

### Discover Property Names

1. With the proxy still running, open the Coffee Link app and navigate to your machine.
2. Look for GET requests to:
   ```
   https://ads-eu.aylanetworks.com/apiv1/dsns/<YOUR_DSN>/properties.json
   ```
   This response contains ALL property names and their current values.

3. Trigger actions in the app (brew coffee, power on/off) and watch for POST requests to:
   ```
   https://ads-eu.aylanetworks.com/apiv1/dsns/<DSN>/properties/<PROPERTY_NAME>/datapoints.json
   ```
   The request body shows what value corresponds to each action.

4. Document the property names you discover and update `config/properties.toml` and `config/beverages.toml`.

### SSL Pinning Workaround

If the Coffee Link app refuses to connect through the proxy (certificate pinning), you'll need to bypass it:

**Android (easier):**
1. Install the Coffee Link APK on an Android device or emulator
2. Use [Frida](https://frida.re/) with objection:
   ```bash
   uv pip install frida-tools objection
   objection --gadget com.delonghi.coffeelink explore
   # Then in the objection shell:
   android sslpinning disable
   ```

**iOS (requires jailbreak):**
- Install [SSL Kill Switch 2](https://github.com/nabla-c0d3/ssl-kill-switch2) via Cydia
- Or use Frida: `frida -U -f com.delonghi.coffeelink -l ssl-bypass.js`

## Method B: Android APK Static Analysis

Extract credentials directly from the app binary without running it.

1. Download the Coffee Link APK from [APKMirror](https://www.apkmirror.com/) or extract from device:
   ```bash
   adb shell pm path com.delonghi.coffeelink
   adb pull /data/app/.../base.apk
   ```

2. Decompile with [jadx](https://github.com/skylot/jadx):
   ```bash
   jadx-gui base.apk
   ```

3. Search the decompiled source for:
   - `app_id` or `appId`
   - `app_secret` or `appSecret`
   - `aylanetworks.com`
   - `AylaNetworks`, `AylaDevice`, `AylaSetup`

4. Check `res/values/strings.xml` for hardcoded configuration values.

5. The Ayla SDK initialization code will typically contain the app_id and app_secret as constants or string resources.

## Method C: iOS IPA Analysis

1. Extract the IPA from a jailbroken device, or use [ipatool](https://github.com/majd/ipatool):
   ```bash
   ipatool download --bundle-identifier com.delonghi.coffeelink
   ```

2. Unzip the IPA and locate the main binary:
   ```bash
   unzip *.ipa -d extracted
   strings extracted/Payload/*.app/CoffeeLink | grep -i "app_id\|app_secret\|ayla"
   ```

3. For deeper analysis, use [Ghidra](https://ghidra-sre.org/) or Hopper Disassembler.

## What to Look For

| Item | Example Pattern | Where to Find |
|------|----------------|---------------|
| `app_id` | `DeLonghi-CoffeeLink-id` or UUID | Sign-in request body |
| `app_secret` | Long alphanumeric string | Sign-in request body |
| Property names | `SET_POWER`, `BREW_ESPRESSO`, etc. | `/properties.json` response |
| Brew commands | `{"datapoint": {"value": ...}}` | POST to `/datapoints.json` |
| Device DSN | Alphanumeric serial | `/devices.json` response |
| API region | `eu` vs `field` in URL | Any API request |

## Updating Configuration

After discovering the values:

1. **`.env`** — Set `DELONGHI_AYLA_APP_ID` and `DELONGHI_AYLA_APP_SECRET`

2. **`config/properties.toml`** — Replace placeholder names:
   ```toml
   [mappings]
   power = "ACTUAL_POWER_PROPERTY_NAME"
   machine_status = "ACTUAL_STATUS_NAME"
   ```

3. **`config/beverages.toml`** — Update each beverage:
   ```toml
   [beverages.espresso]
   display_name = "Espresso"
   property_name = "ACTUAL_BREW_ESPRESSO_NAME"
   confirmed = true
   [beverages.espresso.parameters]
   strength = 3
   temperature = 2
   size_ml = 40
   ```

## Contributing Discoveries

If you successfully extract property names, please share them (without your personal credentials) via GitHub issues. Property names are device-model-specific and not secret — sharing them helps other Eletta Explore owners.
