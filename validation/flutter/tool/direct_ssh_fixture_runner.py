#!/usr/bin/env python3
"""Run disposable loopback SSH widget tests; never uses host accounts or keys."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / 'validation/flutter/test/direct_ssh_fixture.py'


def run_mobile_tests(project, env, path, expected):
    # The JSON reporter distinguishes successful tests from silent skips.
    result = subprocess.run(['flutter', 'test', path, '--reporter', 'json'],
        cwd=project, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        print(result.stdout, end='')
        print(result.stderr, end='')
        result.check_returncode()
    starts, completed = {}, []
    for line in result.stdout.splitlines():
        event = json.loads(line)
        if event['type'] == 'testStart':
            starts[event['test']['id']] = event['test']['name']
        elif event['type'] == 'testDone' and not event.get('hidden', False):
            completed.append(event)
    if len(completed) < expected or any(event['skipped'] or event['result'] != 'success' for event in completed):
        print(result.stdout, end='')
        raise RuntimeError(f'{path}: expected at least {expected} passing tests with no skips')
    for event in completed:
        print(f"PASS {starts[event['testID']]}")
    print(f'{path}: {len(completed)} passed, 0 skipped')


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
        plain_key = temp / 'fixture-key-plain'
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(plain_key)], check=True)
        servers = []
        flutter_passed = False
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
            mobile_password_port = start({})
            mobile_plain_port = start({'HERDR_FIXTURE_PUBLIC_KEY': str(plain_key) + '.pub'})
            mobile_encrypted_port = start({'HERDR_FIXTURE_PUBLIC_KEY': str(key) + '.pub'})
            env = {**os.environ, 'HERDR_DIRECT_SSH_FIXTURE_PORT': password_port,
                'HERDR_DIRECT_SSH_ROTATE_PORT': rotate_port, 'HERDR_DIRECT_SSH_KEY_PORT': key_port,
                'HERDR_DIRECT_SSH_KEY_PATH': str(key)}
            subprocess.run(['flutter', 'test', 'test/direct_ssh_widget_test.dart', '--reporter', 'expanded'],
                cwd=args.project, env=env, check=True)
            # S10 spawns an independent rotation peer per case; it never shares these ports.
            subprocess.run(['flutter', 'test', 'test/direct_ssh_host_key_change_widget_test.dart', '--reporter', 'expanded'],
                cwd=args.project, env=dict(env, HERDR_FIXTURE_PYTHON=str(temp / 'venv/bin/python')), check=True)
            mobile_env = {**env, 'HERDR_DIRECT_SSH_FIXTURE_PORT': mobile_password_port,
                'HERDR_MOBILE_PLAIN_PORT': mobile_plain_port, 'HERDR_MOBILE_PLAIN_KEY': str(plain_key),
                'HERDR_MOBILE_ENCRYPTED_PORT': mobile_encrypted_port, 'HERDR_MOBILE_ENCRYPTED_KEY': str(key)}
            run_mobile_tests(args.project, mobile_env, 'test/direct_ssh_mobile_flow_test.dart', 5)
            run_mobile_tests(args.project, mobile_env, 'test/direct_ssh_return_widget_test.dart', 6)
            flutter_passed = True
        finally:
            logs = []
            for server in servers:
                server.terminate()
                try:
                    output = server.communicate(timeout=5)[0]
                except subprocess.TimeoutExpired:
                    server.kill(); output = server.communicate()[0]
                logs.append(output)
            if len(logs) == 6 and flutter_passed:
                if 'AUTH fixture' not in logs[0] or 'PTY ' not in logs[0] or 'INPUT ' not in logs[0]:
                    raise RuntimeError('password fixture did not observe authentication, PTY and input')
                if 'AUTH ' in logs[1] or 'PUBLICKEY ' in logs[1]:
                    raise RuntimeError('changed host key reached authentication')
                if 'PUBLICKEY fixture' not in logs[2] or 'PTY ' not in logs[2]:
                    raise RuntimeError('private-key fixture did not observe authentication and PTY')
                if logs[3].count('AUTH fixture') < 10 or logs[3].count('PTY ') < 10:
                    raise RuntimeError('mobile password and return flows did not observe all expected authentication and PTY events')
                if any('PUBLICKEY fixture' not in log or 'PTY ' not in log for log in logs[4:6]):
                    raise RuntimeError('mobile plain or encrypted key fixture did not observe public-key authentication and PTY')
                print('Fixture evidence: password, PTY, input, key rotation rejection and encrypted key authentication verified.')
                print('Mobile fixture evidence: password and return flows, plus plain and encrypted key authentication verified.')


if __name__ == '__main__':
    main()
