# Dummy fuer backend/drivers/inficon_microgc_fusion.py (Inficon Micro GC Fusion). Anders als alle
# anderen Dummys hier: simuliert einen HTTP-Server (JSON-Antworten), keinen seriellen Port - das
# Geraet spricht REST/HTTP, keine Frames. Siehe Treiberkommentar in inficon_microgc_fusion.py fuer
# die verifizierten Endpunkte.
#
# main.py erkennt dieses Modul daran, dass es (anders als die anderen Dummys) ein Modul-Attribut
# `Factory` bereitstellt (eine fertige twisted.web.server.Site statt einer Protocol-Klasse) und
# baut den Listener entsprechend als HTTP-Server statt als rohen TCP-Server auf.
#
# 13.10.2026 erweitert fuer den GC-Messplan im Experiment (run_schedule_named):
#   - POST cmd.run mit JSON-Koerper {"runWhenReady": true, "annotations": {"name", "tags"}} wird
#     angenommen; Name/Tags landen in den Laufdaten (wie am echten Geraet, 08.10.2026).
#   - Statusfolge wie am Geraet: loadMethod -> public:loading-method (kurz) -> public:ready;
#     run -> public:preparing -> public:method-running -> public:ready.
#   - /v1/lastRun liefert {"dataLocation": "/runData/<uuid>"} (mit Prefix, wie das Geraet).
#   - Laufdaten mit den echten Detektor-/Peaknamen (moduleA/B/C:tcd, H2, O2, N2, CO2, n Hexane, ...),
#     Werte aendern sich von Lauf zu Lauf, damit im Monitoring Kurven entstehen.
#   - Ein Lauf waehrend eines laufenden Laufs wird (runWhenReady) hinten angestellt.
#   Dauern per Umgebungsvariable: MICROGC_DUMMY_RUN_S (Standard 6), MICROGC_DUMMY_LOAD_S (Standard 1.5).

import json
import os
import time
import uuid

from twisted.internet import reactor
from twisted.logger import Logger
from twisted.web.resource import Resource
from twisted.web.server import Site

log = Logger(namespace="Inficon Micro GC Fusion (dummy)")

READY = "public:ready"
STANDBY = "public:standby"
BAKEOUT = "public:bakeout"
LOADING = "public:loading-method"
PREPARING = "public:preparing"
METHOD_RUNNING = "public:method-running"

RUN_S = float(os.environ.get("MICROGC_DUMMY_RUN_S", "6"))
LOAD_S = float(os.environ.get("MICROGC_DUMMY_LOAD_S", "1.5"))

# Peaks je Detektor, wie am echten Geraet (Methode microGC_Standard_Method_calibrated_0726, 13.10.2026).
PEAKS = {
    "moduleA:tcd": ["H2", "O2", "N2", "CH4", "CO"],
    "moduleB:tcd": ["CO2", "Ethylene", "Acetylene", "Ethane", "Propylene", "Propane"],
    "moduleC:tcd": ["iso Buten", "1 Butene", "n Butane", "1,3 Butadien", "trans + cis 2 Buten",
                    "iso Pentan", "1 Penten", "n Pentan", "n Hexane", "n Heptane"],
}


def _concentration(label: str, index: int) -> float:
    """Plausible, von Lauf zu Lauf steigende Werte (Index = Nummer des Laufs seit Start des Dummys)."""
    base = {"H2": 1.0, "O2": 20.0, "N2": 76.0, "CO2": 0.3, "Ethane": 0.8, "Ethylene": 0.01,
            "n Pentan": 0.05, "1 Penten": 0.02, "n Hexane": 0.1, "n Heptane": 0.03}
    slope = {"H2": 0.5, "CO2": 0.1, "n Hexane": 0.05, "n Heptane": 0.01, "O2": -0.4, "N2": -0.3}
    return max(0.0, base.get(label, 0.0) + slope.get(label, 0.0) * index)


def _fake_run_data(run_id: str, method: str, annotations: dict, index: int) -> dict:
    """Laufdaten im Umfang der Felder, die der Treiber liest (run_data_to_csv, concentrations_from_run_data)."""
    total = 0.0
    detectors = {}
    for detector, labels in PEAKS.items():
        peaks = []
        for n, label in enumerate(labels):
            conc = _concentration(label, index)
            total += conc
            peaks.append({"label": label, "height": 1000.0 * conc + 1, "area": 5000.0 * conc + 1,
                          "top": 0.3 + 0.2 * n, "concentration": conc, "normalizedConcentration": conc})
        peaks.append({"height": 3.0, "area": 9.0, "top": 2.5})   # unbenannter Peak, muss ignoriert werden
        detectors[detector] = {"analysis": {"peaks": peaks}}
    for detector_data in detectors.values():
        for peak in detector_data["analysis"]["peaks"]:
            if "label" in peak and total:
                peak["normalizedConcentration"] = 100.0 * peak["concentration"] / total
    return {
        "$id": run_id,
        "$displayName": method,
        "runTimeStamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        "methodName": method,
        "methodLocation": f"/v1/methods/userMethods/{method}",
        "annotations": annotations,
        "frontInletTotalConcentration": total,
        "detectors": detectors,
    }


