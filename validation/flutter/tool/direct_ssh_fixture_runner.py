#!/usr/bin/env python3
"""Run disposable loopback SSH widget tests; never uses host accounts or keys."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / 'validation/flutter/test/direct_ssh_fixture.py'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True, help='prepared isolated Flutter project')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='herdr-direct-ssh-') as temp:
        temp = Path(temp)
        subprocess.run(['python3', '-m', 'venv', str(temp / 'venv')], check=True)
        python = temp / 'venv/bin/python'
        subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check', 'paramiko==4.0.0'], check=True)
        key = temp / 'fixture-key'
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', 'fixture-passphrase', '-f', str(key)], check=True)
        servers = []
        try:
            def start(extra):
                proc = subprocess.Popen([str(python), str(FIXTURE)], stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, env={**os.environ, **extra})
                servers.append(proc)
                line = proc.stdout.readline().strip()
                if not line.startswith('PORT '):
                    raise RuntimeError(f'fixture did not start: {line}')
                return line.split()[1]
            password_port = start({})
            rotate_port = start({'HERDR_FIXTURE_ROTATE_KEY': '1'})
            key_port = start({'HERDR_FIXTURE_PUBLIC_KEY': str(key) + '.pub'})
            env = {**os.environ, 'HERDR_DIRECT_SSH_FIXTURE_PORT': password_port,
                'HERDR_DIRECT_SSH_ROTATE_PORT': rotate_port, 'HERDR_DIRECT_SSH_KEY_PORT': key_port,
                'HERDR_DIRECT_SSH_KEY_PATH': str(key)}
            subprocess.run(['flutter', 'test', 'test/direct_ssh_widget_test.dart', '--reporter', 'expanded'],
                cwd=args.project, env=env, check=True)
        finally:
            logs = []
            for server in servers:
                server.terminate()
                try:
                    output = server.communicate(timeout=5)[0]
                except subprocess.TimeoutExpired:
                    server.kill(); output = server.communicate()[0]
                logs.append(output)
            if len(logs) == 3:
                if 'AUTH fixture' not in logs[0] or 'PTY ' not in logs[0] or 'INPUT ' not in logs[0]:
                    raise RuntimeError('password fixture did not observe authentication, PTY and input')
                if 'AUTH ' in logs[1] or 'PUBLICKEY ' in logs[1]:
                    raise RuntimeError('changed host key reached authentication')
                if 'PUBLICKEY fixture' not in logs[2] or 'PTY ' not in logs[2]:
                    raise RuntimeError('private-key fixture did not observe authentication and PTY')
                print('Fixture evidence: password, PTY, input, key rotation rejection and encrypted key authentication verified.')


if __name__ == '__main__':
    main()
