# Dummy fuer backend/drivers/endress_hauser_liquiline.py (Endress+Hauser Liquiline CM442/CM448),
# Modbus RTU (seit 12.10.2026 - der Treiber sprach vorher ASCII, das echte Geraet antwortete darauf
# nie; Begruendung und Pruefvektoren im Treiberkopf).
#
# RTU-Frames sind binaer und laengenbasiert, deshalb - wie bei longer_wt600.py - ein eigenes
# twisted.internet.protocol.Protocol statt BaseDummyProtocol (LineOnlyReceiver). Der STUMM-Schalter
# aus base.py (Datei STUMM bzw. STUMM_endress_hauser_liquiline) wird respektiert.
#
# Simuliert: FC03 Read Holding Register fuer einen vollstaendigen AI-Geraetevariablen-Block (Value/
# Status/Unit, 4 Register = 8 Byte). Fuer die drei Register aus config.dummy.yml (0 = pH Kanal 1,
# 4 = pH Kanal 2, 8 = Temperatur) plausible, leicht schwankende Werte mit Status 0 (Good); fuer jedes
# andere Register Status 3 (Not assigned) mit Wert 0.0 - wie das echte Geraet ohne AI-Mapping.
# Anzahl Register muss ein Vielfaches von 4 sein (ganze AI-Bloecke, mehrere je Anfrage erlaubt),
# sonst Modbus-Exception 0x02; andere Funktionscodes -> Exception 0x01.
# Busadresse 1 (config.dummy.yml); Anfragen an andere Adressen werden ignoriert (wie auf einem Bus).

import math
import struct
import time

from twisted.internet.protocol import Protocol
from twisted.logger import Logger

from base import ist_stumm

BUS_ADDRESS = 1
FC_READ_HOLDING_REGISTERS = 0x03

# register -> (Basiswert, Schwankung, Unit-Code)   Unit-Codes Handbuch 7.1: 53 = pH, 89 = degC
SIMULATED_CHANNELS = {
    0: (7.00, 0.05, 53),
    4: (7.20, 0.05, 53),
    8: (23.5, 0.2, 89),
}


def crc16(data: bytes) -> bytes:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc.to_bytes(2, "little")


def encode_float_wire(value: float, byte_order: str = "1-0-3-2") -> bytes:
    std_bytes = struct.pack(">f", value)  # Byte3,Byte2,Byte1,Byte0
    byte_of = {3: std_bytes[0], 2: std_bytes[1], 1: std_bytes[2], 0: std_bytes[3]}
    return bytes(byte_of[int(i)] for i in byte_order.split("-"))


def ai_block(register: int) -> bytes:
    if register in SIMULATED_CHANNELS:
        base_value, jitter, unit = SIMULATED_CHANNELS[register]
        value, status = base_value + jitter * math.sin(time.time()), 0
    else:
        value, status, unit = 0.0, 3, 0
    return encode_float_wire(value) + bytes([0, status, 0, unit])


class DeviceProtocol(Protocol):
    log_name = "Endress+Hauser Liquiline CM44x (dummy, RTU)"

    def __init__(self):
        self.log = Logger(namespace=self.log_name)
        self._buffer = bytearray()

    def dataReceived(self, data):
        self._buffer.extend(data)
        while len(self._buffer) >= 8:                 # FC03-Anfrage ist immer 8 Byte
            if self._buffer[0] != BUS_ADDRESS:
                del self._buffer[0]                   # nicht fuer uns / Rauschen
                continue
            request = bytes(self._buffer[:8]); del self._buffer[:8]
            self.handle_request(request)

    def handle_request(self, request: bytes):
        self.log.info(f"received: {request.hex(' ').upper()}")
        if crc16(request[:-2]) != request[-2:]:
            self.log.warn("CRC falsch - keine Antwort (wie ein echtes Geraet)")
            return
        if ist_stumm(type(self).__module__):
            self.log.warn(f"STUMM-Datei vorhanden - KEINE Antwort auf: {request.hex(' ').upper()}")
            return
        function = request[1]
        start, quantity = int.from_bytes(request[2:4], "big"), int.from_bytes(request[4:6], "big")
        if function != FC_READ_HOLDING_REGISTERS:
            body = bytes([BUS_ADDRESS, function | 0x80, 0x01])
        elif quantity == 0 or quantity % 4 != 0 or quantity > 125:
            body = bytes([BUS_ADDRESS, function | 0x80, 0x02])     # nur ganze AI-Bloecke, max. 125 Register
        else:
            data = b"".join(ai_block(start + 4 * i) for i in range(quantity // 4))   # mehrere Bloecke je Anfrage
            body = bytes([BUS_ADDRESS, function, len(data)]) + data
        reply = body + crc16(body)
        self.transport.write(reply)
        self.log.info(f"answered: {reply.hex(' ').upper()}")
