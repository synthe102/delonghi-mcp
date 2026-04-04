# De'Longhi Eletta Explore Binary Protocol

Reverse-engineered protocol documentation for the De'Longhi Eletta Explore (ECAM450.55.G, OEM model `DL-striker-cb`) coffee machine.

The machine communicates via WiFi through the **Ayla Networks IoT cloud platform**. All commands and responses are **base64-encoded binary packets** sent through Ayla device properties.

## Architecture Overview

```
Coffee Link App  ─── HTTPS ──→  Ayla Networks Cloud  ←── WiFi ───  Coffee Machine
                                  (ads-eu.aylanetworks.com)
MCP Server       ─── HTTPS ──→
```

The mobile app (and our MCP server) never talks to the machine directly. All communication is proxied through Ayla's REST API:

1. **App → Cloud**: POST base64-encoded binary command to the `app_data_request` property
2. **Cloud → Machine**: Ayla pushes the datapoint to the machine over WiFi
3. **Machine → Cloud**: Machine writes status/responses to output properties
4. **Cloud → App**: App polls or subscribes to property changes

## Authentication

### Gigya SSO Token Flow

The Coffee Link app uses **SAP Gigya** as its identity provider. Authentication is a two-step process:

1. User logs into De'Longhi's Gigya-based auth system (handled by the app)
2. App exchanges the Gigya JWT for an Ayla access token via `token_sign_in`

**Endpoint**: `POST https://user-field-eu.aylanetworks.com/api/v1/token_sign_in`

**Request body**:
```json
{
    "app_id": "DLonghiCoffeeIdKit-sQ-id",
    "app_secret": "DLonghiCoffeeIdKit-HT6b0VNd4y6CSha9ivM5k8navLw",
    "token": "<Gigya JWT>"
}
```

**Response**:
```json
{
    "access_token": "37f1d4c2985e41d28f868d189c58fe62",
    "refresh_token": "ee4ed9980e0f453c914f82813a798de4",
    "expires_in": 86400,
    "role": "EndUser",
    "code": "ok"
}
```

The `access_token` is used in all subsequent API calls as:
```
Authorization: auth_token <access_token>
```

### Gigya JWT Structure

The JWT issued by Gigya has this payload:
```json
{
    "iss": "https://fidm.gigya.com/jwt/3_e5qn7USZK-QtsIso1wCelqUKAK_IVEsYshRIssQ-X-k55haiZXmKWDHDRul2e5Y2/",
    "apiKey": "3_e5qn7USZK-QtsIso1wCelqUKAK_IVEsYshRIssQ-X-k55haiZXmKWDHDRul2e5Y2",
    "iat": 1775314015,
    "exp": 1783090015,
    "sub": "<user_id>"
}
```

The token has a very long expiry (~90 days). The Gigya API key `3_e5qn7USZK-QtsIso1wCelqUKAK_IVEsYshRIssQ-X-k55haiZXmKWDHDRul2e5Y2` is De'Longhi's Gigya application identifier.

### Token Refresh

```
POST https://user-field-eu.aylanetworks.com/users/refresh_token.json

{"user": {"refresh_token": "<refresh_token>"}}
```

## Ayla API Endpoints

All device operations use the Ayla Device Service (ADS) API at `https://ads-eu.aylanetworks.com`.

### List Devices

```
GET /apiv1/devices.json
```

Response includes `dsn` (device serial number), `connection_status`, `lan_ip`, `oem_model`, etc.

### Read All Properties

```
GET /apiv1/dsns/{dsn}/properties.json
```

### Read Single Property

```
GET /apiv1/dsns/{dsn}/properties/{property_name}.json
```

### Write Property (Send Command)

```
POST /apiv1/dsns/{dsn}/properties/{property_name}/datapoints.json

{"datapoint": {"value": "<base64_encoded_command>"}}
```

## Connection Flow

Before sending brew or other operational commands, the app must establish a connection with the machine. Without this handshake, the machine acknowledges commands but does not execute them.

### Required Sequence

```
1. POST app_device_connected  →  [timestamp][device_suffix]     (handshake)
2. POST app_data_request      →  [0xE8F0 init command]          (initialization)
3. POST app_data_request      →  [0x83F0 brew command]          (brew)
```

### Step 1: Connection Handshake

Write a timestamp + device suffix to `app_device_connected`:

```
POST /apiv1/dsns/{dsn}/properties/app_device_connected/datapoints.json

Value (base64 of): [4 bytes: unix timestamp BE] [4 bytes: device suffix BE]
```

