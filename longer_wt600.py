# Dummy fuer backend/drivers/longer_wt600.py (Longer WT600-2J, binaeres LONGER-RS485-Protokoll,
# Quelle: docs/protokoll_pumpe.md im LABS-Backend-Repo - ein Blogpost, kein Herstellerhandbuch).
#
# Anders als alle anderen Dummys hier (base.BaseDummyProtocol) NICHT zeilenbasiert: das
# WT600-Protokoll ist binaer und selbstbeschreibend ueber ein Laengenbyte, nicht ueber ein
# Text-Trennzeichen - siehe denselben Framer in backend/drivers/longer_wt600.py
# (WT600Protocol.dataReceived) fuer die ausfuehrliche Begruendung. Dieser Dummy implementiert
# denselben laengenbasierten Framer eigenstaendig (Protocol statt LineOnlyReceiver), inkl.
# XOR-Pruefsummenpruefung, und haelt den zuletzt gesetzten Zustand (Drehzahl/Lauf/Richtung) vor,
# damit RJ (Read running parameter) sinnvolle Werte liefert.
#
# Simuliert: WJ (Set running parameter: Drehzahl+Start/Stop+Richtung in einem Frame) und
# RJ (Read running parameter). WID/RID (Pumpenadresse schreiben/lesen) sind im Treiber nicht
# implementiert und werden hier deshalb auch nicht simuliert.

from twisted.internet.protocol import Protocol
from twisted.logger import Logger

FLAG = 0xE9


def _xor(data) -> int:
    checksum = 0
    for byte in data:
        checksum ^= byte
    return checksum


def _build_frame(address: int, pdu: bytes) -> bytes:
    body = bytes([address & 0xFF, len(pdu)]) + pdu
    return bytes([FLAG]) + body + bytes([_xor(body)])


class DeviceProtocol(Protocol):
    log_name = "Longer WT600-2J (dummy)"

    def __init__(self):
        self.log = Logger(namespace=self.log_name)
        self._buffer = bytearray()
        self.speed = 0
        self.running = False
        self.clockwise = True

    def dataReceived(self, data):
        self._buffer.extend(data)
        while True:
            while self._buffer and self._buffer[0] != FLAG:
                del self._buffer[0]
            if len(self._buffer) < 3:
                return
            frame_length = 3 + self._buffer[2] + 1  # Flag+Adresse+Laengenbyte + PDU + FCS
            if len(self._buffer) < frame_length:
                return
            frame = bytes(self._buffer[:frame_length])
            del self._buffer[:frame_length]
            self._handle_frame(frame)

    def _handle_frame(self, frame: bytes):
        self.log.info(f"received: {frame.hex(' ').upper()}")
        address, length = frame[1], frame[2]
        pdu, fcs = frame[3:3 + length], frame[-1]
        if _xor(frame[1:-1]) != fcs:
            self.log.info(f"checksum mismatch in {frame.hex(' ').upper()}, ignoring")
            return

        command = pdu[:2]
        if command == b"WJ" and length == 6:
            self.speed = (pdu[2] << 8) | pdu[3]
            self.running = bool(pdu[4] & 0x01)
            self.clockwise = bool(pdu[5] & 0x01)
            # Echo der neuen Drehzahl/State - unverifizierte Annahme, siehe Treiberkommentar
            # (WT600Parser) in backend/drivers/longer_wt600.py.
            reply_pdu = b"WJ" + bytes([(self.speed >> 8) & 0xFF, self.speed & 0xFF, pdu[4], pdu[5]])
        elif command == b"RJ" and length == 2:
            state1 = 1 if self.running else 0
            state2 = 1 if self.clockwise else 0
            reply_pdu = b"RJ" + bytes([(self.speed >> 8) & 0xFF, self.speed & 0xFF, state1, state2])
        else:
            self.log.info(f"unhandled command {command!r} in {frame.hex(' ').upper()}")
            return

        reply = _build_frame(address, reply_pdu)
        self.transport.write(reply)
        self.log.info(f"answered: {reply.hex(' ').upper()}")
