"""Protocolo YPL para impresoras térmicas de etiquetas (familia Knaon Y50 / Y50P, FlashLabel Pro).

Implementado a partir de la ingeniería inversa documentada en
https://github.com/slastra/yplib (FINDINGS.md), verificada sobre hardware Y50 real:

  frame  := 1a 01 <len:u16 LE> <payload> <crc32:u32 LE> a1
  crc32  := CRC-32 reflejado, poly 0xEDB88320, init 0xCA896ADE, xorout 0xFFFFFFFF
  payload:= <group:1> <cmd:1> <dir:1> <len:u16 LE> <data>
  raster := (0x18 <run>*)*   con run = <color:1><count-1:7>, filas de W px

El protocolo es agnóstico del transporte: los mismos bytes funcionan por
Bluetooth clásico SPP (RFCOMM canal 1), USB y BLE.
"""
import socket
import time
import zlib

CRC_INIT = 0xCA896ADE
DPI = 8                       # puntos por mm (203 dpi aprox)
ROW_MARK = 0x18

DIR_REQUEST, DIR_REPLY, DIR_EVENT, DIR_SET = 0x01, 0x02, 0x03, 0x04
DTYPE_BYTES, DTYPE_INT = 0x01, 0x03

STATUS_FLAGS = [
    (0x01, "imprimiendo"),
    (0x02, "tapa abierta"),
    (0x04, "sin papel"),
    (0x08, "bajo voltaje"),
    (0x10, "sobrecalentada"),
]


def crc(payload: bytes) -> int:
    return zlib.crc32(payload, CRC_INIT ^ 0xFFFFFFFF)


def frame(payload_hex: str | bytes) -> bytes:
    p = bytes.fromhex(payload_hex) if isinstance(payload_hex, str) else payload_hex
    return (
        b"\x1a\x01"
        + len(p).to_bytes(2, "little")
        + p
        + crc(p).to_bytes(4, "little")
        + b"\xa1"
    )


def request(group: int, cmd: int, data: bytes = b"", direction: int = DIR_REQUEST) -> bytes:
    p = bytes([group, cmd, direction]) + len(data).to_bytes(2, "little") + data
    return frame(p)


# --- preámbulo / trabajo de impresión ---------------------------------------

def preamble(width_mm: int, density: int = 8) -> list[str]:
    w = (width_mm & 0xFF).to_bytes(2, "little").hex()
    dens = bytes([density]).hex()
    return [
        "0104010000", "0104010000", "01b7010000", "0107010000", "0102010000",
        "050b010000", "050b010000", "050b010000", "050b010000", "050b010000",
        "050b010000",
        "052001010000",          # tipo de papel: 0 etiqueta
        "0511010100" + dens,     # densidad
        "0519010000",            # inicio de trabajo
        "0536010000",            # retirada de papel inicial
        "050b010000",
        f"0541040200{w}00",      # ancho del lienzo (mm)
        f"0538040200{w}00",      # ancho de impresión (mm)
        "05400402000000",        # offset = 0
    ]



JOB_FRAME = "0539040100%02x"

TRAILER = [
    "0521010000",
    "0537010000",
    "051a010000",
    "050b010000",
    "050b010000",
    "050b010000",
    "050b010000",
    "050b010000",
    "050b010000",
    "050b010000",
    "050b010000",
    "050b010000",
    "050b010000",
]

QUERIES = {
    "model": (0x01, 0x04),
    "firmware": (0x01, 0x07),
    "serial": (0x01, 0x02),
    "hwinfo": (0x01, 0xB7),
    "status": (0x05, 0x0B),
}

# Consultas seguras (sin efectos sobre el papel)
SAFE_QUERIES = ["model", "firmware", "serial", "hwinfo", "status"]


def describe_status(v: int) -> str:
    if v == 0:
        return "listo"
    flags = []
    for bit, name in STATUS_FLAGS:
        if v & bit:
            if bit == 0x04 and (v & 0x02):
                continue  # la tapa abierta fuerza el bit de papel
            flags.append(name)
    rest = v & ~sum(bit for bit, _ in STATUS_FLAGS)
    if rest:
        flags.append(f"bits desconocidos 0x{rest:02x}")
    return ", ".join(flags) or f"desconocido (0x{v:02x})"