### Step 2: Initialization Command (`0xE8F0`)

Send an init packet via `app_data_request`. The captured payload is `E8 F0 00 ED 7C`:

```
POST /apiv1/dsns/{dsn}/properties/app_data_request/datapoints.json

Packet: [0D] [08] [E8 F0 00 ED 7C] [CRC16] [timestamp] [suffix]
```

The meaning of bytes `00 ED 7C` is unknown, but this exact sequence was captured from the Coffee Link app and is required for the machine to accept subsequent commands.

### Step 3: Send Command

Now brew commands (and likely other operational commands) will be executed by the machine.

## Packet Format

All binary data exchanged with the machine follows this packet structure:

```
┌──────────┬────────┬─────────────────────┬─────────┬───────────────┬──────────────┐
│ Start    │ Length │ Payload             │ CRC-16  │ Timestamp     │ Device       │
│ (1 byte) │(1 byte)│ (variable)          │ (2 bytes)│ (4 bytes)     │ Suffix       │
│ 0x0D     │ N      │ command + params    │         │ Unix BE       │ (4 bytes)    │
└──────────┴────────┴─────────────────────┴─────────┴───────────────┴──────────────┘
```

### Fields

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 1 | Start marker | Always `0x0D` |
| 1 | 1 | Length (N) | Total bytes from [2] through end of CRC. Equals `len(payload) + 3` |
| 2 | variable | Payload | Command type + parameters |
| N-1 | 2 | CRC-16 | CRC-16/CCITT over bytes [0] through [N-2] |
| N+1 | 4 | Timestamp | Unix timestamp, big-endian uint32 |
| N+5 | 4 | Device suffix | Constant per-device identifier, big-endian uint32 |

### Length Byte Calculation

```
N = len(payload) + 3
```

The `+3` accounts for: the length byte itself (1) + the CRC (2).

Total protocol part (before trailer) = `N + 1` bytes (including the `0x0D` start marker).

### CRC-16/CCITT

- **Algorithm**: CRC-16/CCITT (XModem variant)
- **Polynomial**: 0x1021
- **Initial value**: 0x1D0F
- **Input**: bytes [0] through [N-2] (start marker + length byte + payload)
- **Output**: 2 bytes, big-endian

```python
def crc16_ccitt(data: bytes, init: int = 0x1D0F) -> int:
    crc = init
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return crc
```

### Device Suffix

A constant 4-byte value unique to each machine. Extracted from the `app_device_connected` property, which has the format:

```
[4 bytes: timestamp BE] [4 bytes: device suffix BE]
```

For the tested machine: `00 19 A7 A9`.

### Timestamp

Standard Unix timestamp as a big-endian uint32. Represents when the command was issued.

## Command Types

The first two bytes of the payload identify the command type.

| Type | Description |
|------|-------------|
| `0x83 0xF0` | Brew command (execute a recipe) |
| `0xA6 0xF0` | Recipe data (stored profile recipe) |
| `0xE8 0xF0` | Unknown (seen in initial `app_data_request` value) |

## Brew Command (`0x83F0`)

Triggers the machine to prepare a beverage using the specified recipe's current profile settings.

### Packet Structure

```
┌────────┬─────────────┬───────────┬──────┬───────────────┐
│ 83 F0  │ Recipe ID   │ 03        │ Recipe Parameters   │
│ (2B)   │ (1 byte)    │ (1 byte)  │ (variable)          │
└────────┴─────────────┴───────────┴─────────────────────┘
```

### Fields

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0-1 | 2 | Command type | `0x83 0xF0` |
| 2 | 1 | Recipe ID | Beverage identifier (see table below) |
| 3 | 1 | Subcommand | `0x03` for brew execution |
| 4+ | variable | Recipe params | Beverage-specific parameters from stored recipe |

### Example: Espresso Brew

Captured packet (base64): `DROD8AEDAQAoAgQIABsBJwEGNT9p0SlgABmnqQ==`

```
Hex breakdown:
0D              Start marker
13              Length (19)
83 F0           Command: Brew
01              Recipe ID: Espresso
03              Subcommand: Execute
01 00 28 02 04  Recipe parameters (size=40ml, etc.)
08 00 1B 01     Recipe parameters continued
27 01 06        Recipe parameters continued
35 3F           CRC-16
69 D1 29 60     Timestamp (2026-04-04 15:08:16 UTC)
00 19 A7 A9     Device suffix
```

