"""Cliente de impresora Y50: transporte SPP/USB + operaciones de alto nivel."""
import glob
import os
import select
import socket
import sys
import time

from . import ypl

DEFAULT_MAC = "55:55:09:15:A5:2E"
RFCOMM_CHANNEL = 1
USB_GLOB = "/dev/usb/lp*"
USB_VID, USB_PID = "5958", "0150"   # Y50P/Y50 estilo Knaon (CTP800 = 0130, ¡distinto protocolo!)


class SPPTransport:
    name = " bluetooth SPP"

    def __init__(self, addr: str, channel: int = RFCOMM_CHANNEL):
        self.addr = addr
        self.sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        self.sock.settimeout(15)
        self.sock.connect((addr, channel))
        self.name = f"Bluetooth SPP {addr} ch{channel}"

    def write(self, data: bytes):
        for i in range(0, len(data), 1024):
            self.sock.sendall(data[i:i + 1024])
        return len(data)

    def read(self, timeout: float) -> bytes:
        self.sock.settimeout(timeout)
        buf = b""
        try:
            while True:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
        except (socket.timeout, BlockingIOError):
            pass
        return buf

    def close(self):
        self.sock.close()


class USBTransport:
    def __init__(self, device: str):
        self.name = f"USB {device}"
        self.fd = os.open(device, os.O_RDWR | os.O_NONBLOCK)

    def write(self, data: bytes):
        return os.write(self.fd, data)

    def read(self, timeout: float) -> bytes:
        buf = b""
        while select.select([self.fd], [], [], timeout)[0]:
            chunk = os.read(self.fd, 4096)
            if not chunk:
                break
            buf += chunk
        return buf

    def close(self):
        os.close(self.fd)


def usb_ids(node: str):
    link = f"/sys/class/usbmisc/{os.path.basename(node)}"
    if not os.path.exists(link):
        return None
    dev = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(link))))
    try:
        with open(f"{dev}/idVendor") as f:
            vid = f.read().strip()
        with open(f"{dev}/idProduct") as f:
            pid = f.read().strip()
    except OSError:
        return None
    return vid, pid


def find_usb():
    for dev in sorted(glob.glob(USB_GLOB)):
        if usb_ids(dev) == (USB_VID, USB_PID):
            return dev
    return None


class Printer:
    def __init__(self, target: str | None = None):
        self._target = target
        self.t = None

    def connect(self):
        if self.t is None:
            target = self._target
            if target is None:
                target = find_usb()
            if target is None:
                target = DEFAULT_MAC
            self.t = USBTransport(target) if target.startswith("/") else SPPTransport(target)
        return self.t

    def close(self):
        if self.t is not None:
            try:
                self.t.close()
            except OSError:
                pass
            self.t = None

    def transact(self, frames: list[bytes], read_timeout=0.8) -> list[bytes]:
        """manda los frames y devuelve las respuestas decodificadas en orden"""
        t = self.connect()
        buf = b""
        for f in frames:
            t.write(f)
            time.sleep(0.02)
            buf += t.read(read_timeout)
        return [ypl.decode_payload(p) for p in ypl.parse_replies(buf)]

    def info(self) -> dict:
        out: dict = {}
        t = self.connect()
        buf = b""
        for name in ypl.SAFE_QUERIES:
            g, c = ypl.QUERIES[name]
            t.write(ypl.request(g, c))
            time.sleep(0.15)
            buf += t.read(0.8)
        for payload in ypl.parse_replies(buf):
            dec = ypl.decode_payload(payload)
            if not dec:
                continue
            g, c, d, v = dec
            for name, (qg, qc) in ypl.QUERIES.items():
                if (g, c) == (qg, qc) and d == ypl.DIR_REPLY:
                    if name == "status":
                        raw = v[0] if isinstance(v, bytes) and v else v
                        out["status_raw"] = raw
                        out["status"] = ypl.describe_status(raw)
                        out["ready"] = raw == 0
                    elif isinstance(v, (bytes, bytearray)):
                        txt = v.decode("ascii", "replace").strip()
                        out[name] = txt
        return out

    def print_rows(self, rows, width_mm, copies=1, density=8, on_status=None):
        """imprime `copies` etiquetas; comprueba el estado antes de cada copia"""
        errors = []
        for _i in range(copies):
            for g, c, d, v in self.transact([ypl.request(0x05, 0x0B)], 0.8):
                if (g, c) == (0x05, 0x0B) and d == ypl.DIR_REPLY:
                    raw = v[0] if isinstance(v, bytes) and v else v
                    if raw != 0:
                        raise RuntimeError(f"impresora no lista: {ypl.describe_status(raw)} (0x{raw:02x})")
                    if on_status:
                        on_status("listo")
            stream = ypl.build_stream(rows, width_mm, job=0x08 + _i, density=density)
            self._send_stream(stream)
            if on_status:
                on_status(f"etiqueta {_i + 1}/{copies} enviada")
        # esperar a que desocupe
        deadline = time.time() + 8 if copies == 1 else time.time() + 8 + 4 * copies
        while time.time() < deadline:
            info = self._poll_status()
            if isinstance(info, int) and info == 0:
                break
            time.sleep(0.5)
        self.close()
        return errors if errors else None

    def _send_stream(self, stream: bytes):
        """envía todo el flujo troceado sobre los límites de frame"""
        t = self.connect()
        i = 0
        while i < len(stream):
            nxt = stream.find(b"\x1a", i + 1)
            chunk = stream[i:nxt] if nxt != -1 else stream[i:]
            t.write(chunk)
            i = nxt if nxt != -1 else len(stream)
            time.sleep(0.01)
        time.sleep(2)

    def feed(self):
        t = self.connect()
        for h in ("0537010000", "051a010000"):
            t.write(ypl.frame(h))
            time.sleep(0.02)
        time.sleep(2)
        self.close()

    def _poll_status(self):
        try:
            for g, c, d, v in self.transact([ypl.request(0x05, 0x0B)], 0.8):
                if (g, c) == (0x05, 0x0B) and d == ypl.DIR_REPLY:
                    return v[0] if isinstance(v, bytes) and v else v
        except OSError:
            self.close()
        return None


def explain_link_error(err: OSError) -> str:
    usb = find_usb() or "no conectado"
    return (
        f"no puedo alcanzar la impresora: {err}\n"
        f"  USB: {usb}\n"
        f"  Si el móvil tiene conectada la impresora por la app, el socket SPP\n"
        f"  clásico se rechaza. Desconéctala ahí e inténtalo otra vez."
    )
