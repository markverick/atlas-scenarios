import json
import os
import shutil

from minindn.apps.application import Application


class NDNd_FW(Application):
    def __init__(self, node, config={}, logLevel='INFO', threads=2, ndnd_bin='ndnd', network='/minindn'):
        Application.__init__(self, node)
        self.ndnd_bin = ndnd_bin

        if not shutil.which(ndnd_bin):
            raise Exception(f'{ndnd_bin} not found in PATH, did you install it?')

        self.logFile = 'yanfd.log'
        logLevel = node.params['params'].get('nfd-log-level', logLevel)

        self.confFile = f'{self.homeDir}/yanfd.json'
        self.ndnFolder = f'{self.homeDir}/.ndn'
        self.clientConf = f'{self.ndnFolder}/client.conf'
        self.sockFile = f'/run/nfd/{node.name}.sock'

        self.envDict = {
            'GOMAXPROCS': str(threads),
        }

        # Make default configuration
        fw_config = {'threads': threads}
        # Two-phase PET forwarding needs the local router identity so that
        # forwarding hints for cert fetches are recognized as the local
        # producer region and the cert name is used for FIB lookup instead of
        # the hint name.  The onephase yanfd (ndnd-onephase) does not support
        # this field and will fail to parse the config if it is present.
        if ndnd_bin == 'ndnd':
            fw_config['router_name'] = f'{network}/{node.name}'

        default_config = {
            'core': {
                'log_level': logLevel,
            },
            'faces': {
                'unix': {
                    'socket_path': self.sockFile,
                },
            },
            'fw': fw_config,
        }

        # Write YaNFD config file
        with open(self.confFile, "w") as f:
            json.dump(default_config | config, f, indent=4)

        # Create client configuration for host to ensure socket path is consistent
        os.makedirs(self.ndnFolder, exist_ok=True)

        with open(self.clientConf, "w") as client_conf_file:
            client_conf_file.write(f"transport=unix://{self.sockFile}\n")

    def start(self):
        Application.start(self, f'{self.ndnd_bin} fw run {self.confFile}',
                          logfile=self.logFile, envDict=self.envDict)
