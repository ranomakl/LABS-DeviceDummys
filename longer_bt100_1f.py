# Dummy fuer backend/drivers/longer_bt100_1f.py (Longer BT100-1F, Messstand II), 06.11.2026.
# Protokoll: LABS-Backend/docs/protokoll_bt100_1f.md (Herstellerdokument BT100-1F-RS485-Protocol.pdf).
#
# Wie der WT600-Dummy binaer und laengenbasiert (Protocol statt LineOnlyReceiver), zusaetzlich mit dem
# Byte-Stuffing der BT100-1F: hinter dem Flag E9 wird E8 -> E8 00 und E9 -> E8 01 uebertragen.
#
# Simuliert: WF (Flussrate in nL/min + Start/Stop/Richtung), RF (lesen), RT (Kopf/Schlauch), RID.
# Der Dummy rechnet mit, wie lange die Pumpe lief und wie viel sie dabei gefoerdert haette
# (Flussrate * Laufzeit) und schreibt das bei jedem Stopp ins Log - damit laesst sich am PC pruefen,
# ob eine Zugabe (valve_dosing.py) die richtigen Volumen foerdert.

import time

from twisted.internet.protocol import Protocol
from twisted.logger import Logger

from base import ist_stumm

FLAG = 0xE9
ESCAPE = 0xE8
PUMP_HEAD = 3      # DG 6 Rollen (wie am Geraet, 04.11.2026)
TUBING = 5         # Schlauch Nr. 5 = 1,65 mm


def _xor(data) -> int:
    checksum = 0
    for byte in data:
        checksum ^= byte
    return checksum


def _stuff(data: bytes) -> bytes:
    out = bytearray()
    for byte in data:
        if byte == ESCAPE:
            out += bytes([ESCAPE, 0x00])
        elif byte == FLAG:
            out += bytes([ESCAPE, 0x01])
        else:
            out.append(byte)
    return bytes(out)


def _build_wire_frame(address: int, pdu: bytes) -> bytes:
    body = bytes([address & 0xFF, len(pdu)]) + pdu
    return bytes([FLAG]) + _stuff(body + bytes([_xor(body)]))


class DeviceProtocol(Protocol):
    log_name = "Longer BT100-1F (dummy)"

    def __init__(self):
        self.log = Logger(namespace=self.log_name)
        self._buffer = bytearray()
        self.flow_nl_min = 18_000          # 0,018 mL/min, wie am Geraet vorgefunden
        self.running = False
        self.clockwise = True
        self._started = None               # Zeitpunkt des letzten Starts
        self.total_ml = 0.0                # seit Verbindungsaufbau gefoerdert

    def dataReceived(self, data):
        self._buffer.extend(data)
        while True:
            while self._buffer and self._buffer[0] != FLAG:
                del self._buffer[0]
            if not self._buffer:
                return
            decoded = bytearray()
            i = 1
            complete = False
            while i < len(self._buffer):
                byte = self._buffer[i]
                if byte == FLAG:
                    break
                if byte == ESCAPE:
                    if i + 1 >= len(self._buffer):
                        return
                    nxt = self._buffer[i + 1]
                    decoded.append(ESCAPE if nxt == 0x00 else FLAG if nxt == 0x01 else nxt)
                    i += 2
                else:
                    decoded.append(byte)
                    i += 1
                if len(decoded) >= 2 and len(decoded) == 2 + decoded[1] + 1:
                    complete = True
                    break
            if complete:
                del self._buffer[:i]
                self._handle_frame(bytes(decoded))
            elif i < len(self._buffer) and self._buffer[i] == FLAG:
                del self._buffer[:i]
            else:
                return

    def _handle_frame(self, body: bytes):
        """body = Adresse + Laenge + PDU + FCS (ohne Flag, bereits entstufft)."""
        self.log.info(f"received: E9 {body.hex(' ').upper()}")
        if ist_stumm(type(self).__module__):
            self.log.warn("STUMM-Datei vorhanden - KEINE Antwort")
            return
        address, length = body[0], body[1]
        pdu, fcs = body[2:2 + length], body[-1]
        if _xor(body[:-1]) != fcs:
            self.log.info("checksum mismatch, ignoring")
            return

        if pdu[:2] == b"WF" and length == 7:
            flow = int.from_bytes(pdu[2:6], "big")
            running, clockwise = bool(pdu[6] & 0x01), bool(pdu[6] & 0x02)
            self._apply(flow, running, clockwise)
            reply_pdu = b"WF" + pdu[2:6]
        elif pdu == b"RF":
            state1 = (1 if self.running else 0) | ((1 if self.clockwise else 0) << 1)
            reply_pdu = b"RF" + self.flow_nl_min.to_bytes(4, "big") + bytes([state1])
        elif pdu == b"RT":
            reply_pdu = b"RT" + bytes([PUMP_HEAD, TUBING])
        elif pdu == b"RID":
            reply_pdu = b"RID"
        else:
            self.log.info(f"unhandled command {pdu[:3]!r}")
            return

        reply = _build_wire_frame(address, reply_pdu)
        self.transport.write(reply)
        self.log.info(f"answered: {reply.hex(' ').upper()}")

    def _apply(self, flow_nl_min: int, running: bool, clockwise: bool):
        now = time.time()
        if self.running and self._started is not None and (not running or flow_nl_min != self.flow_nl_min):
            seconds = now - self._started
            volume_ml = self.flow_nl_min / 1e6 * seconds / 60.0
            self.total_ml += volume_ml
            self.log.info(f"GEFOERDERT: {volume_ml * 1000:.1f} uL in {seconds:.2f} s bei "
                          f"{self.flow_nl_min / 1e6:g} mL/min (gesamt {self.total_ml:.3f} mL)")
            self._started = None
        if running and (not self.running or self._started is None):
            self._started = now
            self.log.info(f"LAEUFT mit {flow_nl_min / 1e6:g} mL/min, {'cw' if clockwise else 'ccw'}")
        elif not running and self.running:
            self.log.info("STEHT")
        self.flow_nl_min, self.running, self.clockwise = flow_nl_min, running, clockwise
