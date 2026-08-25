# Dummy fuer backend/drivers/inficon_microgc_fusion.py (Inficon Micro GC Fusion). Anders als alle
# anderen Dummys hier: simuliert einen HTTP-Server (JSON-Antworten), keinen seriellen Port - das
# Geraet spricht REST/HTTP, keine Frames. Siehe Treiberkommentar in inficon_microgc_fusion.py fuer
# die verifizierten Endpunkte (aus dem Quellcode des MicroGCFusionAPI-Referenzmoduls, nicht aus
# docs/microgc_api.md selbst - das dokumentiert nur die Python-Methodennamen).
#
# main.py erkennt dieses Modul daran, dass es (anders als die anderen Dummys) ein Modul-Attribut
# `Factory` bereitstellt (eine fertige twisted.web.server.Site statt einer Protocol-Klasse) und
# baut den Listener entsprechend als HTTP-Server statt als rohen TCP-Server auf.

import json
import time
import uuid

from twisted.internet import reactor
from twisted.logger import Logger
from twisted.web.resource import Resource
from twisted.web.server import Site

log = Logger(namespace="Inficon Micro GC Fusion (dummy)")

READY = "public:ready"
BAKEOUT = "public:bakeout"
METHOD_RUNNING = "public:method-running"

# Die Dummy-Vorgaenge (BakeOut/Lauf) dauern zum Testen bewusst nur ein paar Sekunden, unabhaengig
# von der angefragten BakeOut-Dauer (die trotzdem entgegengenommen/geloggt wird) - ein echtes
# Geraet braucht dafuer Minuten bis Stunden, s. Treiberkommentar.
SIMULATED_DURATION_S = 3.0


def _fake_run_data(run_id: str) -> dict:
    """Minimalbeispiel im Umfang von Fusion.data.compoundResults() im Referenzquellcode (s.
    Treiberkommentar in inficon_microgc_fusion.py) - fuer run_data_to_csv() ausreichend, kein
    vollstaendiges, echtes Laufdatenfile (das Handbuch/die Doku legt dessen Struktur nicht offen)."""
    return {
        "$id": run_id,
        "runTimeStamp": int(time.time() * 1000),
        "methodName": "DemoMethod",
        "annotations": {"name": "Demo Run", "tags": []},
        "detectors": {
            "TCD1": {
                "analysis": {
                    "peaks": [
                        {"label": "Methane", "height": 12345.6, "area": 98765.4, "top": 0.42,
                         "concentration": 89.5, "normalizedConcentration": 90.1},
                        {"label": "Ethane", "height": 543.2, "area": 2109.8, "top": 0.91,
                         "concentration": 1.2, "normalizedConcentration": 1.3},
                    ]
                }
            }
        },
    }


class FusionResource(Resource):
    isLeaf = True

    def __init__(self):
        super().__init__()
        self.system_status = READY
        self.sequence_status = "public:sequence-not-loaded"
        self.loaded_method = None
        self.last_run_id = None
        self.runs = {}

    def _json(self, request, payload) -> bytes:
        request.setHeader(b"Content-Type", b"application/json")
        return json.dumps(payload).encode("utf-8")

    def _start_timed_operation(self, active_status: str):
        self.system_status = active_status

        def finish():
            self.system_status = READY
            run_id = str(uuid.uuid4())
            self.last_run_id = run_id
            self.runs[run_id] = _fake_run_data(run_id)
        reactor.callLater(SIMULATED_DURATION_S, finish)

    def render_GET(self, request):
        path = request.path.decode("utf-8")
        args = {key.decode(): [v.decode() for v in values] for key, values in request.args.items()}
        log.info(f"received: GET {path}?{args}")

        if path == "/":
            request.setResponseCode(200)
            return b""

        if path == "/v1/scm/sessions/system-manager/publicConfiguration":
            return self._json(request, [self.sequence_status, self.system_status])

        if path == "/v1/scm/sessions/system-manager!cmd.bakeout":
            duration = args.get("duration", ["?"])[0]
            log.info(f"BakeOut requested (duration={duration}), simulating "
                     f"{SIMULATED_DURATION_S}s regardless")
            self._start_timed_operation(BAKEOUT)
            request.setResponseCode(200)
            return b""

        if path == "/v1/scm/sessions/system-manager!cmd.loadMethod":
            method_location = args.get("methodLocation", [""])[0]
            self.loaded_method = method_location.rsplit("/", 1)[-1]
            log.info(f"Loaded method: {self.loaded_method}")
            request.setResponseCode(200)
            return b""

        if path == "/v1/scm/sessions/system-manager!cmd.run":
            log.info(f"Run requested (runWhenReady={args.get('runWhenReady')}), "
                     f"method={self.loaded_method!r}")
            self.sequence_status = "public:sequence-loaded"
            self._start_timed_operation(METHOD_RUNNING)
            request.setResponseCode(200)
            return b""

        if path == "/v1/lastRun":
            if self.last_run_id is None:
                request.setResponseCode(404)
                return self._json(request, {"error": "no run available yet"})
            return self._json(request, {"dataLocation": self.last_run_id})

        if path.startswith("/runData/"):
            run_id = path[len("/runData/"):]
            try:
                return self._json(request, self.runs[run_id])
            except KeyError:
                request.setResponseCode(404)
                return self._json(request, {"error": f"unknown run id {run_id}"})

        request.setResponseCode(404)
        return self._json(request, {"error": f"unknown path {path}"})


# main.py erkennt dieses Attribut (statt DeviceProtocol) und baut einen HTTP- statt TCP-Server.
Factory = Site(FusionResource())
