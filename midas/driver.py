"""
A Python driver for Honeywell's Midas gas detector, using TCP/IP modbus.

Distributed under the GNU General Public License v2
"""
import csv
import os
import struct
from typing import Any

from midas.util import AsyncioModbusClient

root = os.path.normpath(os.path.dirname(__file__))
with open(os.path.join(root, 'faults.csv')) as in_file:
    reader = csv.reader(in_file)
    _ = next(reader)
    faults = {row[0]: {'description': row[1], 'condition': row[2],
                       'recovery': row[3]} for row in reader}

options = {
    'alarm level': [
        'none',
        'low',
        'high',
    ],
    'concentration unit': [
        'ppm',
        'ppb',
        '% volume',
        '% LEL',
        'mA',
    ],
    'monitor state': [
        'Warmup',
        'Monitoring',
        'Monitoring with alarms inhibited',
        'Monitoring with alarms and faults inhibited',
        'Monitoring every response inhibited',
        'Alarm or fault simulation',
        'Bump test mode',
        '4-20 mA loop calibration mode',
        'Non-analog calibration mode',
    ],
    'fault status': [
        'No fault',
        'Maintenance fault',
        'Instrument fault',
        'Maintenance and instrument faults',
    ],
}


class GasDetector(AsyncioModbusClient):
    """Python driver for Honeywell Midas Gas Detectors.

    This driver handles asynchronous Modbus TCP/IP and Midas parsing,
    returning a human-readable dictionary. In particular, this loads fault
    and boolean information specified in the manual and looks up codes so
    you don't have to.
    """

    async def get(self) -> dict[str, Any]:
        """Get current state from the Midas gas detector."""
        return self._parse(await self.read_registers(0, 16))

    async def reset_alarms_and_faults(self) -> None:
        """Reset all alarms and faults."""
        return await self.write_registers(20, [0x015E, 0x3626])

    async def inhibit_alarms(self) -> None:
        """Inhibit alarms from triggering."""
        return await self.write_registers(20, [0x025E, 0x3626])

    async def inhibit_alarms_and_faults(self) -> None:
        """Inhibit alarms and faults from triggering."""
        return await self.write_registers(20, [0x035E, 0x3626])

    async def remove_inhibit(self) -> None:
        """Cancel the inhibit state."""
        return await self.write_registers(20, [0x055E, 0x3626])

    def _unpack_32bit_float(self, registers: list[int]) -> float:
        """Unpack a float from two 16-bit registers."""
        packed = struct.pack('<HH', registers[0], registers[1])
        return struct.unpack('<f', packed)[0]

    def _parse(self, registers: list[int]) -> dict[str, Any]:
        """Parse the response, returning a dictionary."""
        result: dict[str, Any] = {'ip': self.ip, 'connected': True}
        # Register 40001 is a collection of alarm status signals
        # Extract all 16 bits (LSB first)
        reg_40001 = [(registers[0] >> i) & 1 for i in range(16)]
        # Bits 0-3 map to the monitor state
        monitor_integer = sum(1 << i for i, b in enumerate(reg_40001[:4]) if b)
        result['state'] = options['monitor state'][monitor_integer]
        # Bits 4-5 map to fault status
        fault_integer = sum(1 << i for i, b in enumerate(reg_40001[4:6]) if b)
        result['fault'] = {'status': options['fault status'][fault_integer]}
        # Bits 6 and 7 tell if low and high alarms are active
        low, high = reg_40001[6:8]
        result['alarm'] = options['alarm level'][low + high]
        # Bits 8-10 tell if internal sensor relays 1-3 are energized. Skipping.
        # Bit 11 is a heartbeat bit that toggles every two seconds. Skipping.
        # Bit 12 tells if relays are under modbus control. Skipping.
        # Remaining bits are empty. Skipping.
        # Register 40002 has a gas ID and a sensor cartridge ID. Skipping.
        # Registers 40003-40004 are the gas concentration as a float
        result['concentration'] = self._unpack_32bit_float(registers[2:4])
        # Register 40005 is the concentration as an int. Skipping.
        # Register 40006 is the number of the most important fault.
        fault_number = registers[5]
        if fault_number != 0:
            code = ('m' if fault_number < 30 else 'F') + str(fault_number)
            result['fault']['code'] = code
            result['fault'].update(faults[code])
        # Register 40007 holds the concentration unit in the second byte
        # Instead of being an int, it's the position of the up bit
        reg_40007 = [(registers[6] >> i) & 1 for i in range(8, 16)]  # only high byte
        unit_bit = reg_40007.index(1)
        result['units'] = options['concentration unit'][unit_bit]
        # Register 40008 holds the sensor temperature in Celsius
        result['temperature'] = registers[7]
        # Register 40009 holds number of hours remaining in cell life
        result['life'] = registers[8] / 24.0
        # Register 40010 holds the number of heartbeats (16 LSB). Skipping.
        # Register 40011 is the sample flow rate in cc / min
        result['flow'] = registers[10]
        # Register 40012 is blank. Skipping.
        # Registers 40013-40016 are the alarm concentration thresholds
        result['low-alarm threshold'] = round(self._unpack_32bit_float(registers[12:14]), 6)
        result['high-alarm threshold'] = round(self._unpack_32bit_float(registers[14:16]), 6)
        # Despite what the manual says, thresholds are always reported in ppm.
        # Let's fix that to match the concentration units.
        if result['units'] == 'ppb':
            result['concentration'] *= 1000
            result['low-alarm threshold'] *= 1000
            result['high-alarm threshold'] *= 1000
        return result