class FusionResource(Resource):
    isLeaf = True

    def __init__(self):
        super().__init__()
        self.system_status = STANDBY
        self.sequence_status = "public:sequence-not-loaded"
        self.loaded_method = "DemoMethod"
        self.runs = {}
        self.run_index = 0
        self.pending_runs = []      # runWhenReady: Laeufe, die auf das Ende des aktuellen warten
        self.last_run_id = self._store_run({"name": "Dummy-Startlauf", "tags": []})

    # -- Hilfsfunktionen --

    def _json(self, request, payload) -> bytes:
        request.setHeader(b"Content-Type", b"application/json")
        return json.dumps(payload).encode("utf-8")

    def _store_run(self, annotations: dict) -> str:
        run_id = str(uuid.uuid4())
        self.runs[run_id] = _fake_run_data(run_id, self.loaded_method, annotations, self.run_index)
        self.run_index += 1
        return run_id

    def _busy(self) -> bool:
        return self.system_status not in (READY, STANDBY)

    def _start_run(self, annotations: dict):
        log.info("run started: annotations={a}, method={m!r}, {s} s", a=annotations, m=self.loaded_method, s=RUN_S)
        self.sequence_status = "public:sequence-loaded"
        self.system_status = PREPARING
        reactor.callLater(RUN_S / 3.0, self._set_status, METHOD_RUNNING)
        reactor.callLater(RUN_S, self._finish_run, annotations)

    def _set_status(self, status):
        self.system_status = status

    def _finish_run(self, annotations: dict):
        self.last_run_id = self._store_run(annotations)
        self.system_status = READY
        log.info("run finished: {a} -> {r}", a=annotations, r=self.last_run_id)
        if self.pending_runs:
            self._start_run(self.pending_runs.pop(0))

    def _request_run(self, annotations: dict):
        if self._busy():
            log.info("run queued (runWhenReady) behind current {s}: {a}", s=self.system_status, a=annotations)
            self.pending_runs.append(annotations)
        else:
            self._start_run(annotations)

    def _start_bakeout(self):
        self.system_status = BAKEOUT
        reactor.callLater(RUN_S, self._set_status, READY)

    def _load_method(self, method_location: str):
        self.loaded_method = method_location.rsplit("/", 1)[-1]
        log.info("loading method {m!r} ({s} s)", m=self.loaded_method, s=LOAD_S)
        self.system_status = LOADING
        reactor.callLater(LOAD_S, self._set_status, READY)

    # -- HTTP --

    def render_POST(self, request):
        path = request.path.decode("utf-8")
        raw = request.content.read()
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            body = {"_invalid": raw[:100].decode("utf-8", "replace")}
        log.info("received: POST {p} {b}", p=path, b=body)
        if path == "/v1/scm/sessions/system-manager!cmd.run":
            annotations = body.get("annotations") or {"name": "", "tags": []}
            self._request_run({"name": str(annotations.get("name", "")), "tags": list(annotations.get("tags") or [])})
            return self._json(request, {"runWhenReady": "true"})
        request.setResponseCode(404)
        return self._json(request, {"error": f"unknown path {path}"})

    def render_GET(self, request):
        path = request.path.decode("utf-8")
        args = {key.decode(): [v.decode() for v in values] for key, values in request.args.items()}
        log.info("received: GET {p} {a}", p=path, a=args)

        if path == "/":
            request.setResponseCode(200)
            return b""

        if path == "/v1/scm/sessions/system-manager/publicConfiguration":
            return self._json(request, [self.sequence_status, self.system_status])

        if path == "/v1/scm/sessions/system-manager!cmd.bakeout":
            log.info("BakeOut requested (duration={d}), simulating {s} s regardless",
                     d=args.get("duration", ["?"])[0], s=RUN_S)
            self._start_bakeout()
            request.setResponseCode(200)
            return b""

        if path == "/v1/scm/sessions/system-manager!cmd.loadMethod":
            self._load_method(args.get("methodLocation", [""])[0])
            return self._json(request, {"$public.currentMethodLocation": args.get("methodLocation", [""])[0]})

        if path == "/v1/scm/sessions/system-manager!cmd.run":
            self._request_run({"name": "", "tags": []})
            return self._json(request, {"runWhenReady": "true"})

        if path == "/v1/lastRun":
            return self._json(request, {"dataLocation": f"/runData/{self.last_run_id}"})

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
