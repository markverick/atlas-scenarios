import minindn.util


def _popen_get_env_compat(host, envDict=None):
    """Compatibility wrapper that preserves env values containing '='."""
    env = {}
    home_dir = host.params['params']['homeDir']
    printenv = host.popen('printenv'.split(), cwd=home_dir).communicate()[0].decode('utf-8')
    for var in printenv.split('\n'):
        if var == '':
            break
        parts = var.split('=', 1)
        if len(parts) == 2:
            env[parts[0]] = parts[1]
    env['HOME'] = home_dir

    if envDict is not None:
        for key, value in envDict.items():
            env[key] = str(value)

    return env


def patch_minindn():
    minindn.util.popenGetEnv = _popen_get_env_compat
