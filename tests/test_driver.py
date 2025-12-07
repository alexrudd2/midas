"""Test the driver correctly responds with correct data."""
import asyncio
import struct

import pytest

from midas import GasDetector, command_line

try:
    from pymodbus.server import ModbusTcpServer  # 3.0.x
except ImportError:
    from pymodbus.server.async_io import (  # type: ignore[import-not-found, no-redef]
        ModbusTcpServer,
    )

@pytest.fixture(scope='session', autouse=True)
async def _sim():
    """Start a modbus server and datastore."""
    from pymodbus.datastore import (
        ModbusSequentialDataBlock,
        ModbusServerContext,
    )
    class InterceptingDataBlock(ModbusSequentialDataBlock):
        """Datablock that intercepts writes."""

        def setValues(self, address, values):
            """Look for user commands to the user commands registers."""
            if address == 21 and values == [0x025E, 0x3626]:  # inhibit alarms
                super().setValues(1, 2)
            elif address == 21 and values == [0x055E, 0x3626]:  # uninhibit
                super().setValues(1, 1)
            else:
                super().setValues(address, values)

    try:  # 3.10
        from pymodbus.datastore import ModbusDeviceContext  # type: ignore
    except ImportError:
        from pymodbus.datastore import ModbusSlaveContext as ModbusDeviceContext  # type: ignore
    store = ModbusDeviceContext(
        di=ModbusSequentialDataBlock(0, [0] * 65536),  # Discrete Inputs
        co=ModbusSequentialDataBlock(0, [0] * 65536),  # Coils
        hr=InterceptingDataBlock(1, [
            0b0000000000000001,  # status bits - monitoring, no faults
            0,                   # 40002 - gas id / cartridge id (skipped)
            *list(               # 40003-4 float concentration
                struct.unpack('<HH',struct.pack('<f', 0.0))),
            0,                   # 40005 - int concentration (skipped)
            0,                   # 40006 - most important fault (none)
            0b0000000100000000,  # 40007 - unit bit position = 8 (ppb)
            30,                  # 40008 - temperature = 30°C
            13346,               # 40009 - life hours remaining = 556.083 days
            0,                   # 40010 - heartbeat counter (skipped)
            482,                 # 40011 - flow rate = cc/min
            0,                   # 40012 - reserved
            *list(               # 40013-4 float low alarm threshold
                struct.unpack('<HH', struct.pack('<f', 5.0))),
            *list(               # 40015-6 float high alarm threshold
                struct.unpack('<HH', struct.pack('<f', 8.0))),
            0,                   # 40017 - alarm status
            0,                   # 40018 - fault bits
            0, 0,                # 40019-20 - concentration high scale (skipped)
            0, 0,                # 40021-22 - user command registers
        ]),  # Holding Registers
        ir=ModbusSequentialDataBlock(0, [0] * 65536),  # Input Registers
    )
    context = ModbusServerContext(store, single=True)
    server = ModbusTcpServer(context=context, address=("127.0.0.1", 5020))
    asyncio.ensure_future(server.serve_forever())  # noqa: RUF006
    await asyncio.sleep(0)
    yield
    await server.shutdown()


@pytest.fixture(scope="session")
async def midas_driver():
    """Confirm the driver correctly initializes."""
    async with GasDetector("127.0.0.1") as g:
        yield g


@pytest.fixture
def expected_data():
    """Return the initial mocked data format."""
    return {
        "ip": "127.0.0.1",
        "connected": True,
        "state": "Monitoring",
        "fault": {"status": "No fault"},
        "alarm": "none",
        "concentration": 0.0,
        "units": "ppm",
        "temperature": 30,
        "life": 556.0833333333334,
        "flow": 482,
        "low-alarm threshold": 5.0,
        "high-alarm threshold": 8.0,
    }

def test_driver_cli(capsys):
    """Confirm the commandline interface works."""
    command_line(["127.0.0.1"])
    captured = capsys.readouterr()
    assert "Monitoring" in captured.out

def test_driver_cli_timeout():
    """Confirm the commandline raises an error on failure to connect."""
    with pytest.raises(TimeoutError):
        command_line(["fakeip"])

@pytest.mark.asyncio(loop_scope='session')
async def test_get(midas_driver, expected_data):
    """Confirm that the driver returns correct values on get() calls."""
    assert expected_data == await midas_driver.get()

@pytest.mark.asyncio(loop_scope='session')
async def test_inhibit_roundtrip(midas_driver, expected_data):
    """Test a roundtrip with the driver using inhibit/uninhibit."""
    await midas_driver.inhibit_alarms()
    state = await midas_driver.get()
    assert state == {**expected_data, "state": "Monitoring with alarms inhibited"}
    await midas_driver.remove_inhibit()
    state = await midas_driver.get()
    assert state == expected_data
