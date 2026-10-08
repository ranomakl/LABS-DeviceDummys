import os
import re

from twisted.protocols.basic import LineOnlyReceiver
from twisted.logger import Logger

# STUMM-SCHALTER (08.10.2026, fuer den Test des Fehlerpfads im Backend, s. LABS-Backend/docs/
# test_fehlerpfad_dummys.md): Liegt im Dummy-Verzeichnis eine Datei namens STUMM (Inhalt egal),
# nimmt jeder Dummy Befehle an, ANTWORTET ABER NICHT - wie ein Geraet, das haengt, bei offener
# Verbindung. Datei loeschen -> Dummy antwortet wieder. Funktioniert auch unter Windows (kein
# SIGSTOP noetig). Optional: Datei STUMM_<modulname> (z.B. STUMM_bronkhorst_mfc) stummt nur
# diesen einen Dummy.
_HIER = os.path.dirname(os.path.abspath(__file__))


def ist_stumm(modulname: str) -> bool:
    return (os.path.exists(os.path.join(_HIER, "STUMM"))
            or os.path.exists(os.path.join(_HIER, f"STUMM_{modulname}")))


class BaseDummyProtocol(LineOnlyReceiver):
    replies = {}
    non_delimited_replies = {}
    delimiter = b"\r"
    log_name = "don't use me directly"

    def __init__(self, *args, **kwargs):
        self.log = Logger(namespace=self.log_name)
        super().__init__(*args, **kwargs)

    def lineReceived(self, line):
        self.log.info(f"received: {line}")
        if ist_stumm(type(self).__module__):
            self.log.warn(f"STUMM-Datei vorhanden - KEINE Antwort auf: {line}")
            return

        def get_match(data, dictionary):
            for key, value in dictionary.items():
                match = re.match(key, data)
                if match:
                    return match, value
            return None, None

        line = line.decode()
        send_function = self.sendLine
        match, reply = get_match(line, self.replies)
        if match is None and reply is None:
            match, reply = get_match(line, self.non_delimited_replies)
            send_function = self.transport.write
        if match is None and reply is None:
            return
        if not isinstance(reply, str):
            f, reply = reply
            reply = f(match) or reply
        try:
            send_function(reply.encode())
            self.log.info(f"answered: {reply}")
        except AttributeError:
            pass
