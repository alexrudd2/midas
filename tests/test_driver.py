"""Test the driver correctly responds with correct data."""

import asyncio
import struct

import pytest

from midas import GasDetector, command_line

try:
    from pymodbus.server import ModbusTcpServer
except ImportError:  # PyModbus 3.0.x
    from pymodbus.server.async_io import (  # type: ignore[import-not-found, no-redef]
        ModbusTcpServer,
    )

def create_context():  # noqa: C901
    """Create a datastore compatible with the installed pymodbus version."""
    INITIAL_REGISTERS = [
        0b0000000000000001,  # status bits - monitoring, no faults
        0,                   # 40002 - gas id / cartridge id (skipped)
                             # 40003-4 float concentration
        *struct.unpack('<HH',struct.pack('<f', 0.0)),
        0,                   # 40005 - int concentration (skipped)
        0,                   # 40006 - most important fault (none)
        0b0000000100000000,  # 40007 - unit bit position = 8 (ppb)
        30,                  # 40008 - temperature = 30°C
        13346,               # 40009 - life hours remaining = 556.083 days
        0,                   # 40010 - heartbeat counter (skipped)
        482,                 # 40011 - flow rate = cc/min
        0,                   # 40012 - reserved
                             # 40013-4 float low alarm threshold
        *struct.unpack('<HH', struct.pack('<f', 5.0)),
                             # 40015-6 float high alarm threshold
        *struct.unpack('<HH', struct.pack('<f', 8.0)),
        0,                   # 40017 - alarm status
        0,                   # 40018 - fault bits
        0, 0,                # 40019-20 - concentration high scale (skipped)
        0, 0,                # 40021-22 - user command registers
    ]
    try:  # 3.13 +
        from pymodbus.simulator import DataType, SimData, SimDevice

        async def handle_action(function_code, _start_address, address, _count, current_registers,
                                set_values):
            """Intercept simulator writes that change the monitor state."""
            if function_code == 16 and address == 20:
                if set_values == [0x025E, 0x3626]:    # inhibit alarms
                    current_registers[0] = 0b00000010
                elif set_values == [0x035E, 0x3626]:  # inhibit alarms and faults
                    current_registers[0] = 0b00000011
                elif set_values == [0x055E, 0x3626]:  # uninhibit
                    current_registers[0] = 0b00000001

        return SimDevice(
            id=1,
            simdata=(
                [SimData(address=0, values=False, datatype=DataType.BITS)],
                [SimData(address=0, values=False, datatype=DataType.BITS)],
                [SimData(address=0, values=INITIAL_REGISTERS, datatype=DataType.REGISTERS)],
                [SimData(address=0, values=0, datatype=DataType.REGISTERS)],
            ),
            action=handle_action,
        )
    except (ImportError, TypeError): # 3.0 - 3.12
        from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext

        class InterceptingDataBlock(ModbusSequentialDataBlock):
            def setValues(self, address, values):
                if address == 21 and values == [0x025E, 0x3626]:    # inhibit alarms
                    self.values[0] = 0b00000010
                elif address == 21 and values == [0x035E, 0x3626]:  # inhibit alarms and faults
                    self.values[0] = 0b00000011
                elif address == 21 and values == [0x055E, 0x3626]:  # uninhibit
                    self.values[0] = 0b00000001
                else:
                    super().setValues(address, values)  # pyright: ignore[reportAttributeAccessIssue]

        registers = InterceptingDataBlock(1, INITIAL_REGISTERS)

        try:
            from pymodbus.datastore import ModbusDeviceContext  # 3.10 - 3.12
        except ImportError:
            from pymodbus.datastore import ModbusSlaveContext as ModbusDeviceContext  # < 3.10
        device = ModbusDeviceContext(hr=registers)
        return ModbusServerContext(device, single=True)


@pytest.fixture(scope="session", autouse=True)
async def _sim():
    """Start a Modbus server and datastore."""
    server = ModbusTcpServer(
        context=create_context(),
        address=("127.0.0.1", 5020),
    )

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

    await midas_driver.inhibit_alarms_and_faults()
    state = await midas_driver.get()
    assert state == {**expected_data, "state": "Monitoring with alarms and faults inhibited"}
    await midas_driver.remove_inhibit()
    state = await midas_driver.get()
    assert state == expected_data
