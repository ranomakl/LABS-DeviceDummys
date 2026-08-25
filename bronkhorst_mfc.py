# Dummy fuer backend/drivers/bronkhorst_mfc.py (Bronkhorst EL-FLOW Prestige FG-201CV,
# FLOW-BUS/ProPar ASCII). Simuliert: Setpoint schreiben (mit echter Statusantwort), Messwert
# lesen und Counter lesen (jeweils mit dem "Echo/Index"-Paar + Wert, siehe Treiber-Kommentar).
# Der Momentanwert folgt dem Setpoint ohne Verzoegerung (keine echte Regeldynamik simuliert),
# der Counter akkumuliert ueber die Zeit proportional zum Setpoint - beides nur zum Testen der
# Backend-Anbindung, nicht als realistisches Prozessmodell gedacht.
#
# GEAENDERT: komplett neu auf Basis von docs/handbuch_bronkhorst.pdf Abschnitte 3.6-3.9
# (Statusmeldung, Lese-Anfrage mit Echo/Index-Paar, Lese-Antwort mit Befehl 02 + Echo-Paar).
# Alle drei Request-Patterns und alle drei Reply-Frames sind jetzt byte-genau gegen die
# Handbuchbeispiele (3.9.1-3.9.4) aufgebaut - siehe Kommentar in bronkhorst_mfc.py (Treiber).

import re
import struct
import time

from base import BaseDummyProtocol


class DeviceProtocol(BaseDummyProtocol):
    delimiter = b"\r\n"
    log_name = "Bronkhorst EL-FLOW Prestige FG-201CV (dummy)"

    def __init__(self):
        super().__init__()
        self.setpoint_raw = 0  # 0-32000 entspricht 0-100 % vom Messbereich
        self.counter = 0.0
        self._last_counter_update = time.time()
        self.replies = {
            # SET_SETPOINT: :LEN NODE 01 010121 WERT(4hex)  ->  Statusmeldung :04 NODE 00 00 05
            r":(?P<len>[0-9A-F]{2})(?P<node>[0-9A-F]{2})010121(?P<value>[0-9A-F]{4})": (self.set_setpoint, ""),
            # READ_MEASURE-Anfrage: :LEN NODE 04 (Echo 0121)(Actual 0120)
            r":(?P<len>[0-9A-F]{2})(?P<node>[0-9A-F]{2})0401210120": (self.read_measure, ""),
            # READ_COUNTER-Anfrage: :LEN NODE 04 (Echo 6841)(Actual 6841)
            r":(?P<len>[0-9A-F]{2})(?P<node>[0-9A-F]{2})0468416841": (self.read_counter, ""),
        }

    @staticmethod
    def _build_reply(node: str, data: str) -> str:
        body = f"{node}{data}"
        length = f"{len(body) // 2:02X}"
        return f":{length}{body}"

    def set_setpoint(self, match: re.Match):
        self.setpoint_raw = int(match.group("value"), 16)
        # echte Statusmeldung: Befehl 00, Status 00 (kein Fehler), Index-Byte (Platzhalter "05",
        # wie im Handbuchbeispiel 3.9.1 - nur relevant, wenn Status != 0)
        return self._build_reply(match.group("node"), "000005")

    def read_measure(self, match: re.Match):
        self._update_counter()
        # Antwort: Befehl 02 + geechotes Prozess/Parameter-Paar (0121, s. Treiber) + Wert
        return self._build_reply(match.group("node"), f"020121{self.setpoint_raw:04X}")

    def read_counter(self, match: re.Match):
        self._update_counter()
        value_hex = struct.pack(">f", self.counter).hex().upper()
        # Antwort: Befehl 02 + geechotes Prozess/Parameter-Paar (6841, s. Treiber) + Wert
        return self._build_reply(match.group("node"), f"026841{value_hex}")

    def _update_counter(self):
        now = time.time()
        elapsed = now - self._last_counter_update
        self._last_counter_update = now
        percent = self.setpoint_raw / 32000 * 100
        self.counter += percent * elapsed  # willkuerliche Simulation, nur zum Testen der Anbindung
