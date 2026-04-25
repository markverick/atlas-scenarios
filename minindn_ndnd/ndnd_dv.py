import json
import os
import subprocess
import shutil
from pathlib import Path

from minindn.apps.application import Application

DEFAULT_NETWORK = '/minindn'

TRUST_ROOT_NAME = None
TRUST_ROOT_PATH = '/tmp/mn-dv-root'

# Schema files live inside the ndnd source tree, located via NDND_SRC (set by
# run.sh).  This mirrors how the CI's e2e/dv.py resolves them via
# Path(__file__).parent — the only difference is we are not inside that tree.
_NDND_SRC = os.environ.get('NDND_SRC', '')
ROUTING_LVS_SCHEMA = str(Path(_NDND_SRC) / 'dv' / 'config' / 'schema.tlv') if _NDND_SRC else None
CLIENT_LVS_SCHEMA  = str(Path(_NDND_SRC) / 'e2e' / 'client_lvs_minindn.tlv') if _NDND_SRC else None


class NDNd_DV(Application):
    config: str
    network: str

    def __init__(self, node, network=DEFAULT_NETWORK, dv_config=None, ndnd_bin='ndnd'):
        Application.__init__(self, node)
        self.network = network
        self.ndnd_bin = ndnd_bin

        if not shutil.which(ndnd_bin):
            raise Exception(f'{ndnd_bin} not found in PATH, did you install it?')

        if TRUST_ROOT_NAME is None:
            raise Exception('Trust root not initialized (call NDNd_DV.init_trust first)')

        self.init_keys()

        router_keychain = f'dir://{self.homeDir}/dv-keys'
        cfg = {
            'dv': {
                'network': network,
                'router': f"{network}/{node.name}",
                'keychain': router_keychain,
                'trust_anchors': [TRUST_ROOT_NAME],
                'neighbors': list(self.neighbors()),
            }
        }

        # twophase (dv2) uses LVS schema-based trust validation for both routing
        # advertisements and prefix insertion.  Without these fields every
        # neighbor advertisement is rejected ("key locator is nil") and routing
        # never converges.  onephase (main) does not use schema-based trust.
        is_twophase = (ndnd_bin == 'ndnd')
        if is_twophase:
            if not ROUTING_LVS_SCHEMA or not Path(ROUTING_LVS_SCHEMA).exists():
                raise Exception(f'Routing trust schema file not found: {ROUTING_LVS_SCHEMA} (is NDND_SRC set?)')
            if not CLIENT_LVS_SCHEMA or not Path(CLIENT_LVS_SCHEMA).exists():
                raise Exception(f'Client trust schema file not found: {CLIENT_LVS_SCHEMA} (is NDND_SRC set?)')
            cfg['dv']['trust_schema'] = ROUTING_LVS_SCHEMA
            cfg['dv']['prefix_insertion_keychain'] = router_keychain
            cfg['dv']['prefix_insertion_trust_anchors'] = [TRUST_ROOT_NAME]
            cfg['dv']['prefix_insertion_trust_schema'] = CLIENT_LVS_SCHEMA

        if dv_config:
            cfg['dv'].update(dv_config)
            # Prevent overriding per-node identity fields
            cfg['dv']['network'] = network
            cfg['dv']['router'] = f"{network}/{node.name}"

        self.config = f'{self.homeDir}/dv.config.json'
        with open(self.config, 'w') as f:
            json.dump(cfg, f, indent=4)

    def start(self):
        Application.start(self, [self.ndnd_bin, 'dv', 'run', self.config],
                          logfile='dv.log')

    @staticmethod
    def init_trust(network=DEFAULT_NETWORK, ndnd_bin='ndnd') -> None:
        global TRUST_ROOT_NAME
        subprocess.check_output(
            f'{ndnd_bin} sec keygen {network} ed25519 > {TRUST_ROOT_PATH}.key',
            shell=True)
        subprocess.check_output(
            f'{ndnd_bin} sec sign-cert {TRUST_ROOT_PATH}.key < {TRUST_ROOT_PATH}.key > {TRUST_ROOT_PATH}.cert',
            shell=True)
        out = subprocess.check_output(
            f'cat {TRUST_ROOT_PATH}.cert | grep "Name:" | cut -d " " -f 2',
            shell=True)
        TRUST_ROOT_NAME = out.decode('utf-8').strip()

    def init_keys(self) -> None:
        self.node.cmd(f'rm -rf dv-keys && mkdir -p dv-keys')
        self.node.cmd(
            f'{self.ndnd_bin} sec keygen {self.network}/{self.node.name}/32=DV ed25519 > dv-keys/{self.node.name}.key')
        self.node.cmd(
            f'{self.ndnd_bin} sec sign-cert {TRUST_ROOT_PATH}.key < dv-keys/{self.node.name}.key > dv-keys/{self.node.name}.cert')
        self.node.cmd(f'cp {TRUST_ROOT_PATH}.cert dv-keys/')

    def neighbors(self):
        for intf in self.node.intfList():
            other_intf = intf.link.intf2 if intf.link.intf1 == intf else intf.link.intf1
            yield {"uri": f"udp4://{other_intf.IP()}:6363"}