### Example: Regular Coffee Brew

Captured packet (base64): `DRGD8AIDAQC0AgIbAScBBhKpadEpyAAZp6k=`

```
Hex breakdown:
0D              Start marker
11              Length (17)
83 F0           Command: Brew
02              Recipe ID: Regular Coffee
03              Subcommand: Execute
01 00 B4 02 02  Recipe parameters (size=180ml, etc.)
1B 01 27 01 06  Recipe parameters continued
12 A9           CRC-16
69 D1 29 C8     Timestamp (2026-04-04 15:10:00 UTC)
00 19 A7 A9     Device suffix
```

## Recipe IDs

| ID (hex) | ID (dec) | Beverage | Property (Profile 1) |
|----------|----------|----------|----------------------|
| 0x01 | 1 | Espresso | d059_rec_1_espresso |
| 0x02 | 2 | Regular Coffee | d060_rec_1_regular |
| 0x03 | 3 | Long Coffee | d061_rec_1_long_coffee |
| 0x04 | 4 | 2x Espresso | d062_rec_1_2x_espresso |
| 0x05 | 5 | Doppio+ | d063_rec_1_doppio_pl |
| 0x06 | 6 | Americano | d064_rec_1_americano |
| 0x07 | 7 | Cappuccino | d065_rec_1_cappuccino |
| 0x08 | 8 | Latte Macchiato | d066_rec_1_latte_macch |
| 0x09 | 9 | Caffe Latte | d067_rec_1_caffelatte |
| 0x0A | 10 | Flat White | d068_rec_1_flat_white |
| 0x0B | 11 | Espresso Macchiato | d069_rec_1_espr_macch |
| 0x0C | 12 | Hot Milk | d070_rec_1_hot_milk |
| 0x0D | 13 | Cappuccino Doppio+ | d071_rec_1_capp_doppio_pl |
| 0x0F | 15 | Cappuccino Reverse | d072_rec_1_capp_reverse |
| 0x10 | 16 | Hot Water | d073_rec_1_hot_water |
| 0x16 | 22 | Tea | d074_rec_1_tea |
| 0x17 | 23 | Coffee Pot | d075_rec_1_coffee_pot |
| 0x18 | 24 | Cortado | d076_rec_1_cortado |
| 0x1B | 27 | Brew Over Ice | d078_rec_1_brew_over_ice |
| 0x32 | 50 | Iced Americano | (stored in d002/d003 defaults) |
| 0x33 | 51 | Iced Cappuccino | (stored in d002/d003 defaults) |
| 0x34 | 52 | Iced Latte Macchiato | (stored in d002/d003 defaults) |
| 0x35 | 53 | Iced Cappuccino Mix | (stored in d002/d003 defaults) |
| 0x36 | 54 | Iced Flat White | (stored in d002/d003 defaults) |
| 0x37 | 55 | Iced Cold Milk | (stored in d002/d003 defaults) |
| 0x38 | 56 | Iced Caffe Latte | (stored in d002/d003 defaults) |
| 0x39 | 57 | Over Ice Espresso | (stored in d002/d003 defaults) |

## Stored Recipe Format (`0xA6F0`)

The machine stores recipes in Ayla properties. Each recipe contains the user's customized parameters (size, strength, temperature, etc.) for a specific beverage and profile.

### Property Naming

Recipes are stored across multiple property groups:

- **Default recipes** (`d002_rec_default_1` through `d008_rec_default_7`): JSON objects mapping recipe keys to base64 blobs. These contain the factory-default recipe definitions with full parameter ranges.
- **Per-profile recipes** (`d059_rec_1_*` through `d231_rec_4_*`): Individual properties for each beverage per user profile (profiles 1-4). These contain the user's actual customized settings.
- **Custom recipes** (`d240_rec_custom_1` through `d245_rec_custom_6`): User-created custom beverages.

### Per-Profile Recipe Packet

```
┌──────────┬────────┬─────────────┬────────────┬───────────┬────────────────────┬─────────┐
│ Start    │ Length │ Type        │ Profile ID │ Recipe ID │ Recipe Parameters  │ CRC-16  │
│ 0xD0     │ N      │ A6 F0       │ (1 byte)   │ (1 byte)  │ (variable)         │ (2B)    │
└──────────┴────────┴─────────────┴────────────┴───────────┴────────────────────┴─────────┘
```

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 1 | Start marker | `0xD0` (different from command packets which use `0x0D`) |
| 1 | 1 | Length | Total bytes including this byte through end (= total - 1) |
| 2-3 | 2 | Type | `0xA6 0xF0` for recipe data |
| 4 | 1 | Profile ID | User profile (1-4) |
| 5 | 1 | Recipe ID | Beverage type (same IDs as brew command) |
| 6:-2 | variable | Parameters | Recipe-specific parameters |
| -2: | 2 | CRC-16 | CRC-16/CCITT over bytes [0:-2] |

