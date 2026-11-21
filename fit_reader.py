"""Read the standard FIT fields needed by the local activity previews."""

from struct import unpack_from


class FitError(ValueError):
    pass


FILE_ID, SESSION, RECORD, EVENT = 0, 18, 20, 21
TIMESTAMP = 253
FIELDS = {
    FILE_ID: {0},
    SESSION: {2, 5, 7, 8, 9, 16, 22},
    RECORD: {0, 1, 2, 3, 5, 6, 13, 73, 78, TIMESTAMP},
    EVENT: {0, 1, TIMESTAMP},
}
INTEGERS = {
    0x00: (1, False, 0xFF),  # enum
    0x01: (1, True, 0x7F),  # sint8
    0x02: (1, False, 0xFF),  # uint8
    0x84: (2, False, 0xFFFF),  # uint16
    0x85: (4, True, 0x7FFFFFFF),  # sint32
    0x86: (4, False, 0xFFFFFFFF),  # uint32
}


def crc_entry(byte):
    for _ in range(8):
        byte = (byte >> 1) ^ (0xA001 if byte & 1 else 0)
    return byte


CRC_TABLE = tuple(crc_entry(byte) for byte in range(256))


def crc16(data):
    crc = 0
    for byte in data:
        crc = (crc >> 8) ^ CRC_TABLE[(crc ^ byte) & 0xFF]
    return crc


def fit_payload(data):
    if len(data) < 14 or data[0] not in (12, 14) or data[8:12] != b".FIT":
        raise FitError("Missing or unsupported FIT header")
    header_size = data[0]
    data_end = header_size + unpack_from("<I", data, 4)[0]
    if data_end + 2 != len(data):
        raise FitError("FIT data size does not match the header")
    if header_size == 14 and any(data[12:14]) and crc16(data[:14]):
        raise FitError("FIT header checksum failed")
    if crc16(data):
        raise FitError("FIT file checksum failed")
    return memoryview(data)[header_size:data_end]


def messages(data, *, only=None):
    payload = fit_payload(data)
    offset = 0
    definitions = {}
    last_timestamp = None

    def take(size):
        nonlocal offset
        end = offset + size
        if end > len(payload):
            raise FitError("Truncated FIT message")
        value = payload[offset:end]
        offset = end
        return value

    while offset < len(payload):
        header = take(1)[0]
        compressed = bool(header & 0x80)
        local = (header >> 5) & 3 if compressed else header & 0x0F
        if not compressed and header & 0x40:
            _, architecture, a, b, count = take(5)
            if architecture not in (0, 1):
                raise FitError("Unsupported FIT definition byte order")
            byte_order = "big" if architecture else "little"
            global_id = int.from_bytes(bytes((a, b)), byte_order)
            fields = [tuple(take(3)) for _ in range(count)]
            developer_size = 0
            if header & 0x20:
                developer_size = sum(take(3)[1] for _ in range(take(1)[0]))
            definitions[local] = (global_id, byte_order, fields, developer_size)
            continue

        if local not in definitions:
            raise FitError("FIT data message precedes its definition")
        global_id, byte_order, fields, developer_size = definitions[local]
        selected = only is None or global_id in only
        fields_to_read = FIELDS.get(global_id, ()) if selected else ()
        values = {}
        if compressed:
            if last_timestamp is None or not fields or fields[0] != (TIMESTAMP, 4, 0x86):
                raise FitError("Compressed FIT timestamp has no valid reference")
            low_bits = header & 0x1F
            timestamp = (last_timestamp & ~0x1F) + low_bits
            last_timestamp = timestamp + 32 if timestamp < last_timestamp else timestamp
            values[TIMESTAMP] = last_timestamp
            fields = fields[1:]

        for number, size, base_type in fields:
            raw = take(size)
            # Other messages can still establish the reference for compressed timestamps.
            if number not in fields_to_read and number != TIMESTAMP:
                continue
            spec = INTEGERS.get(base_type)
            if spec is None or spec[0] != size:
                continue
            _, signed, invalid = spec
            value = int.from_bytes(raw, byte_order, signed=signed)
            if value == invalid:
                continue
            if number == TIMESTAMP and base_type == 0x86:
                last_timestamp = value
            values[number] = value
        take(developer_size)
        if selected and global_id in FIELDS:
            yield global_id, values
