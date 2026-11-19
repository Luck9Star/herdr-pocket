#!/usr/bin/env python3
"""Owned AVD reverse mappings for the three constrained dual-overlay relays.

The caller creates the namespace and AndroidDualOverlayRelay first. Device ports
are the fixture's actual advertised control/DERP/EasyTier ports. No SSH mapping,
installation, system trust or App operation is performed by this module.
"""
import os
from pathlib import Path
import re
import subprocess

from android_dual_overlay_relay import ROLES, SHARED_EASYTIER_ROLES

SERIAL = 'emulator-5554'
ADB_DIAGNOSTICS = []
REVERSE_LIST_DIAGNOSTICS = []


class ReverseError(ValueError):
    pass


def _adb(*args, input_data=None, timeout=30):
    result = subprocess.run(['adb','-s',SERIAL,*args],input=input_data,stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,timeout=timeout,check=False)
    if result.returncode:
        operation = ('reverse_add' if args[:2] == ('reverse','--no-rebind') else
                     'reverse_remove' if args[:2] == ('reverse','--remove') else
                     'reverse_list' if args[:2] == ('reverse','--list') else
                     'shell' if args[:1] == ('shell',) else 'other')
        text = result.stderr.decode('utf-8',errors='replace').lower()
        ADB_DIAGNOSTICS.append({'operation':operation,'exitCode':int(result.returncode),
                                'stdoutBytes':len(result.stdout),'stderrBytes':len(result.stderr),
                                'unsupportedOption':('unknown option' in text or 'unrecognized option' in text)})
        del ADB_DIAGNOSTICS[:-12]
        raise ReverseError('adb_operation_failed')
    return result.stdout


def _text(*args):
    try:
        return _adb(*args).decode('utf-8',errors='strict').strip()
    except UnicodeError:
        raise ReverseError('adb_output_invalid') from None


