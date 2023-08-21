"""Asynchronous Python client for Lektrico device."""
from __future__ import annotations

import asyncio
import httpx
import socket
import random
from dataclasses import dataclass
from typing import Any
from enum import IntEnum

from .exceptions import DeviceConnectionError, DeviceError
from .models import InfoForCharger, InfoForM2W, Info, Settings

from async_timeout import timeout
from builtins import str


class LBMode(IntEnum):
    """Enumeration of load balancing modes."""
    OFF = 0
    POWER = 1
    HYBRID = 2
    GREEN = 3


@dataclass
class Device:
    """Main class for handling connections with a Lektrico device."""

    _host: str
    
    TYPE_1P7K: str = "1p7k"
    TYPE_3P22K: str = "3p22k"
    TYPE_EM: str = "em"
    TYPE_3EM: str = "3em"
    
    CURRENT_LIMIT_REASON = ["No limit", "Installation current", 
                            "User limit", "Dynamic limit", "Schedule",
                            "EM offline", "EM", "OCPP"]
    
    request_timeout: int = 8
    asyncClient: httpx.AsyncClient | None = None

    _close_session: bool = False

    async def device_info(self, type: str) -> Info:
        """ Get information from Lektrico device.
        Ex for a charger:
        {'charger_state': 'A', 'session_energy': 0.0, 'charging_time': 0, 
        'session_id': 13, 'instant_power': 0.0, 'current': 0.0, 'voltage': 0.0, 
        'temperature': 31.7, 'energy_index': 0.0, dynamic_current=32, 
        headless=False, install_current=32, led_max_brightness=20, 
        total_charged_energy: 0, fw_version='1.23'}
        """
        if type == self.TYPE_1P7K or type == self.TYPE_3P22K:
            data_info = await self._request_get("charger_info.get")
            data_dyn = await self._request_get("app_config.get")
            data = dict(data_info, **data_dyn)
            
            if data["has_active_errors"]:
                data_new = await self._request_get("active_errors.get")
            else:
                data_new = {
                  "state_e_activated": False,
                  "overtemp": False,
                  "critical_temp": False,
                  "overcurrent": False,
                  "meter_fault": False,
                  "undervoltage_error": False,
                  "overvoltage_error": False,
                  "rcd_error": False,
                  "cp_diode_failure": False,
                  "contactor_failure": False,
                }
            data.update(data_new)
            
            # put readable format for state
            data["extended_charger_state"] = self._put_readable_format(data["extended_charger_state"])
            # put current_limit_reason as str
            data["current_limit_reason"] = self.CURRENT_LIMIT_REASON[int(data["current_limit_reason"])]
            return InfoForCharger.from_dict(data)
        elif type == self.TYPE_EM or type == self.TYPE_3EM:
            data_info = await self._request_get("Meter_info.Get")
            data_dyn = await self._request_get("App_config.Get")
            data = dict(data_info, **data_dyn)
            data_new = await self._request_get("Sw_version.Get")
            data.update(data_new)
            return InfoForM2W.from_dict(data)
        else:
            raise DeviceError("Unknown device_id")
    
    async def device_config(self) -> Settings:
        """Return the charger's configuration.
        Ex:
        {'type': '1p7k', 'serial_number': 500006, 'board_revision': 'B'}"""
        # get device's type
        data = await self._request_get("Device_id.Get")
        _device_id: str = data["device_id"]
        data_type: dict
        if _device_id.startswith(self.TYPE_1P7K):
            data_type = {"type": self.TYPE_1P7K}
            data = await self._request_get("charger_config.get")
        elif _device_id.startswith(self.TYPE_3P22K):
            data_type = {"type": self.TYPE_3P22K}
            data = await self._request_get("charger_config.get")
        elif _device_id.startswith("m2w_81"):
            data_type = {"type": self.TYPE_EM}
            data = await self._request_get("M2w_config.Get")
        elif _device_id.startswith("m2w_83"):
            data_type = {"type": self.TYPE_3EM}
            data = await self._request_get("M2w_config.Get")
        else:
            raise DeviceError("Unknown device_id")
        
        data = dict(data_type, **data)
        return Settings.from_dict(data)
    
    async def send_charge_start(self) -> dict:
        """Command the charger to start charging.
        Return the device's confirmation.
        """
        return await self._request_post(
            {"src": "HASS", 
            "id": random.randint(10000000, 99999999), 
            "method": "charge.start", 
            "params":{"tag": "HASS"}})
        
    async def send_charge_stop(self) -> dict:
        """Command the charger to stop charging.
        Return the device's confirmation.
        """
        return await self._request_post(
            {"src": "HASS", 
            "id": random.randint(10000000, 99999999), 
            "method": "charge.stop"})
        
    async def send_reset(self) -> dict:
        """Command the device to reset.
        Return the device's confirmation.
        """
        return await self._request_post(
            {"src": "HASS", 
            "id": random.randint(10000000, 99999999), 
            "method": "device.reset"})    
        
    async def set_auth(self, value: bool) -> dict:
        """Set the authentication mode.
        Return the device's confirmation.
        """
        return await self._request_post(
            {"src": "HASS", 
            "id": random.randint(10000000, 99999999), 
            "method": "app_config.set", 
            "params":{"config_key": "headless", "config_value": value}})
        
    async def set_led_max_brightness(self, value: int) -> dict:
        """Set the value of led max brightness.
        Return the device's confirmation.
        """
        return await self._request_post(
            {"src": "HASS", 
            "id": random.randint(10000000, 99999999), 
            "method": "app_config.set", 
            "params":{"config_key": "led_max_brightness", "config_value": value}})

    async def set_dynamic_current(self, value: int) -> dict:
        """Set dynamic current.
        Return the device's confirmation.
        """
        return await self._request_post(
            {"src": "HASS", 
            "id": random.randint(10000000, 99999999), 
            "method": "dynamic_current.set", 
            "params":{"dynamic_current": value}})
    
    async def set_user_current(self, value: int) -> dict:
        """Set user current.
        Return the device's confirmation.
        """
        return await self._request_post(
            {"src": "HASS", 
            "id": random.randint(10000000, 99999999), 
            "method": "app_config.set", 
            "params":{"config_key": "user_current", "config_value": value}})

    async def set_load_balancing_mode(self, value: int) -> dict:
        """Set load_balancing_mode.
        Return the device's confirmation.
        """
        return await self._request_post(
            {"src": "HASS", 
            "id": random.randint(10000000, 99999999), 
            "method": "app_config.set", 
            "params":{"config_key": "load_balancing_mode", "config_value": value}})
    
    async def set_charger_locked(self, value: bool) -> bool:
        """Lock or unlock the device.
        Return the device's confirmation.
        """
        return await self._request_post(
            {"src": "HASS", 
            "id": random.randint(10000000, 99999999), 
            "method": "app_config.set", 
            "params":{"config_key": "charger_locked", "config_value": value}})    

        

    async def close(self) -> None:
        """Close open client session."""
        if self.asyncClient and self._close_session:
            await self.asyncClient.aclose()

    async def __aenter__(self) -> Device:
        """Async enter.
        Returns:
            The Device object.
        """
        return self

    async def __aexit__(self, *_exc_info) -> None:
        """Async exit.
        Args:
            _exc_info: Exec type.
        """
        await self.close()
    
    async def _request_get(self,uri: str) -> dict[str, Any]:
        """
        Handle a GET request to a Lektrico device.
        Args:
            uri: ex: "charger_info.get"
        Returns:
            A Python dictionary (JSON decoded) with the response from
            the Lektrico charger.
        Raises:
            DeviceConnectionError: An error occurred while communicating with
                the Lektrico device.
            DeviceError: Received an unexpected response from the Lektrico 
                device.
        """
        _url: str = F"http://{self._host}/rpc/{uri}"
        return await self._request(_url, "GET", None)
    
    async def _request_post(self,json: str) -> dict[str, Any]:
        """
        Handle a POST request to a Lektrico device.
        Args:
            json: ex: {"src": "HASS", 
                            "id": random.randint(10000000, 99999999), 
                            "method": "charge.start", 
                            "params":{"tag": "HASS"}}
        Returns:
            A Python dictionary (JSON decoded) with the response from
            the Lektrico charger.
        Raises:
            DeviceConnectionError: An error occurred while communicating with
                the Lektrico device.
            DeviceError: Received an unexpected response from the Lektrico 
                device.
        """
        return await self._request(F"http://{self._host}/rpc", "POST", json)
        
    async def _request(self,url: str, method: str, json: str) -> dict[str, Any]:
        """Handle a request to a Lektrico device.
        Args:
            url: ex: "charger_info.get"
            method: ex: METH_GET
            json: None for METH_GET
                  str for METH_POST
        Returns:
            A Python dictionary (JSON decoded) with the response from
            the Lektrico charger.
        Raises:
            DeviceConnectionError: An error occurred while communicating with
                the Lektrico device.
            DeviceError: Received an unexpected response from the Lektrico 
                device.
        """
        if self.asyncClient is None:
            self.asyncClient = httpx.AsyncClient() 
            self._close_session = True

        try:
            async with timeout(self.request_timeout):
                response = await self.asyncClient.request(
                    method,
                    url,
                    json = json
                )
                response.raise_for_status()
        except asyncio.TimeoutError as exception:
            raise DeviceConnectionError(
                "Timeout occurred while connecting to Lektrico device"
            ) from exception
        except (
            httpx.ConnectError,
            socket.gaierror,
        ) as exception:
            raise DeviceConnectionError(
                "Error occurred while communicating with Lektrico device"
            ) from exception

        content_type = response.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            text = await response.text()
            raise DeviceError(
                "Unexpected response from the Lektrico device",
                {"Content-Type": content_type, "response": text},
            )

        return response.json()
        
    def _put_readable_format(self, _state: str) -> str:
        """Convert state in a readable format.
        ex: state="B_AUTH" -> "Connected_NeedAuth" """
        if _state == "A":
            return "Available"
        elif _state == "B":
            return "Connected"
        elif _state == "B_AUTH":
            return "Connected,NeedAuth"
        elif _state == "B_PAUSE":
            return "Paused"
        elif _state == "C" or _state == "D":
            return "Charging"
        elif _state == "E" or _state == "F":
            return "Error"
        elif _state == "OTA":
            return "Updating firmware"
        else:
            return _state

