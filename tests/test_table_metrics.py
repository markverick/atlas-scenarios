import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from lib import table_metrics


class FakeHost:
    def __init__(self, name, outputs):
        self.name = name
        self.outputs = outputs
        self.params = {"params": {"homeDir": f"/tmp/minindn/{name}"}}

    def cmd(self, command):
        for subcommand, output in self.outputs.items():
            if subcommand in command:
                return output
        raise AssertionError(f"unexpected command for {self.name}: {command}")


def test_parse_nfdc_status_listing_counts_entries():
    output = (
        "FIB:\n"
        "  /minindn/c0 nexthops={faceid=12 (cost=0)}\n"
        "  /data/e0/pfx0 nexthops={faceid=15 (cost=1)}\n"
    )

    assert table_metrics.parse_nfdc_status_listing(output, "FIB:") == 2


def test_parse_nfdc_status_listing_accepts_empty_dataset():
    assert table_metrics.parse_nfdc_status_listing("PET:\n", "PET:") == 0


def test_collect_emu_table_metrics_collects_fib_and_twophase_pet():
    hosts = [
        FakeHost("c0", {
            "fib-list": "FIB:\n  /minindn/c0 nexthops={faceid=12 (cost=0)}\n",
            "pet-list": "PET:\n  /data/e0/pfx0 egress={/minindn/e0} nexthops={faceid=15 (cost=1)}\n",
        }),
        FakeHost("e0", {
            "fib-list": (
                "FIB:\n"
                "  /minindn/e0 nexthops={faceid=6 (cost=0)}\n"
                "  /data/e0/pfx0 nexthops={faceid=8 (cost=1)}\n"
            ),
            "pet-list": (
                "PET:\n"
                "  /data/e0/pfx0 egress={/minindn/e0} nexthops={faceid=8 (cost=0)}\n"
                "  /minindn/c0 egress={} nexthops={faceid=6 (cost=1)}\n"
            ),
        }),
    ]

    rows = table_metrics.collect_emu_table_metrics(
        hosts,
        {"c0": "core", "e0": "edge"},
        "twophase",
        ndnd_bin="ndnd",
    )

    assert rows == [
        {
            "node": "c0",
            "role": "core",
            "table_category": "common",
            "table_name": "forwarder_fib",
            "entry_count": 1,
        },
        {
            "node": "c0",
            "role": "core",
            "table_category": "twophase",
            "table_name": "forwarder_pet",
            "entry_count": 1,
        },
        {
            "node": "e0",
            "role": "edge",
            "table_category": "common",
            "table_name": "forwarder_fib",
            "entry_count": 2,
        },
        {
            "node": "e0",
            "role": "edge",
            "table_category": "twophase",
            "table_name": "forwarder_pet",
            "entry_count": 2,
        },
    ]


def test_collect_emu_table_metrics_warns_and_skips_failed_listing():
    warnings = []

    rows = table_metrics.collect_emu_table_metrics(
        [
            FakeHost("c0", {
                "fib-list": "Error fetching status dataset: timeout\n",
            }),
        ],
        {"c0": "core"},
        "onephase",
        ndnd_bin="ndnd-onephase",
        warn=warnings.append,
    )

    assert rows == []
    assert warnings == [
        "WARNING: failed to collect forwarder_fib on c0: Error fetching status dataset: timeout"
    ]