def assert_owned_avd():
    env=os.environ
    if (env.get('GITHUB_ACTIONS') != 'true' or not env.get('GITHUB_REF','').startswith('refs/heads/codex/') or
            env.get('ANDROID_SERIAL') != SERIAL or not env.get('RUNNER_TEMP') or not env.get('ANDROID_AVD_HOME')):
        raise ReverseError('owned_avd_required')
    root=Path(env['RUNNER_TEMP']).resolve(strict=True)
    avd=Path(env['ANDROID_AVD_HOME']).resolve(strict=True)
    if avd == root or not avd.is_relative_to(root) or not avd.is_dir():
        raise ReverseError('owned_avd_required')
    result=subprocess.run(['adb','devices'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10,check=False)
    if result.returncode:
        raise ReverseError('adb_operation_failed')
    try:
        devices=[line.split()[:2] for line in result.stdout.decode('utf-8',errors='strict').splitlines()[1:] if line.strip()]
    except UnicodeError:
        raise ReverseError('adb_output_invalid') from None
    if (devices != [[SERIAL,'device']] or _text('shell','getprop','ro.kernel.qemu') != '1' or
            _text('shell','getprop','ro.build.version.sdk') != '35' or
            _text('shell','getprop','ro.product.cpu.abi') != 'x86_64' or
            _text('shell','am','get-current-user') != '0' or
            _text('shell','getprop','sys.boot_completed') != '1'):
        raise ReverseError('owned_avd_required')


def _mapping_list():
    lines=_text('reverse','--list').splitlines()
    mappings={}
    for line in lines:
        fields=line.split()
        if len(fields)!=3 or not fields[0] or not all(re.fullmatch(r'tcp:[1-9][0-9]{0,4}',v) for v in fields[1:]):
            REVERSE_LIST_DIAGNOSTICS.append({'lineCount':min(len(lines),100),'fieldCount':min(len(fields),9),'valid':False})
            del REVERSE_LIST_DIAGNOSTICS[:-12]
            raise ReverseError('reverse_list_invalid')
        device,host=(int(value[4:]) for value in fields[1:])
        if device>65535 or host>65535 or device in mappings:
            raise ReverseError('reverse_list_invalid')
        mappings[device]=host
    REVERSE_LIST_DIAGNOSTICS.append({'lineCount':min(len(lines),100),'valid':True})
    del REVERSE_LIST_DIAGNOSTICS[:-12]
    return mappings


class OwnedReverseMappings:
    """Install only selected no-rebind mappings and remove unchanged owned ones."""
    def __init__(self, relay, *, _device_check=None):
        self.relay=relay
        self.roles=getattr(relay, 'roles', ROLES)
        self._device_check=_device_check or assert_owned_avd
        self.created={}
        self.baseline=None
        self.cleanup_confirmed=False
        self.cleanup_evidence=None
        self.uncertain=set()
        self.installed_count=0
        self.removed_count=0

    def __enter__(self):
        self._device_check()
        config=self.relay.config
        if self.roles not in (ROLES, SHARED_EASYTIER_ROLES) or set(self.relay.ports)!=set(self.roles):
            raise ReverseError('relay_not_started')
        requested={config[role]:self.relay.ports[role] for role in self.roles}
        if (len(requested)!=len(self.roles) or len(set(requested.values()))!=len(self.roles) or
                set(requested)&set(config['sshPorts']) or set(requested.values())&set(config['sshPorts'])):
            raise ReverseError('ssh_reverse_forbidden')
        self.baseline=_mapping_list()
        if set(requested)&set(self.baseline):
            raise ReverseError('reverse_collision')
        try:
            for device,host in requested.items():
                try:
                    _adb('reverse','--no-rebind',f'tcp:{device}',f'tcp:{host}')
                except BaseException:
                    self.uncertain.add(device)
                    raise
                self.created[device]=host
                self.installed_count+=1
                if _mapping_list().get(device)!=host:
                    raise ReverseError('reverse_install_unconfirmed')
            return self
        except BaseException as original:
            try:
                self.close()
            except ReverseError:
                original.cleanup_code='reverse_cleanup_unconfirmed'
            raise

    def close(self):
        if self.cleanup_evidence is None:
            self._close_once()
        if not self.cleanup_confirmed:
            raise ReverseError('reverse_cleanup_unconfirmed')

    def _close_once(self):
        problems = set()
        already_absent = set()
        acknowledged = set()
        adb_errors = (ReverseError, OSError, subprocess.SubprocessError)
        for device, host in self.created.items():
            try:
                current = _mapping_list()
            except adb_errors:
                problems.add('list_before_remove_failed')
                continue
            if device not in current:
                already_absent.add(device)
            elif current[device] != host:
                problems.add('owned_mapping_changed')
            else:
                try:
                    _adb('reverse', '--remove', f'tcp:{device}')
                    acknowledged.add(device)
                except adb_errors:
                    problems.add('remove_unconfirmed')
        confirmed_absent = set()
        if self.baseline is not None:
            try:
                after = _mapping_list()
            except adb_errors:
                problems.add('list_after_remove_failed')
            else:
                if any(after.get(device) != host for device, host in self.baseline.items()):
                    problems.add('baseline_changed')
                if self.uncertain & after.keys():
                    problems.add('uncertain_mapping_remaining')
                if self.created.keys() & after.keys():
                    problems.add('owned_mapping_remaining')
                confirmed_absent = (acknowledged | already_absent) - after.keys()
                for device in confirmed_absent:
                    del self.created[device]
        self.removed_count = len(confirmed_absent & acknowledged)
        self.cleanup_evidence = {'removedConfirmed': self.removed_count,
                                 'alreadyAbsent': len(confirmed_absent & already_absent),
                                 'problems': sorted(problems)}
        self.cleanup_confirmed = not problems and not self.created

    def __exit__(self, kind, original, traceback):
        try:
            self.close()
        except ReverseError:
            if original is None:
                raise
            original.cleanup_code = 'reverse_cleanup_unconfirmed'