### Example: Profile 1 Espresso

Property `d059_rec_1_espresso`, value: `0BKm8AEBCAABACgbAQIEGQFnbg==`

```
D0              Start marker (recipe)
12              Length (18)
A6 F0           Type: Recipe data
01              Profile ID: 1
01              Recipe ID: Espresso
08 00 01 00 28  Parameters (size=40ml at offset +4)
1B 01 02 04     Parameters continued
19 01           Parameters continued
67 6E           CRC-16
```

### Example: Profile 1 Regular Coffee

Property `d060_rec_1_regular`, value: `0BCm8AECGQEbAQEAtAICL7A=`

```
D0              Start marker (recipe)
10              Length (16)
A6 F0           Type: Recipe data
01              Profile ID: 1
02              Recipe ID: Regular Coffee
19 01 1B 01     Parameters
01 00 B4 02 02  Parameters (size=180ml at offset +4)
2F B0           CRC-16
```

## Recipe Parameters

Recipe parameters are encoded as variable-length byte sequences. The exact encoding has not been fully decoded, but observed patterns include:

### Known Parameter Values

From comparing espresso (40ml) and regular coffee (180ml):

| Byte value | Decimal | Likely meaning |
|------------|---------|----------------|
| `0x14` | 20 | 20 ml |
| `0x28` | 40 | 40 ml (espresso default) |
| `0x50` | 80 | 80 ml |
| `0x64` | 100 | 100 ml |
| `0xB4` | 180 | 180 ml (regular coffee default) |
| `0xF8` | 248 | ~250 ml |

The parameters appear to encode the beverage size in milliliters as a direct byte value. Other parameters likely encode strength, temperature, milk level, and grind settings, but the exact byte positions vary between beverage types.

### Relationship Between Stored Recipe and Brew Command

The recipe parameters stored in per-profile properties (e.g., `d059_rec_1_espresso`) are reused in the brew command payload. The brew command wraps them with the `0x83F0` command type:

```
Stored recipe:  [D0] [len] [A6 F0] [profile] [recipe_id] [params] [CRC]
Brew command:   [0D] [len] [83 F0] [recipe_id] [03]       [params] [CRC] [timestamp] [suffix]
```

Note that the stored recipe includes the profile ID and has a different ordering, while the brew command uses `0x03` as a subcommand byte and includes a timestamp trailer.

## Device Properties Reference

### Command Properties (direction: input)

| Property | Type | Description |
|----------|------|-------------|
| `app_data_request` | string | Primary command channel. Base64-encoded binary packets. |
| `app_device_connected` | string | Connection handshake. Contains timestamp + device suffix. |

### Status Properties (direction: output)

| Property | Type | Description |
|----------|------|-------------|
| `app_data_response` | string | Machine responses (base64 binary) |
| `app_device_status` | string | Machine state: `"RUN"` = ready/on |
| `app_id` | string | Connection identifier |
| `software_version` | string | Firmware version (e.g., `"Striker_cb_demo 1.1.0 Oct 18 2022"`) |
| `d302_monitor_machine` | string | Real-time machine monitoring (binary) |

### Machine Settings (direction: output, base64 binary)

| Property | Description |
|----------|-------------|
| `d280_mach_sett_pin` | Machine PIN settings |
| `d281_mach_sett_temperature` | Temperature settings |
| `d282_mach_sett_auto_off` | Auto-off timer |
| `d283_mach_sett_water_hard` | Water hardness setting |
| `d284_mach_sett_user_conf` | User configuration |
| `d285_mach_sett_radio_conf` | Radio/wireless configuration |
| `d286_mach_sett_profile` | Active profile selection |

### Maintenance Counters (direction: output, integer)

