"""
MotorView Gateway - leitura Modbus RTU dos inversores
========================================================
Leitura completa por mapa e leitura pontual de registradores críticos
(corrente/falha), usando uma única conexão serial síncrona.
"""

import logging
from pathlib import Path

import yaml
from pymodbus.client import ModbusSerialClient

log = logging.getLogger("motorview.modbus")

# O CFW500 limita o telegrama Modbus RTU a 64 bytes. Em uma resposta
# Function 03, 29 registradores ocupam 63 bytes no quadro RTU:
# endereço + função + byte-count + 58 bytes de dados + CRC.
# Manter este limite evita que um mapa esparso (ex.: P0002..P0070)
# seja transformado em uma única leitura grande demais para o inversor.
MAX_READ_REGISTERS = 29


def _to_signed16(value: int) -> int:
    return value - 0x10000 if value >= 0x8000 else value


class RegisterMap:
    def __init__(self, path: Path):
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        self.function_code = data.get("function_code", 3)
        self.fields: dict = data["fields"]
        self.status_word_bits: dict = data.get("status_word_bits", {})
        self.fault_codes: dict = {int(k): v for k, v in data.get("fault_codes", {}).items()}

    def decode(self, raw_values: dict) -> dict:
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
    def __init__(self, client: ModbusSerialClient, slave_id: int, register_map: RegisterMap):
        self.client = client
        self.slave_id = slave_id
        self.register_map = register_map

    def _read_block(self, address: int, count: int):
        try:
            return self.client.read_holding_registers(
                address=address, count=count, device_id=self.slave_id
            )
        except TypeError:
            return self.client.read_holding_registers(
                address=address, count=count, slave=self.slave_id
            )

    def read_field(self, field_name: str):
        """Lê apenas um registrador do mapa e devolve valor em unidade de engenharia."""
        spec = self.register_map.fields.get(field_name)
        if not spec:
            raise KeyError(f"Campo não existe no mapa: {field_name}")
        try:
            result = self._read_block(int(spec["address"]), 1)
        except Exception as exc:
            log.warning("Falha ao ler %s do slave %s: %s", field_name, self.slave_id, exc)
            return None
        if result is None or result.isError() or not getattr(result, "registers", None):
            log.warning("Resposta inválida ao ler %s do slave %s: %s", field_name, self.slave_id, result)
            return None
        return self.register_map.decode({field_name: result.registers[0]}).get(field_name)

    def read(self) -> dict | None:
        address_to_names: dict[int, list[str]] = {}
        for name, spec in self.register_map.fields.items():
            address_to_names.setdefault(int(spec["address"]), []).append(name)

        if not address_to_names:
            return {}

        sorted_addresses = sorted(address_to_names)
        blocks: list[tuple[int, int]] = []
        block_start = block_end = sorted_addresses[0]

        for address in sorted_addresses[1:]:
            if address - block_start + 1 <= MAX_READ_REGISTERS:
                block_end = address
            else:
                blocks.append((block_start, block_end))
                block_start = block_end = address
        blocks.append((block_start, block_end))

        raw_values: dict[str, int] = {}

        for lo, hi in blocks:
            count = hi - lo + 1
            try:
                result = self._read_block(lo, count)
            except Exception as exc:
                log.warning("Falha ao ler slave %s, bloco %s..%s: %s", self.slave_id, lo, hi, exc)
                return None

            if result is None or result.isError():
                log.warning("Resposta Modbus inválida do slave %s, bloco %s..%s: %s", self.slave_id, lo, hi, result)
                return None

            for address in sorted_addresses:
                if lo <= address <= hi:
                    index = address - lo
                    if index < len(result.registers):
                        for name in address_to_names[address]:
                            raw_values[name] = result.registers[index]

        decoded = self.register_map.decode(raw_values)

        status_word = raw_values.get("status_word")
        if status_word is not None:
            decoded["status_bits"] = self.register_map.decode_status_word(status_word)

        fault_code = decoded.get("fault_code")
        if fault_code is not None:
            decoded["fault_description"] = self.register_map.fault_description(fault_code)

        for field, description_field in (
            ("last_fault_code", "last_fault_description"),
            ("second_fault_code", "second_fault_description"),
            ("third_fault_code", "third_fault_description"),
        ):
            code = decoded.get(field)
            if code is not None:
                decoded[description_field] = self.register_map.fault_description(code)

        last_fault_status = decoded.get("last_fault_status_word")
        if last_fault_status is not None:
            decoded["last_fault_status_bits"] = self.register_map.decode_status_word(last_fault_status)

        return decoded


def build_serial_client(serial_cfg: dict) -> ModbusSerialClient:
    return ModbusSerialClient(
        port=serial_cfg["port"],
        baudrate=serial_cfg.get("baudrate", 19200),
        parity=serial_cfg.get("parity", "E"),
        stopbits=serial_cfg.get("stopbits", 1),
        bytesize=serial_cfg.get("bytesize", 8),
        timeout=serial_cfg.get("timeout", 0.3),
        retries=serial_cfg.get("retries", 0),
    )
