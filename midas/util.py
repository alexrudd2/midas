"""Base functionality for modbus communication.

Distributed under the GNU General Public License v2
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Literal, TypeVar, overload

from pymodbus.client import AsyncModbusTcpClient

if TYPE_CHECKING:
    try:  # 3.8.x
        from pymodbus.pdu.register_message import (
            ReadHoldingRegistersResponse,
            WriteMultipleRegistersResponse,
        )
    except ImportError:  # <= 3.7.x
        ReadHoldingRegistersResponse = TypeVar('ReadHoldingRegistersResponse')  # type: ignore
        WriteMultipleRegistersResponse = TypeVar('WriteMultipleRegistersResponse')  # type: ignore

import pymodbus.exceptions


class AsyncioModbusClient:
    """A generic asyncio client.

    This expands upon the pymodbus AsyncModbusTcpClient by
    including standard timeouts, async context manager, and queued requests.
    """

    def __init__(self, address: str, timeout: float = 1) -> None:
        """Set up communication parameters."""
        self.ip = address
        self.port = 5020 if address == '127.0.0.1' else 502  # pymodbus simulator is 127.0.0.1:5020
        self.timeout = timeout
        self.pymodbus30plus = int(pymodbus.__version__[0]) == 3
        self.pymodbus32plus = self.pymodbus30plus and int(pymodbus.__version__[2]) >= 2
        self.pymodbus33plus = self.pymodbus30plus and int(pymodbus.__version__[2]) >= 3
        self.pymodbus35plus = self.pymodbus30plus and int(pymodbus.__version__[2]) >= 5
        self.client = AsyncModbusTcpClient(address, timeout=timeout, port=self.port)
        self.lock = asyncio.Lock()
        self.connectTask = asyncio.create_task(self._connect())

    async def __aenter__(self) -> Any:
        """Asynchronously connect with the context manager."""
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Provide exit to the context manager."""
        await self._close()

    async def _connect(self) -> None:
        """Start asynchronous reconnect loop."""
        async with self.lock:
            try:
                await asyncio.wait_for(self.client.connect(), timeout=self.timeout)
            except Exception as e:
                raise OSError(f"Could not connect to '{self.ip}'.") from e

    async def read_registers(self, address: int, count: int) -> list[int]:
        """Read modbus registers.

        The Modbus protocol doesn't allow responses longer than 250 bytes
        (ie. 125 registers), which this function manages by chunking larger requests.
        """
        registers: list[int] = []
        while count > 124:
            r = await self._request('read_holding_registers', address=address, count=124)
            registers += r.registers
            address, count = address + 124, count - 124
        r = await self._request('read_holding_registers', address=address, count=count)
        registers += r.registers
        return registers

    async def write_registers(self, address: int, values: list | tuple) -> None:
        """Write modbus registers.

        The Modbus protocol doesn't allow requests longer than 250 bytes
        (ie. 125 registers), but a single Midas doesn't have that many.
        """
        await self._request('write_registers', address=address, values=values)

    @overload
    async def _request(self, method: Literal['read_holding_registers'],
                       *args: Any, **kwargs: Any) -> ReadHoldingRegistersResponse:
        ...

    @overload
    async def _request(self, method: Literal['write_registers'],
                       *args: Any, **kwargs: Any) -> WriteMultipleRegistersResponse:
        ...

    async def _request(self, method: Literal['read_holding_registers', 'write_registers'],
                       *args: Any, **kwargs: Any) -> Any:
        """Send a request to the device and awaits a response.

        This mainly ensures that requests are sent serially, as the Modbus
        protocol does not allow simultaneous requests (it'll ignore any
        request sent while it's processing something). The driver handles this
        by assuming there is only one client instance. If other clients
        exist, other logic will have to be added to either prevent or manage
        race conditions.
        """
        await self.connectTask
        async with self.lock:
            try:
                if self.pymodbus32plus:
                    future = getattr(self.client, method)
                else:
                    future = getattr(self.client.protocol, method)  # type: ignore
                return await future(*args, **kwargs)
            except (asyncio.TimeoutError, pymodbus.exceptions.ConnectionException,
                    AttributeError) as e:
                raise TimeoutError("Not connected to Midas.") from e

    async def _close(self) -> None:
        """Close the TCP connection."""
        if self.pymodbus33plus:
            self.client.close()  # 3.3.x
        else:
            await self.client.close()  # type: ignore  # 3.0.x - 3.2.x