| Property | Description | Example Value |
|----------|-------------|---------------|
| `d510_ground_cnt_percentage` | Coffee grounds container fill level (%) | 14 |
| `d512_percentage_to_deca` | Descaling progress (%) | 126 |
| `d513_percentage_usage_fltr` | Water filter usage (%) | 0 |
| `d524_ix_calcare_alm_qty` | Limescale alarm quantity | 2 |
| `d525_max_pos` | Maximum position (grinder?) | 484 |
| `d550_water_calc_qty` | Water volume for calc purposes (ml?) | 1769100 |
| `d551_cnt_coffee_fondi` | Coffee grounds puck count | 80 |
| `d552_cnt_calc_tot` | Total descaling cycles | 10 |
| `d553_water_tot_qty` | Total water dispensed (ml?) | 1287739 |
| `d554_cnt_filter_tot` | Total filter replacements | 1 |
| `d555_water_filter_qty` | Water through current filter | 0 |
| `d556_water_hardness` | Water hardness level (0-4) | 2 |
| `d558_bev_cnt_desc_on` | Beverages since last descale | 134 |

### Beverage Counters (direction: output, integer)

| Property | Description | Example |
|----------|-------------|---------|
| `d701_tot_bev_b` | Total black beverages | 1646 |
| `d704_tot_bev_espressi` | Total espressos (all types) | 370 |
| `d705_tot_id1_espr` | Total single espressos | 319 |
| `d706_tot_id2_coffee` | Total regular coffees | 1226 |
| `d707_tot_id3_long` | Total long coffees | 8 |
| `d708_tot_id5_doppio_p` | Total doppio+ | 34 |
| `d709_id6_americano` | Total americanos | 14 |
| `d710_tot_id7_capp` | Total cappuccinos | 350 |
| `d711_id8_lattmacc` | Total latte macchiatos | 100 |
| `d712_id9_cafflatt` | Total caffe lattes | 57 |
| `d713_id10_flatwhite` | Total flat whites | 56 |
| `d714_id11_esprmacc` | Total espresso macchiatos | 0 |
| `d715_id12_hotmilk` | Total hot milks | 216 |
| `d716_id13_cappdoppio_p` | Total cappuccino doppio+ | 0 |
| `d717_id15_caprev` | Total cappuccino reverse | 45 |
| `d718_id16_hotwater` | Total hot waters | 1 |
| `d719_id22_tea` | Total teas | 0 |
| `d720_tot_id23_coffee_pot` | Total coffee pots | 0 |
| `d730_tot_id27_brew_over_ice` | Total brew-over-ice | 2 |

### Extended Counters (direction: output, JSON string)

| Property | Contains |
|----------|----------|
| `d702_tot_bev_other` | `tot_bev_bw` (black+water), `tot_bev_other`, `tot_bev_w` (water) |
| `d733_tot_bev_counters` | Mug sizes (hot/cold small/medium/large), iced totals |
| `d734_tot_bev_usage` | Pre-ground count, taste stats, custom counts, abort count, 2x count |
| `d735_iced_bev` | Per-type iced beverage counters |
| `d736_mug_bev` | Per-type mug beverage counters |
| `d737_mug_iced_bev` | Per-type iced mug counters |
| `d738_cold_brew_bev` | Per-type cold brew counters |
| `d739_taste_bev` | Taste scores for espressos and coffees |
| `d740_water_qty_bev` | Water quantities per beverage type |

### Service Parameters (direction: output, JSON string)

| Property | Contains |
|----------|----------|
| `d580_service_parameters` | `water_misuse_calc_abs_qty`, `descale_status`, last calc thresholds |
| `d581_service_parameters` | Water quantities for steamer, heater, cold branch (abs + relative) |

### Bean System (direction: output, base64 binary)

| Property | Description |
|----------|-------------|
| `d250_beansystem_0` | Default bean settings |
| `d251_beansystem_1` through `d256_beansystem_6` | Bean presets 1-6 (name + settings) |
| `d260_beansystem_par` | Bean system parameters |

### User Profiles (direction: output, base64 binary)

| Property | Description |
|----------|-------------|
| `d051_profile_name1_3` | Profile names for profiles 1-3 |
| `d052_profile_name4` | Profile name for profile 4 |
| `d053_custom_name_13` | Custom beverage names 1-3 |
| `d054_custom_name_46` | Custom beverage names 4-6 |

### Recipe Priority (direction: output, base64 binary)

| Property | Description |
|----------|-------------|
| `d261_recipe_priority_1` through `d264_recipe_priority_4` | Display order of recipes per profile |
| `d265_favorite_priority_1` through `d268_favorite_priority_4` | Favorite beverage order per profile |

## Constructing a Brew Command

Complete algorithm to brew a beverage. **All steps are required** — skipping the connection handshake results in the machine acknowledging but not executing commands.

### Step 1: Get Device Suffix

