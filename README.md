# Y50Web — interfaz web plug-and-play para la Y50

Reemplaza a la app **FlashLabel Pro**: conecta con la impresora térmica
**Knaon Y50** por Bluetooth clásico (SPP, RFCOMM canal 1) usando su protocolo
nativo YPL (frames `1a 01`/`1a 02` con CRC-32 init `0xCA896ADE` + raster RLE
1-bit a 8 dots/mm ≈ 203 dpi).

Sin dependencias: **solo Python 3 estándar**. Compatible con Linux (BlueZ)
y, si la Y50 se enchufa por USB, también con `/dev/usb/lp*` (clase 07,
vendor `5958:0150`).

## Arranque (30 segundos)

```bash
git clone https://github.com/JContreras11/print-bluetooth.git
cd print-bluetooth
./start.sh                      # -> http://localhost:8899
```

Al abrir la web, pulsa **Impresora** para ver el estado en vivo; diseña y
pulsa **🖨 Imprimir**.

## Poner la impresora a punto (una sola vez por PC)

La Y50 debe estar emparejada/trusted; si no lo está:

```bash
bluetoothctl
> power on
> scan on        # espera a ver "Y50_XXXX"
> pair XX:XX:XX:XX:XX:XX
> trust XX:XX:XX:XX:XX:XX
> connect XX:XX:XX:XX:XX:XX   # opcional, el servidor abre el canal cuando imprime
```

## Para agentes / scripts (todo con HTTP y CLI)

Arranca el servidor y usa la API:

```bash
./start.sh &
curl http://localhost:8899/api/info
#  {"model":"Y50","firmware":"2.1.0","serial":"Y5026410561","status":"listo","ready":true,...}

# prueba de impresión sin construir bitmap (imprime una etiqueta de calibración 50x30):
curl -X POST http://localhost:8899/api/pattern

# sacar una etiqueta en blanco para alinear el rollo:
curl -X POST http://localhost:8899/api/feed

# bytes crudos del protocolo YPL (avanzado):
curl -X POST http://localhost:8899/api/raw \
     -d '{"hex":"01 04 01 00 00"}'          # consulta el modelo; contesta "Y50"
```

Impresión completa (formato detalle):

```jsonc
POST /api/print
{
  "widthMm": 50,          // ancho del rollo en mm (max 50)
  "wDots": 400,           // = widthMm * 8, cada fila del raster mide esto
  "hDots": 240,           // alto de la etiqueta en dots (define la longitud)
  "copies": 1,
  "density": 8,           // 4..14
  "bits": "<base64>"      // 1 bit por punto, MSB primero, fila a fila
}
```

Generador de bits (cliente): el lienzo del navegador ya es 1 px = 1 dot;
`luma < 128` → punto negro. Con PIL también vale: `img.convert("L")`,
`px < 128 → 1`.

Fuera del navegador:

```bash
python3 scripts/print_test.py status          # info + estado
python3 scripts/print_test.py                 # etiqueta "PRUEBA YPL" 50x30
python3 scripts/print_test.py texto "HOLA"    # imprime texto grande
```

Opciones del servidor: `./start.sh --addr MAC --port 9000` (si se omite,
busca USB 5958:0150 y si no usa la MAC guardada en `config.json`).

## Qué hace la interfaz

- Estado en vivo (modelo, firmware, serie, listo/tapa/sin papel) con sondeo.
- Diseñador 1:1: texto (tamaño/negrita/fuente/alineación/saltos), QR,
  Code-128, imágenes y rectángulos; arrastra, redimensiona por esquina,
  flechas 1 mm, Supr; prediseños pequeño/precio/fecha; autosave.
- Copias, densidad, consola de bytes crudos.

## Estructura

| Ruta | Qué es |
|---|---|
| `server.py` | servidor HTTP + API (stdlib) |
| `lib/ypl.py` | protocolo YPL: frames, CRC-32, RLE, parser de respuestas |
| `lib/printer.py` | transportes SPP/USB + operaciones de alto nivel |
| `scripts/print_test.py` | cliente de escritorio/terminal |
| `web/` | interfaz (diseñador canvas; vendor/ con libs MIT locales) |
| `config.json` | opcional: `{"device": "XX:XX:..."}` |

## Notas técnicas

- La app nativa usa el canal clásico SPP, así que se replica exacto
  (socket Linux `AF_BLUETOOTH`/RFCOMM, canal 1); no hace falta BLE.
- Las respuestas del Y50 llegan con byte de versión 2 (`1a 02…`) y la Y50P
  con el 1; el lector acepta ambas y el CRC se validó contra capturas
  reales (documentación: github.com/slastra/yplib).
- Si el móvil sigue conectado a la impresora desde la app, el SPP se
  rechaza (`br-connection-profile-unavailable`): cierra la app y reintenta.
- El protocolo no transmite el alto de la etiqueta: se imprime lo que se
  envía. El corte limpio lo dan las llamadas `0537+051a` del tráiler.
