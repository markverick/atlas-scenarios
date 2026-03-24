"""NDN-over-UDP packet capture parsing for emulation scenarios.

Classifies NDN packets from pcap files into user traffic (Interest/Data
matching the app prefix) and DV routing overhead.  Counts LP-encoded
bytes (= UDP payload) to match the sim's link tracer, which counts
LP-encoded bytes via the NdnPayloadTag.
"""

import os
import struct
from dataclasses import dataclass

# TLV byte pattern for the /ndn/test app prefix (GenericNameComponent encoding).
_USER_NAME_BYTES = b"\x08\x03ndn\x08\x04test"


@dataclass
class TrafficCounters:
    """Classified NDN traffic counters from pcap analysis."""

    dv_packets: int = 0
    dv_bytes: int = 0
    user_interest_packets: int = 0
    user_interest_bytes: int = 0
    user_data_packets: int = 0
    user_data_bytes: int = 0

    @property
    def user_packets(self):
        return self.user_interest_packets + self.user_data_packets

    @property
    def user_bytes(self):
        return self.user_interest_bytes + self.user_data_bytes

    @property
    def total_packets(self):
        return self.user_packets + self.dv_packets

    @property
    def total_bytes(self):
        return self.user_bytes + self.dv_bytes


def _unwrap_lp(payload):
    """Return the inner NDN TLV fragment from an LP packet, or payload unchanged."""
    if not payload or payload[0] != 100:  # LP packet type
        return payload
    i = 1
    if i < len(payload) and payload[i] >= 0xFD:
        i += 3
    else:
        i += 1
    while i + 1 < len(payload):
        t = payload[i]; i += 1
        if t >= 0xFD:
            if i + 2 < len(payload):
                t = struct.unpack_from("!H", payload, i + 1)[0]; i += 3
            else:
                break
        if i < len(payload) and payload[i] >= 0xFD:
            if i + 2 < len(payload):
                l = struct.unpack_from("!H", payload, i + 1)[0]; i += 3
            else:
                break
        elif i < len(payload):
            l = payload[i]; i += 1
        else:
            break
        if t == 80:  # LpPayload / Fragment
            return payload[i:i + l]
        i += l
    return payload


def _extract_udp_payload(frame, linktype):
    """Return UDP payload bytes for an IPv4/UDP/port-6363 packet, or None."""
    l2_len = {1: 14, 113: 16, 276: 20}.get(linktype)
    if l2_len is None or len(frame) < l2_len + 20:
        return None
    ip = frame[l2_len:]
    if (ip[0] >> 4) != 4:
        return None
    ihl = (ip[0] & 0x0F) * 4
    if ihl < 20 or len(ip) < ihl + 8:
        return None
    if ip[9] != 17:  # UDP
        return None
    udp = ip[ihl:]
    src_port, dst_port, udp_len = struct.unpack_from("!HHH", udp, 0)
    if src_port != 6363 and dst_port != 6363:
        return None
    if udp_len < 8 or len(udp) < udp_len:
        return None
    return udp[8:udp_len]


def parse_pcap(pcap_path, start_ts=None, end_ts=None):
    """Parse one pcap file and classify NDN packets.

    Only packets within [start_ts, end_ts) are counted when given.
    Returns a TrafficCounters instance.
    """
    result = TrafficCounters()
    if not pcap_path or not os.path.isfile(pcap_path):
        return result

    with open(pcap_path, "rb") as f:
        gh = f.read(24)
        if len(gh) < 24:
            return result
        magic = gh[:4]
        if magic == b"\xd4\xc3\xb2\xa1":
            endian = "<"
        elif magic == b"\xa1\xb2\xc3\xd4":
            endian = ">"
        else:
            return result
        linktype = struct.unpack(endian + "I", gh[20:24])[0]

        while True:
            ph = f.read(16)
            if len(ph) < 16:
                break
            ts_sec, ts_usec, incl_len, _ = struct.unpack(endian + "IIII", ph)
            frame = f.read(incl_len)
            if len(frame) < incl_len:
                break
            if start_ts is not None:
                pkt_ts = ts_sec + ts_usec / 1e6
                if pkt_ts < start_ts or pkt_ts >= end_ts:
                    continue
            payload = _extract_udp_payload(frame, linktype)
            if payload is None:
                continue
            tlv = _unwrap_lp(payload)
            if not tlv or tlv[0] not in (5, 6):  # Interest=5, Data=6
                continue
            is_interest = tlv[0] == 5
            lp_len = len(payload)
            if _USER_NAME_BYTES in tlv:
                if is_interest:
                    result.user_interest_packets += 1
                    result.user_interest_bytes += lp_len
                else:
                    result.user_data_packets += 1
                    result.user_data_bytes += lp_len
            else:
                result.dv_packets += 1
                result.dv_bytes += lp_len

    return result


def collect_traffic(pcap_paths, start_ts=None, end_ts=None):
    """Aggregate NDN traffic from multiple pcap files.

    Returns a TrafficCounters with totals across all files.
    """
    total = TrafficCounters()
    for path in pcap_paths:
        c = parse_pcap(path, start_ts, end_ts)
        total.dv_packets += c.dv_packets
        total.dv_bytes += c.dv_bytes
        total.user_interest_packets += c.user_interest_packets
        total.user_interest_bytes += c.user_interest_bytes
        total.user_data_packets += c.user_data_packets
        total.user_data_bytes += c.user_data_bytes
    return total


def parse_pcap_packets(pcap_paths, time_origin=None):
    """Extract per-packet (time, category, bytes) from multiple pcap files.

    Args:
        pcap_paths: iterable of pcap file paths
        time_origin: if given, subtract this from all timestamps to get
                     relative time (seconds). If None, uses the earliest
                     packet timestamp across all files.

    Returns list of (time_s, category_str, lp_bytes) tuples, sorted by time.
    """
    raw = []
    for path in pcap_paths:
        raw.extend(_parse_pcap_events(path))
    raw.sort(key=lambda x: x[0])
    if not raw:
        return raw
    if time_origin is None:
        time_origin = raw[0][0]
    return [(t - time_origin, cat, b) for t, cat, b in raw]


def _parse_pcap_events(pcap_path):
    """Parse one pcap file and yield (epoch_ts, category_str, lp_bytes)."""
    if not pcap_path or not os.path.isfile(pcap_path):
        return
    with open(pcap_path, "rb") as f:
        gh = f.read(24)
        if len(gh) < 24:
            return
        magic = gh[:4]
        if magic == b"\xd4\xc3\xb2\xa1":
            endian = "<"
        elif magic == b"\xa1\xb2\xc3\xd4":
            endian = ">"
        else:
            return
        linktype = struct.unpack(endian + "I", gh[20:24])[0]
        while True:
            ph = f.read(16)
            if len(ph) < 16:
                break
            ts_sec, ts_usec, incl_len, _ = struct.unpack(endian + "IIII", ph)
            frame = f.read(incl_len)
            if len(frame) < incl_len:
                break
            pkt_ts = ts_sec + ts_usec / 1e6
            payload = _extract_udp_payload(frame, linktype)
            if payload is None:
                continue
            tlv = _unwrap_lp(payload)
            if not tlv or tlv[0] not in (5, 6):
                continue
            lp_len = len(payload)
            if _USER_NAME_BYTES in tlv:
                cat = "UserInterest" if tlv[0] == 5 else "UserData"
            else:
                cat = "DvAdvert"    # routing-only: all non-user is DV
            yield (pkt_ts, cat, lp_len)