Read the `app_device_connected` property. The last 4 bytes of the base64-decoded value are the device suffix.

```python
import base64
data = base64.b64decode(app_device_connected_value)
device_suffix = data[-4:]  # e.g., b'\x00\x19\xa7\xa9'
```

### Step 2: Send Connection Handshake

Write a timestamp + device suffix to `app_device_connected`:

```python
import struct, time

timestamp = int(time.time())
handshake = base64.b64encode(
    struct.pack(">I", timestamp) + device_suffix
).decode()

# POST to app_device_connected
```

### Step 3: Send Init Command (`0xE8F0`)

```python
init_payload = bytes([0xE8, 0xF0, 0x00, 0xED, 0x7C])
init_length = len(init_payload) + 3
init_crc_input = bytes([0x0D, init_length]) + init_payload
init_crc = crc16_ccitt(init_crc_input)
init_packet = init_crc_input + struct.pack(">H", init_crc) + struct.pack(">I", timestamp) + device_suffix
init_command = base64.b64encode(init_packet).decode()

# POST to app_data_request
```

### Step 4: Get Recipe Parameters

Read the stored per-profile recipe property for the desired beverage. For example, for Profile 1 Espresso, read `d059_rec_1_espresso`.

```python
data = base64.b64decode(recipe_property_value)
# data[0] = 0xD0 (start), data[1] = length
# data[4] = profile_id, data[5] = recipe_id
recipe_params = data[6:-2]  # everything between header and CRC
```

### Step 5: Build and Send the Brew Packet

```python
recipe_id = 0x01  # espresso
subcommand = 0x03
timestamp = int(time.time())

# Payload
payload = bytes([0x83, 0xF0, recipe_id, subcommand]) + recipe_params

# Length byte
length = len(payload) + 3  # +1 (length byte) +2 (CRC)

# CRC input: start marker + length + payload
crc_input = bytes([0x0D, length]) + payload
crc = crc16_ccitt(crc_input)

# Full packet
packet = crc_input + struct.pack(">H", crc) + struct.pack(">I", timestamp) + device_suffix

# Base64 encode for Ayla
command = base64.b64encode(packet).decode("ascii")

# POST to app_data_request
```

### Step 6: Verify

Read `app_data_response` to check the machine's reply. A response with command type `0x83F0` and status byte `0x00` indicates success.

```
Response: D0 07 83 F0 [recipe_id] 00 [extra] [timestamp]
                                   ^^ 0x00 = success
```

## Device Information

### Tested Device

| Field | Value |
|-------|-------|
| OEM Model | DL-striker-cb |
| Ayla Model | AY008ESP1 |
| Firmware | Striker_cb_demo 1.1.0 Oct 18 2022 |
| WiFi Module | ESP (esp-idf-v3.3.1) |
| Ayla SDK | ADA 1.6 |

### Ayla Configuration

| Setting | Value |
|---------|-------|
| Auth Base URL | `https://user-field-eu.aylanetworks.com` |
| ADS Base URL | `https://ads-eu.aylanetworks.com` |
| App ID | `DLonghiCoffeeIdKit-sQ-id` |
| App Secret | `DLonghiCoffeeIdKit-HT6b0VNd4y6CSha9ivM5k8navLw` |
| Gigya API Key | `3_e5qn7USZK-QtsIso1wCelqUKAK_IVEsYshRIssQ-X-k55haiZXmKWDHDRul2e5Y2` |

## Unknown / Future Work

- **Recipe parameter encoding**: The exact meaning of each byte in the recipe parameters is not fully decoded. Size in ml appears as a direct byte value, but the positions of strength, temperature, grind, and milk level vary between beverage types.
- **Machine responses**: The `app_data_response` property receives binary responses from the machine. The format has not been analyzed.
- **Machine monitoring**: The `d302_monitor_machine` property contains real-time status in binary form.
- **Power on/off**: The command to power on/off the machine has not been captured. It likely uses a different command type through `app_data_request`.
- **Recipe modification**: Writing to per-profile recipe properties to change beverage settings (size, strength, etc.) has not been tested.
- **Iced/mug/cold-brew recipes**: These use additional recipe IDs (0x32+ for iced, 0x50+ for mug variants, 0x78+ for cold brew) and may have different parameter structures.
- **Default recipe format**: The `d002_rec_default_1` through `d008_rec_default_7` properties contain JSON with longer base64 blobs that define the full parameter ranges (min/max/default) for each recipe. These have not been decoded.
