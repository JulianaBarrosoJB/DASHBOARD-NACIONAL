"""
MotorView Gateway - leitura Modbus RTU dos inversores
========================================================
Usa pymodbus para ler, via RS-485, os registradores mapeados em
registers_weg_cfw500.yaml (ou outro mapa que você configure) e devolve
um dicionário com valores já convertidos para unidade de engenharia.
"""

import logging
from pathlib import Path

import yaml
from pymodbus.client import ModbusSerialClient

log = logging.getLogger("motorview.modbus")


def _to_signed16(value: int) -> int:
    return value - 0x10000 if value >= 0x8000 else value


class RegisterMap:
    """Carrega e representa um mapa de registradores (ex.: registers_weg_cfw500.yaml)."""

    def __init__(self, path: Path):
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        self.function_code = data.get("function_code", 3)
        self.fields: dict = data["fields"]
        self.status_word_bits: dict = data.get("status_word_bits", {})
        self.fault_codes: dict = {int(k): v for k, v in data.get("fault_codes", {}).items()}

    def decode(self, raw_values: dict) -> dict:
        """raw_values: {field_name: raw_int_16bit} -> valores já escalados."""
        out = {}
        for name, spec in self.fields.items():
            raw = raw_values.get(name)
            if raw is None:
                continue
            if spec.get("signed"):
                raw = _to_signed16(raw)
            scale = spec.get("scale", 1)
            out[name] = round(raw / scale, 4) if scale != 1 else raw
        return out

    def decode_status_word(self, status_word: int) -> dict:
        return {name: bool(status_word & (1 << bit)) for bit, name in self.status_word_bits.items()}

    def fault_description(self, fault_code: int) -> str | None:
        if not fault_code:
            return None
        return self.fault_codes.get(int(fault_code), f"F{int(fault_code):04d} - código não mapeado")


class InverterReader:
    """Lê um único inversor (um slave_id) num barramento RS-485 compartilhado."""

    def __init__(self, client: ModbusSerialClient, slave_id: int, register_map: RegisterMap):
        self.client = client
        self.slave_id = slave_id
        self.register_map = register_map

    def read(self) -> dict | None:
        """Lê todos os campos do mapa em uma única (ou poucas) chamadas Modbus.
        Retorna None em caso de falha de comunicação (timeout/CRC/etc.)."""
        addresses = {spec["address"]: name for name, spec in self.register_map.fields.items()}
        if not addresses:
            return {}

        lo, hi = min(addresses), max(addresses)
        count = hi - lo + 1
        try:
            result = self.client.read_holding_registers(address=lo, count=count, slave=self.slave_id)
        except Exception as exc:  # comunicação instável no barramento RS-485
            log.warning("Falha ao ler slave %s: %s", self.slave_id, exc)
            return None

        if result is None or result.isError():
            log.warning("Resposta Modbus inválida do slave %s: %s", self.slave_id, result)
            return None

        raw_values = {
            name: result.registers[address - lo]
            for address, name in addresses.items()
            if address - lo < len(result.registers)
        }
        decoded = self.register_map.decode(raw_values)

        status_word = raw_values.get("status_word")
        if status_word is not None:
            decoded["status_bits"] = self.register_map.decode_status_word(status_word)

        fault_code = decoded.get("fault_code")
        if fault_code is not None:
            decoded["fault_description"] = self.register_map.fault_description(fault_code)

        return decoded


def build_serial_client(serial_cfg: dict) -> ModbusSerialClient:
    return ModbusSerialClient(
        port=serial_cfg["port"],
        baudrate=serial_cfg.get("baudrate", 19200),
        parity=serial_cfg.get("parity", "E"),
        stopbits=serial_cfg.get("stopbits", 1),
        bytesize=serial_cfg.get("bytesize", 8),
        timeout=serial_cfg.get("timeout", 1.0),
    )