# --- raster RLE -------------------------------------------------------------

def encode_raster(rows: list[list[int]]) -> bytes:
    """Filas de 0/1 (1 = negro). Cada fila debe medir exactamente el ancho."""
    out: list[int] = []
    width = len(rows[0])
    for row in rows:
        if len(row) != width:
            raise ValueError("todas las filas deben medir el mismo ancho")
        out.append(ROW_MARK)
        i = 0
        while i < len(row):
            color = row[i]
            n = 1
            while i + n < len(row) and row[i + n] == color and n < 128:
                n += 1
            out.append((color << 7) | (n - 1))
            i += n
    return bytes(out)


def decode_raster(blob: bytes, width: int) -> list[list[int]]:
    rows, i = [], 0
    while i < len(blob):
        if blob[i] != ROW_MARK:
            raise ValueError(f"sin marcador de fila en {i}")
        i += 1
        row, x = [], 0
        while x < width:
            if i >= len(blob):
                raise ValueError("raster truncado")
            b = blob[i]
            i += 1
            color, n = b >> 7, (b & 0x7F) + 1
            row.extend([color] * n)
            x += n
        if x != width:
            raise ValueError("fila desbordada")
        rows.append(row)
    return rows


def build_stream(rows: list[list[int]], width_mm: int, job: int = 0x08,
                 density: int = 8, copies: int = 1) -> bytes:
    """Una etiqueta completa: preámbulo + raster + tráiler."""
    dots = width_mm * DPI
    if not rows:
        raise ValueError("raster vacío")
    if len(rows[0]) != dots:
        raise ValueError(f"cada fila debe medir {dots} px para {width_mm} mm (lleva {len(rows[0])})")
    parts = [frame(p) for p in preamble(width_mm, density)]
    parts.append(frame(JOB_FRAME % job))
    parts.append(encode_raster(rows))
    parts += [frame(p) for p in TRAILER]
    return b"".join(parts)


# --- servidor de impresión (preámbulo repetido por copia) ---------------------

def build_jobs(rows, width_mm, copies=1, job=0x08, density=8):
    for c in range(copies):
        yield build_stream(
            rows,
            width_mm,
            job=(job + c) & 0xFF,
            density=density,
        )


# --- descodificación de respuestas -------------------------------------------

def decode_payload(payload: bytes):
    """-> (group, cmd, dir, value: bytes|int)"""
    if len(payload) < 5:
        return None
    group, cmd, direction = payload[0], payload[1], payload[2]
    ln = int.from_bytes(payload[3:5], "little")
    data = payload[5:5 + ln]
    value: bytes | int = data
    if direction == DIR_REPLY and len(data) >= 3:
        dtype = data[0]
        vlen = int.from_bytes(data[1:3], "little")
        raw = data[3:3 + vlen]
        if dtype == DTYPE_INT:
            value = int.from_bytes(raw, "little")
        elif dtype == DTYPE_BYTES:
            value = raw
    return group, cmd, direction, value


def parse_replies(buf: bytes):
    """Analiza un buffer de bytes en payloads válidos (tolerante a desync).

    Esta impresora Y50 responde con frames de VERSIÓN 2 (cabecera 1a 02 ...), la
    Y50P con v1: formato idéntico salvo el byte de versión; CRC y datos iguales.
    Acepto ambas."""
    out = []
    i = 0
    while i + 9 <= len(buf):
        is_v1 = buf[i] == 0x1A and buf[i + 1] == 0x01
        is_v2 = buf[i] == 0x1A and buf[i + 1] == 0x02
        if not (is_v1 or is_v2):
            i += 1
            continue
        ln = buf[i + 2] | (buf[i + 3] << 8)
        end = i + 4 + ln + 4
        if end >= len(buf) or buf[end] != 0xA1:
            i += 1
            continue
        payload = buf[i + 4:i + 4 + ln]
        want = int.from_bytes(buf[end - 4:end], "little")
        if crc(payload) == want and ln >= 5:
            out.append(payload)
        i = end + 1
    return out
