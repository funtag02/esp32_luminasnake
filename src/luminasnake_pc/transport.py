from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import replace

import serial
from serial.tools import list_ports

from .models import ConnectionState
from .protocol import VERSION, frame_packet, hello_packet, ping_packet

READY = re.compile(r"@LS READY version=(\d+) strips=(\d+) leds=(\d+) max_fps=(\d+)")
STATUS = re.compile(
    r"@LS STATUS connected=(\d+) accepted=(\d+) rejected=(\d+) "
    r"late=(\d+) dropped=(\d+) sequence=(\d+)"
)


class SerialTransport:
    def __init__(self, on_state: Callable[[ConnectionState], None] | None = None) -> None:
        self.state = ConnectionState()
        self.on_state = on_state or (lambda state: None)
        self.serial: serial.Serial | None = None
        self.sequence = 0
        self.lock = threading.RLock()
        self.reader: threading.Thread | None = None
        self.running = False

    @staticmethod
    def ports() -> list[str]:
        return [port.device for port in list_ports.comports()]

    @staticmethod
    def _open_without_reset(port: str) -> serial.Serial:
        connection = serial.Serial(
            port=None,
            baudrate=921_600,
            timeout=0.1,
            write_timeout=0.2,
            dsrdtr=False,
            rtscts=False,
        )
        connection.dtr = False
        connection.rts = False
        connection.port = port
        connection.open()
        return connection

    def connect(self, requested_port: str = "auto") -> bool:
        candidates = self.ports() if requested_port == "auto" else [requested_port]
        last_error = "No compatible LuminaSnake ESP found"
        for port in candidates:
            try:
                connection = self._open_without_reset(port)
                connection.reset_input_buffer()
                deadline = time.monotonic() + 4.0
                next_hello = 0.0
                while time.monotonic() < deadline:
                    if time.monotonic() >= next_hello:
                        connection.write(hello_packet())
                        next_hello = time.monotonic() + 0.2
                    line = connection.readline().decode("utf-8", errors="ignore")
                    match = READY.search(line)
                    if match:
                        version, strips, leds, max_fps = map(int, match.groups())
                        if version != VERSION:
                            last_error = (
                                f"Incompatible ESP protocol {version}; desktop expects {VERSION}"
                            )
                            break
                        with self.lock:
                            self.serial = connection
                            self.state = ConnectionState(
                                True, port, version, strips, leds, max_fps
                            )
                            self.running = True
                        self.reader = threading.Thread(
                            target=self._read_loop,
                            args=(connection,),
                            daemon=True,
                        )
                        self.reader.start()
                        self._notify()
                        return True
                connection.close()
            except (OSError, serial.SerialException):
                continue
        with self.lock:
            self.state.connected = False
            self.state.last_error = last_error
        self._notify()
        return False

    def disconnect(self) -> None:
        with self.lock:
            self.running = False
            connection = self.serial
            self.serial = None
            self.state.connected = False
        if connection:
            connection.close()
        self._notify()

    def send_frame(self, frame, delay_us: int) -> None:
        self._write(frame_packet(self._next_sequence(), delay_us, frame))
        with self.lock:
            self.state.sent_frames += 1

    def _next_sequence(self) -> int:
        with self.lock:
            self.sequence = (self.sequence + 1) & 0xFFFFFFFF
            return self.sequence

    def _write(self, packet: bytes) -> None:
        try:
            with self.lock:
                if not self.serial or not self.state.connected:
                    raise ConnectionError("ESP is not connected")
                self.serial.write(packet)
        except (OSError, serial.SerialException, ConnectionError) as error:
            with self.lock:
                self.state.errors += 1
                self.state.last_error = str(error)
            self.disconnect()
            raise ConnectionError(str(error)) from error

    def _read_line(self, connection: serial.Serial) -> bytes | None:
        with self.lock:
            if not self.running or self.serial is not connection:
                return None
        # readline has a timeout; do not hold the state lock while waiting so disconnect can proceed.
        return connection.readline()

    def _read_loop(self, connection: serial.Serial) -> None:
        last_ping = time.monotonic()
        while True:
            try:
                raw_line = self._read_line(connection)
                if raw_line is None:
                    return
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if line:
                    match = READY.search(line)
                    if match:
                        with self.lock:
                            self.state.protocol_version, self.state.strips, self.state.leds_per_strip, self.state.negotiated_max_fps = map(int, match.groups())
                    status = STATUS.search(line)
                    if status:
                        connected, accepted, rejected, late, dropped, _ = map(int, status.groups())
                        with self.lock:
                            self.state.connected = bool(connected)
                            self.state.accepted_frames = accepted
                            self.state.rejected_packets = rejected
                            self.state.late_frames = late
                            self.state.queue_drops = dropped
                        self._notify()
                if time.monotonic() - last_ping >= 0.25:
                    self._write(ping_packet(self._next_sequence()))
                    last_ping = time.monotonic()
            except (OSError, serial.SerialException, ConnectionError, TypeError) as error:
                with self.lock:
                    if self.serial is not connection:
                        return
                    self.state.last_error = str(error)
                self.disconnect()
                return

    def snapshot(self) -> ConnectionState:
        with self.lock:
            return replace(self.state)

    def _notify(self) -> None:
        self.on_state(self.snapshot())
