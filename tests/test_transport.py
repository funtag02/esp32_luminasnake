import threading
from unittest.mock import MagicMock, patch

from luminasnake_pc.transport import SerialTransport


def test_serial_control_lines_are_disabled_before_open():
    connection = MagicMock()
    with patch("luminasnake_pc.transport.serial.Serial", return_value=connection) as constructor:
        result = SerialTransport._open_without_reset("COM7")

    constructor.assert_called_once_with(
        port=None,
        baudrate=921_600,
        timeout=0.1,
        write_timeout=0.2,
        dsrdtr=False,
        rtscts=False,
    )
    assert result is connection
    assert connection.dtr is False
    assert connection.rts is False
    assert connection.port == "COM7"
    connection.open.assert_called_once_with()


def test_connect_rejects_incompatible_protocol_with_specific_error():
    connection = MagicMock()
    connection.readline.return_value = (
        b"@LS READY version=1 strips=1 leds=120 max_fps=100\n"
    )
    transport = SerialTransport()

    with patch.object(transport, "_open_without_reset", return_value=connection):
        assert transport.connect("COM7") is False

    assert transport.state.connected is False
    assert transport.state.last_error == (
        "Incompatible ESP protocol 1; desktop expects 2"
    )
    connection.close.assert_called_once_with()


def test_disconnect_does_not_wait_for_in_progress_serial_read():
    read_started = threading.Event()
    allow_read_to_finish = threading.Event()
    close_called = threading.Event()
    connection = MagicMock()

    def readline():
        read_started.set()
        assert allow_read_to_finish.wait(timeout=1)
        return b""

    connection.readline.side_effect = readline
    connection.close.side_effect = close_called.set
    transport = SerialTransport()
    transport.serial = connection
    transport.running = True
    transport.state.connected = True

    reader = threading.Thread(target=transport._read_loop, args=(connection,))
    reader.start()
    assert read_started.wait(timeout=1)

    disconnector = threading.Thread(target=transport.disconnect)
    disconnector.start()
    disconnector.join(timeout=1)
    assert not disconnector.is_alive()
    assert close_called.is_set()
    assert reader.is_alive()

    allow_read_to_finish.set()
    reader.join(timeout=1)

    assert not reader.is_alive()
    assert close_called.is_set()


def test_read_loop_handles_pyserial_windows_close_race():
    connection = MagicMock()
    connection.readline.side_effect = TypeError(
        "byref() argument must be a ctypes instance, not 'NoneType'"
    )
    transport = SerialTransport()
    transport.serial = connection
    transport.running = True
    transport.state.connected = True
    reader = threading.Thread(target=transport._read_loop, args=(connection,))
    with patch("threading.excepthook") as thread_exception:
        reader.start()
        reader.join(timeout=1)

    assert not reader.is_alive()
    thread_exception.assert_not_called()
    assert transport.state.connected is False
    assert "byref()" in transport.state.last_error
    connection.close.assert_called_once_with()