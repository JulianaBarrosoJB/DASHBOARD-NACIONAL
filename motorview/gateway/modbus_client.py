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

    def _read_block(self, address: int, count: int):
        """Compatibilidade com pymodbus 3.x: versões recentes usam device_id;
        versões anteriores usavam slave."""
        try:
            return self.client.read_holding_registers(
                address=address, count=count, device_id=self.slave_id
            )
        except TypeError:
            return self.client.read_holding_registers(
                address=address, count=count, slave=self.slave_id
            )

    def read(self) -> dict | None:
        """Lê os campos do mapa em blocos Modbus válidos (máx. 125 registradores).

        O mapa do CFW500 possui parâmetros próximos de zero e outros na faixa
        P0680; tentar ler tudo em uma única chamada ultrapassa o limite do
        function code 03. Por isso os endereços são separados em blocos.
        """
        address_to_names: dict[int, list[str]] = {}
        for name, spec in self.register_map.fields.items():
            address_to_names.setdefault(int(spec["address"]), []).append(name)

        if not address_to_names:
            return {}

        sorted_addresses = sorted(address_to_names)
        blocks: list[tuple[int, int]] = []
        block_start = block_end = sorted_addresses[0]

        for address in sorted_addresses[1:]:
            # Pode haver lacunas; o importante é não ultrapassar 125 registros.
            if address - block_start + 1 <= 125:
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
            except Exception as exc:  # comunicação instável no barramento RS-485
                log.warning(
                    "Falha ao ler slave %s, bloco %s..%s: %s",
                    self.slave_id, lo, hi, exc
                )
                return None

            if result is None or result.isError():
                log.warning(
                    "Resposta Modbus inválida do slave %s, bloco %s..%s: %s",
                    self.slave_id, lo, hi, result
                )
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
        timeout=serial_cfg.get("timeout", 1.0),
    )
