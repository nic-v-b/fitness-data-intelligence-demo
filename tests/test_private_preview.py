import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import create_server, export_files
from fit_reader import RECORD, FitError, crc16, messages
from private_preview import build_private_dataset, normalize_run


def fit_file(payload):
    header = struct.pack("<BBHI4s", 14, 0x20, 2000, len(payload), b".FIT")
    body = header + struct.pack("<H", crc16(header)) + payload
    return body + struct.pack("<H", crc16(body))


def definition(local, global_id, fields, *, big_endian=False, developer=False):
    header = 0x40 | local | (0x20 if developer else 0)
    order = "big" if big_endian else "little"
    standard = b"".join(bytes(field) for field in fields)
    extension = bytes((1, 0, 2, 0)) if developer else b""
    return (bytes((header, 0, big_endian)) + global_id.to_bytes(2, order)
            + bytes((len(fields),)) + standard + extension)


def activity_fit(sport=1, distance_cm=1800):
    activity = definition(0, 0, [(0, 1, 0)]) + b"\x00\x04"
    session = definition(1, 18, [(2, 4, 0x86), (5, 1, 0), (7, 4, 0x86), (9, 4, 0x86)])
    session += b"\x01" + struct.pack("<IBII", 100, sport, 4000, distance_cm)
    fields = [(253, 4, 0x86), (0, 4, 0x85), (1, 4, 0x85), (5, 4, 0x86),
              (3, 1, 0x02), (73, 4, 0x86), (78, 4, 0x86)]
    samples = definition(2, 20, fields, big_endian=True, developer=True)
    for i in range(3):
        samples += b"\x02" + struct.pack(">IiiIBII", 100 + 2 * i, 0, 950 * i,
                                           900 * i, 130 + i, 4500, 2500 + i * 5) + b"\x00\x00"
    return fit_file(activity + session + samples)


class FitReaderTests(unittest.TestCase):
    def test_fit_record_temperature_is_signed_and_respects_the_missing_sentinel(self):
        record = definition(0, RECORD, [(13, 1, 0x01)])
        fixture = fit_file(record + bytes((0, 250, 0, 127, 0, 0)))
        self.assertEqual(list(messages(fixture)), [(RECORD, {13: -6}), (RECORD, {}), (RECORD, {13: 0})])

    def test_checksum_and_compressed_timestamp_rollover(self):
        self.assertEqual(crc16(b"123456789"), 0xBB3D)
        record = definition(0, 20, [(253, 4, 0x86), (3, 1, 0x02)])
        normal = b"\x00" + struct.pack("<IB", 63, 140)
        compressed = bytes((0x81, 0xFF))
        recording = fit_file(record + normal + compressed)
        self.assertEqual(list(messages(recording)), [(RECORD, {253: 63, 3: 140}), (RECORD, {253: 65})])
        with self.assertRaisesRegex(FitError, "checksum"):
            list(messages(recording[:-1] + bytes((recording[-1] ^ 0x01,))))
        with self.assertRaisesRegex(FitError, "size"):
            list(messages(recording[:-1]))
        with self.assertRaisesRegex(FitError, "precedes its definition"):
            list(messages(fit_file(b"\x00")))

    def test_fit_selection_and_recorded_units(self):
        with TemporaryDirectory() as folder:
            private_root = Path(folder).resolve()
            path = private_root / "fixture.fit"
            path.write_bytes(activity_fit())
            with patch("private_preview.PRIVATE_ROOT", private_root):
                dataset = build_private_dataset([path])
                with self.assertRaisesRegex(FitError, "distinct"):
                    build_private_dataset([path, path])
            with self.assertRaisesRegex(FitError, "inside the ignored"):
                build_private_dataset([path])
        run = dataset["activities"][0]
        self.assertEqual(run["name"], "Run A")
        self.assertIsNone(run["shared_segment"])
        self.assertEqual(run["diagnostics"]["session_distance_m"], 18)
        self.assertEqual(run["diagnostics"]["session_elapsed_s"], 4)
        second = run["samples"][1]
        self.assertEqual(second["source"]["elapsed_s"], 2)
        self.assertEqual(second["source"]["speed_mps"], 4.5)
        self.assertAlmostEqual(second["derived"]["speed_kmh"], 16.2)
        self.assertEqual(second["source"]["distance_m"], 9)
        self.assertEqual(second["source"]["elevation_m"], 1)
        self.assertEqual(second["source"]["heart_rate_bpm"], 131)
        self.assertEqual(set(second["source"]), {"elapsed_s", "distance_m", "x_m", "y_m",
                                                "speed_mps", "heart_rate_bpm", "elevation_m"})
        self.assertNotIn("fixture.fit", json.dumps(dataset))

    def test_pauses_and_missing_distance_do_not_fill_gaps(self):
        samples = [{253: 100, 0: 0, 1: 0, 5: 0, 3: 120},
                   {253: 110, 0: 0, 1: 1000, 5: 90000, 3: 130},
                   {253: 160, 3: 145},
                   {253: 170, 0: 0, 1: 2000, 5: 120000, 3: 150},
                   {253: 170, 0: 0, 1: 2000, 5: 120000, 3: 153},
                   {253: 180, 0: 0, 1: 50000, 5: 250000, 3: 160},
                   {253: 190, 0: 0, 1: 100000, 5: 260000, 3: 164}]
        run = normalize_run(({2: 100}, samples, [(110, 1), (160, 0)]), 6_371_008.8, 0)
        records = run["samples"]
        self.assertEqual(len(records), 6)
        self.assertEqual(run["diagnostics"]["non_increasing_timestamps"], 1)
        self.assertEqual(run["diagnostics"]["pause_intervals"], 1)
        self.assertEqual(run["diagnostics"]["gps_jumps"], 1)
        self.assertTrue(records[2]["break_before"])
        self.assertIsNone(records[2]["source"]["x_m"])
        self.assertIsNone(records[2]["source"]["distance_m"])
        self.assertTrue(records[-1]["route_break_before"])
        self.assertFalse(records[-1]["break_before"])
        self.assertIsNone(run["splits"][0]["duration_s"])
        self.assertAlmostEqual(run["summary"]["heart_rate_coverage"], 1 / 3)


class PrivateHTTPTests(unittest.TestCase):
    def test_preview_is_loopback_and_serve_allowlist_excludes_private_files(self):
        dataset = {"metadata": {"dataset_type": "private-fit-preview"}, "activities": []}
        with self.assertRaisesRegex(ValueError, "Only the synthetic"):
            export_files(dataset)
        with create_server(0, dataset) as server:
            self.assertEqual(server.server_address[0], "127.0.0.1")
            thread = Thread(target=server.serve_forever)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with urlopen(f"{base}/api/dataset", timeout=5) as response:
                    self.assertEqual(json.load(response), dataset)
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertEqual(response.headers["Cross-Origin-Resource-Policy"], "same-origin")
                for route in ("/private-data/review/example.fit", "/%2e%2e/private-data/example.fit",
                              "/exports/ridge-traverse.json", "/exports/run-1.csv"):
                    self.assert_status(Request(base + route), 404)
                self.assert_status(Request(base + "/api/dataset", headers={"Host": "example.test"}), 403)
                self.assert_status(Request(base + "/api/dataset", headers={"Sec-Fetch-Site": "cross-site"}), 403)
            finally:
                server.shutdown()
                thread.join()

    def assert_status(self, request, status):
        with self.assertRaises(HTTPError) as rejected:
            urlopen(request, timeout=5)
        with rejected.exception as response:
            self.assertEqual(response.code, status)
