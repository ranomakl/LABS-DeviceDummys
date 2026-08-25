# Dummy fuer backend/drivers/endress_hauser_liquiline.py (Endress+Hauser Liquiline CM442/CM448,
# Modbus ASCII, siehe Treiberkommentar dort fuer die RTU/ASCII-Entscheidung und die
# Frame-/Registerverifikation gegen docs/handbuch_liquiline_modbus.pdf).
#
# Modbus-ASCII-Frames sind text-delimitiert (":" ... CRLF) und passen deshalb - anders als
# longer_wt600.py - direkt in das bestehende BaseDummyProtocol (LineOnlyReceiver).
#
# Simuliert: FC03 Read Holding Register fuer einen vollstaendigen AI-Geraetevariablen-Block
# (Value/Status/Unit, 4 Register = 8 Byte, s. Treiberkommentar). Liefert fuer die drei in
# config.yml vorgesehenen Register (0=pH, 4=Leitfaehigkeit, 8=Temperatur) plausible, leicht
# schwankende Messwerte; fuer jedes andere angefragte Register wird status=2 (Bad) mit Wert 0.0
# geliefert (simuliert "kein Sensor auf diesem AI-Slot konfiguriert"). Kein Schreibzugriff, da der
# Treiber reiner Lesezugriff ist.

import math
import re
import struct
import time

from base import BaseDummyProtocol


def _lrc(data: bytes) -> int:
    return (-sum(data)) & 0xFF


def _encode_float_wire(value: float, byte_order: str = "1-0-3-2") -> bytes:
    std_bytes = struct.pack(">f", value)  # Byte3,Byte2,Byte1,Byte0
    byte_of = {3: std_bytes[0], 2: std_bytes[1], 1: std_bytes[2], 0: std_bytes[3]}
    order = [int(x) for x in byte_order.split("-")]
    return bytes(byte_of[i] for i in order)


# register -> (Basiswert, Schwankung, Unit-Code) - Register wie im mitgelieferten config.yml-Beispiel
SIMULATED_CHANNELS = {
    0: (7.00, 0.05, 53),    # pH, Unit-Code 53 = "pH" (Handbuch Abschnitt 7.1)
    4: (520.0, 5.0, 71),    # Leitfaehigkeit, Unit-Code 71 = "uS/cm"
    8: (23.5, 0.2, 89),     # Temperatur, Unit-Code 89 = "degC"
}


class DeviceProtocol(BaseDummyProtocol):
    delimiter = b"\r\n"
    log_name = "Endress+Hauser Liquiline CM44x (dummy)"

    def __init__(self):
        super().__init__()
        self.bus_address = 1  # muss zur config.yml-`bus_address` des Treibers passen
        self.replies = {
            r":(?P<address>[0-9A-Fa-f]{2})03(?P<register>[0-9A-Fa-f]{4})0004(?P<lrc>[0-9A-Fa-f]{2})":
                (self.read_ai_block, ""),
        }

    def read_ai_block(self, match: re.Match) -> str:
        register = int(match.group("register"), 16)
        base_value, jitter, unit = SIMULATED_CHANNELS.get(register, (0.0, 0.0, 0))
        status = 0 if register in SIMULATED_CHANNELS else 2  # 2 = Bad ("nicht konfiguriert")
        value = base_value + jitter * math.sin(time.time())

        data = _encode_float_wire(value) + bytes([0, status, 0, unit])
        body = bytes([self.bus_address, 0x03, len(data)]) + data
        return f":{body.hex().upper()}{_lrc(body):02X}"
