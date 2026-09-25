# Bitfocus Companion integration

Code: `src/cuekeys/companion.py` (HTTP and Satellite client), and `runtime.py` (mapping,
state, events). Tested against Companion **4.2.0** (Satellite API 1.9) and **5.0.6** (API 1.12).

## Two mechanisms

| | HTTP remote API | Satellite surface |
|---|---|---|
| Used by | the `companion` action (one specific button) | layers with `mode: "companion"` |
| Transport | `POST http://host:8000/api/location/<page>/<row>/<col>/{down,up,press}` | TCP `host:16622`, line-based text protocol |
| Direction | keypad → Companion | both ways: key presses go out, button colour, text and page come back |
| Needs | Companion's web/HTTP port | Satellite port (default on) |

## Satellite details

**Registration**

```
← BEGIN CompanionVersion="5.0.6+…" ApiVersion="1.12.0"
← CAPS SUBSCRIPTIONS=0 NONSQUARE=1 BITMAP_FORMATS="rgb,png,webp"     (API ≥ 1.10 only)
→ ADD-DEVICE DEVICEID=ck-e35b8c2b-example PRODUCT_NAME="CueKeys FOH · Companion" KEYS_TOTAL=12 KEYS_PER_ROW=4
             BITMAPS=0 COLORS=hex TEXT=true TEXT_STYLE=true CAN_CHANGE_PAGE=true
← ADD-DEVICE OK DEVICEID="ck-e35b8c2b-example"
← KEY-STATE DEVICEID="ck-e35b8c2b-example" KEY=0 LOCATION="4/0/0" TYPE="BUTTON" COLOR="#ff0000"
            TEXTCOLOR="#ffffff" TEXT="<base64>" FONT_SIZE="auto" PRESSED=0
→ KEY-PRESS DEVICEID=ck-e35b8c2b-example KEY=0 PRESSED=true
→ CHANGE-PAGE DEVICEID=ck-e35b8c2b-example DIRECTION=1                        (API ≥ 1.10)
↔ PING x / PONG x                                                       (every 2 s)
```

**Surface shape.** One surface per Companion layer: `companion_rows × width` keys, where the width
is the device profile's display width at the current rotation. By default every row except the
bottom one goes to Companion, so the bottom row stays local, e.g. layer, page and overlay keys.
Keys you assign locally inside the Companion region override Companion.

**Key mapping.** Satellite keys are numbered left to right, top to bottom.
`profile.satellite_index(key, rotation)` and `profile.key_from_satellite(index, rotation)` convert
between them and keypad key numbers.

**Surface ids** are `ck-<keypad>-<layer>`:

- `<keypad>` is the last 8 hex digits of the keypad's hardware id, so two keypads with the same layout
  are two surfaces, and a keypad keeps its surface (and its Companion page settings) on any computer.
  The virtual "No keypad" uses the host name instead.
- `<layer>` is `layer.companion_id` (the editor gives new Companion layers a random 6-hex id, so it
  survives reordering and renaming), or `l<index>` without one. Ids from before keypad identity
  (`ck-…`, `cuekeys-…`, `pmk-…`) lose that prefix: `cuekeys-example` → `ck-e35b8c2b-example`.

The surface name is `CueKeys <keypad name> · <layer name>`; rename a keypad in the editor
(Keypad → Rename keypad…) or with `cuekeys keypads rename`. All surfaces on one Companion server share
one Satellite connection (`Hub.sync_satellites`).

**State kept per key:** `color`, `text`, `text_color`, `type` (BUTTON / PAGEUP / PAGEDOWN / PAGENUM),
`pressed`, `location` and `page`, plus `page_name` added by the runtime.

## Quirks we hit, and how the client handles them

1. **Companion 5 ignores `ADD-DEVICE` sent before `CAPS`.** Registering right after `BEGIN` gets no
   reply at all. The client registers after `CAPS` when `ApiVersion ≥ 1.10`, and right after `BEGIN`
   on older servers.
2. **A duplicate surface id gets silence on 5.x and `ERROR … "Device exists elsewhere"` on 4.x.** This
   happens when another process (a second app instance, a hung test run) holds the same
   `DEVICEID`. The client resends after 5 s when there's no reply, retries every 10 s on an error,
   and logs a hint. `KeypadSession.companion_status()` returns `busy` and the UI pill turns amber.
3. **Re-adding an id on the same connection is rejected.** To rename or resize a surface, send
   `REMOVE-DEVICE` and then `ADD-DEVICE` (see `add_device()`).
4. **Page names are never sent over Satellite.** Page-number buttons (`TYPE=PAGENUM`) arrive with
   empty text. The runtime fetches `GET /api/variable/internal/page_number_<n>_name/value` (HTTP) and
   caches it per `(target, page)`.
5. **`LOCATION` (API ≥ 1.10)** gives `page/row/column`. It's used for the page indicator and the
   location badge, which is hidden on page up/down/number buttons, empty slots and locally
   assigned keys.
6. **Black buttons with text are real buttons.** Only black *and* empty is an empty slot (drawn dimmed).
7. **`CHANGE-PAGE` needs API ≥ 1.10 and `CAN_CHANGE_PAGE=true` in `ADD-DEVICE`.** On older servers
   `change_page()` returns False and the UI logs "needs Companion 4.3 or newer".
8. **Grid size.** If Companion's button grid is smaller than the surface (for example a 3×2 grid
   from a Stream Deck Mini setup), Companion warns that the surface overflows. Use *Resize grid to
   fit* in Buttons.

## Recommended Companion setup

1. Settings → OSC & Companion: `{"default": {"host": "…", "http_port": 8000, "satellite_port": 16622}}`.
2. Give the CueKeys surface its own pages. In Pages, add pages such as "CueKeys 1" and "CueKeys 2" at the end,
   so existing page numbers don't shift. Then, in Surfaces → your CueKeys surface:
   - turn off *Use Last Page At Startup*;
   - set *Startup Page* to your first CueKeys page;
   - turn on *Restrict pages accessible to this surface* and pick the CueKeys pages.

   The keypad's `companion_page` keys (◀ Page / Page ▶) then cycle through only those pages.
3. Several Companion layers means several independent surfaces, and each can have its own pages.

## Testing without Companion

`tests/test_companion.py` runs the client against a local fake TCP server and a local
`http.server`. `tests/test_runtime.py` uses `FakeSatellite` via `Runtime(satellite_factory=…)`.
Never point tests at 127.0.0.1:16622: a developer's real Companion might be listening there, and
test surfaces would get registered in their config.
