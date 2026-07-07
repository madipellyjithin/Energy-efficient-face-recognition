from __future__ import annotations

import ipaddress
import socket
import threading
import time
from dataclasses import dataclass

import requests
from zeroconf import ServiceBrowser, ServiceListener, Zeroconf


@dataclass
class Esp32Status:
    connected: bool = False
    base_url: str = ""
    last_message: str = ""
    armed: bool = True
    motion_count: int = 0


class _MdnsListener(ServiceListener):
    def __init__(self) -> None:
        self.url: str | None = None
        self.lock = threading.Lock()

    def update_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
        self.add_service(zc, service_type, name)

    def remove_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
        return

    def add_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
        info = zc.get_service_info(service_type, name)
        if info is None or not info.addresses:
            return

        address = socket.inet_ntoa(info.addresses[0])
        port = info.port
        with self.lock:
            self.url = f"http://{address}:{port}"


class Esp32ApiClient:
    def __init__(self, base_url: str = "", discovery_enabled: bool = True, mdns_service: str = "_edgeface._tcp.local.", scan_timeout_seconds: float = 4.0) -> None:
        self.session = requests.Session()
        self.discovery_enabled = discovery_enabled
        self.mdns_service = mdns_service
        self.scan_timeout_seconds = scan_timeout_seconds
        self.state = Esp32Status(base_url=base_url.rstrip("/"))

    def ensure_connection(self) -> str:
        if self.state.base_url:
            try:
                self.get_status()
                self.state.connected = True
                return self.state.base_url
            except requests.RequestException:
                self.state.connected = False

        if not self.discovery_enabled:
            raise RuntimeError("ESP32 API base URL is not configured and discovery is disabled")

        discovered = self._discover_mdns() or self._discover_by_scan()
        if not discovered:
            raise RuntimeError("Could not find ESP32 API automatically")

        self.state.base_url = discovered
        self.state.connected = True
        return discovered

    def rediscover(self) -> str:
        self.state.base_url = ""
        self.state.connected = False
        return self.ensure_connection()

    def get_status(self) -> dict:
        base_url = self.ensure_connection() if not self.state.base_url else self.state.base_url
        response = self.session.get(f"{base_url}/api/status", timeout=2)
        response.raise_for_status()
        data = response.json()
        self.state.last_message = data.get("lastEvent", "")
        self.state.armed = bool(data.get("armed", True))
        self.state.motion_count = int(data.get("motionCount", 0))
        self.state.connected = True
        return data

    def get_events(self, since: int) -> dict:
        base_url = self.ensure_connection() if not self.state.base_url else self.state.base_url
        response = self.session.get(f"{base_url}/api/events", params={"since": since}, timeout=2)
        response.raise_for_status()
        self.state.connected = True
        return response.json()

    def send_command(self, command: str) -> dict:
        base_url = self.ensure_connection() if not self.state.base_url else self.state.base_url
        response = self.session.post(f"{base_url}/api/control", json={"command": command}, timeout=4)
        response.raise_for_status()
        self.state.connected = True
        return response.json()

    def _discover_mdns(self) -> str | None:
        listener = _MdnsListener()
        zeroconf = Zeroconf()
        browser = ServiceBrowser(zeroconf, self.mdns_service, listener)
        try:
            deadline = time.time() + self.scan_timeout_seconds
            while time.time() < deadline:
                with listener.lock:
                    if listener.url:
                        if self._is_valid_endpoint(listener.url):
                            return listener.url
                time.sleep(0.2)
        finally:
            del browser
            zeroconf.close()
        return None

    def _discover_by_scan(self) -> str | None:
        host_ip = self._guess_local_ip()
        if not host_ip:
            return None

        network = ipaddress.ip_network(f"{host_ip}/24", strict=False)
        for ip in network.hosts():
            candidate = f"http://{ip}:80"
            if self._is_valid_endpoint(candidate):
                return candidate
        return None

    def _is_valid_endpoint(self, base_url: str) -> bool:
        try:
            response = self.session.get(f"{base_url}/api/status", timeout=0.5)
            if not response.ok:
                return False
            data = response.json()
            return data.get("device") == "esp32-face-bridge"
        except Exception:
            return False

    @staticmethod
    def _guess_local_ip() -> str | None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.connect(("8.8.8.8", 80))
            local_ip = sock.getsockname()[0]
            sock.close()
            return local_ip
        except OSError:
            return None
