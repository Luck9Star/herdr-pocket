"""Owned synthetic waiting agents, reported through herdr's real 0.9.5 hook API.

No snapshot rewriting, AI service, attach, observe lease, terminal input or resize.
Only the caller's private pocket-probe socket and newly created workspaces are used.
"""
import argparse
import json
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import signal
import socket
import stat
import sys
import termios
import time
import tty
import uuid

SOURCE = 'pocket-blocked-fixture-v1'
AGENT = 'pocket-fixture'
LABEL = 'pocket-blocked'
SAMPLES = ('A', 'B')
PANE = re.compile(r'[A-Za-z0-9:_-]{1,128}')
TERMINAL = re.compile(r'term_[0-9a-f]{1,123}')
# Fixed upstream contract, not a claim about an arbitrary binary's build source:
# https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/api/schema/panes.rs
# https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/app/api/panes.rs


class BlockedFixtureFailure(ValueError):
    """Fixed codes only; never emit raw engine output or terminal data."""


def _alive(pid):
    try:
        os.kill(pid,0)  # Existence check only, for PIDs minted by our own child.
        return True
    except ProcessLookupError:
        return False


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BlockedFixtureFailure('blocked_fixture_wire_invalid')
        result[key] = value
    return result


def rpc(path, method, params):
    ident = 'pocket-blocked-' + uuid.uuid4().hex
    request = {'id':ident, 'method':method, 'params':params}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
            stream.settimeout(4)
            stream.connect(str(path))
            stream.sendall(json.dumps(request,separators=(',',':')).encode() + b'\n')
            with stream.makefile('rb') as incoming:
                raw = incoming.readline(1_048_577)
        if len(raw) > 1_048_576 or not raw.endswith(b'\n'):
            raise ValueError()
        value = json.loads(raw,object_pairs_hook=_unique)
        if not isinstance(value,dict) or value.get('id') != ident or 'error' in value or not isinstance(value.get('result'),dict):
            raise ValueError()
        return value['result']
    except (OSError, ValueError, TypeError):
        raise BlockedFixtureFailure('blocked_fixture_rpc_failed') from None


def snapshot(path):
    result = rpc(path,'session.snapshot',{})
    value = result.get('snapshot')
    if (result.get('type') != 'session_snapshot' or not isinstance(value,dict) or
            value.get('version') != '0.9.5' or type(value.get('protocol')) is not int or value['protocol'] != 22 or
            not isinstance(value.get('panes'),list)):
        raise BlockedFixtureFailure('blocked_fixture_snapshot_invalid')
    return value['panes']


def bindings(rows, targets, *, require_blocked=True):
    if not isinstance(rows,list) or not isinstance(targets,list) or len(targets) != 2:
        raise BlockedFixtureFailure('blocked_fixture_targets_invalid')
    clean = []
    for target in targets:
        if (not isinstance(target,dict) or set(target) != {'paneId','terminalId'} or
                not isinstance(target['paneId'],str) or not PANE.fullmatch(target['paneId']) or
                not isinstance(target['terminalId'],str) or not TERMINAL.fullmatch(target['terminalId'])):
            raise BlockedFixtureFailure('blocked_fixture_targets_invalid')
        matches = [row for row in rows if isinstance(row,dict) and row.get('pane_id') == target['paneId']]
        if (len(matches) != 1 or matches[0].get('terminal_id') != target['terminalId'] or
                len([row for row in rows if isinstance(row,dict) and row.get('terminal_id') == target['terminalId']]) != 1 or
                require_blocked and (matches[0].get('agent_status') != 'blocked' or
                                     matches[0].get('agent') != AGENT or matches[0].get('label') != LABEL)):
            raise BlockedFixtureFailure('blocked_fixture_binding_changed')
        clean.append(target.copy())
    if len({item['paneId'] for item in clean}) != 2 or len({item['terminalId'] for item in clean}) != 2:
        raise BlockedFixtureFailure('blocked_fixture_duplicate_target')
    return clean


class BlockedTargets:
    """Host controller; all writes are fixture setup/control outside the SSH client."""
    def __init__(self, root, config, command):
        self.root = Path(root).resolve()
        self.config = config
        self.command = command
        self.socket = self.root / 'config/herdr/sessions/pocket-probe/herdr.sock'
        if (Path(config['socketPath']) != self.socket or config['session'] != 'pocket-probe' or
                self.socket.is_symlink() or not stat.S_ISSOCK(self.socket.stat().st_mode)):
            raise BlockedFixtureFailure('blocked_fixture_not_owned_socket')
        self.targets = []
        self.directories = []
        self.pids = []
        self.stopped = False

    def prepare(self):
        if self.targets or self.directories:
            raise BlockedFixtureFailure('blocked_fixture_already_prepared')
        primary = [row for row in snapshot(self.socket) if row.get('pane_id') == self.config['paneId']]
        if len(primary) != 1:
            raise BlockedFixtureFailure('blocked_fixture_primary_invalid')
        primary_terminal = primary[0].get('terminal_id')
        script = self.root / 'blocked_fixture.py'
        shutil.copy2(Path(__file__),script)
        prefix = [self.config['herdrPath'],'--session','pocket-probe']
        for sample in SAMPLES:
            directory = self.root / ('blocked-' + sample)
            directory.mkdir(mode=0o700)
            self.directories.append(directory)
            raw = self.command(prefix + ['workspace','create','--cwd',str(directory),'--label',LABEL])
            try:
                created = json.loads(raw,object_pairs_hook=_unique)['result']['root_pane']
                target = {'paneId':created['pane_id'],'terminalId':created['terminal_id']}
                if not PANE.fullmatch(target['paneId']) or not TERMINAL.fullmatch(target['terminalId']):
                    raise ValueError()
                if target['paneId'] == self.config['paneId'] or target['terminalId'] == primary_terminal:
                    raise ValueError()
            except (KeyError,TypeError,ValueError):
                raise BlockedFixtureFailure('blocked_fixture_create_invalid') from None
            self.targets.append(target)
            # Both products display snapshot.panes[].label for blocked rows;
            # workspace.label and agent are separate fields and are insufficient.
            self.command(prefix + ['pane','rename',target['paneId'],LABEL])
            child = [sys.executable,str(script),'--directory',str(directory),
                     '--socket',str(self.socket),'--pane',target['paneId'],'--sample',sample]
            self.command(prefix + ['pane','run',target['paneId'],shlex.join(child)])
        deadline = time.monotonic() + 15
        while not all((directory/'capture-ready').is_file() for directory in self.directories):
            if time.monotonic() >= deadline:
                raise BlockedFixtureFailure('blocked_fixture_ready_timeout')
            time.sleep(0.05)
        for directory in self.directories:
            raw = (directory/'capture-running').read_bytes()
            if len(raw) > 16 or not re.fullmatch(rb'[1-9][0-9]{0,9}',raw) or int(raw) == os.getpid():
                raise BlockedFixtureFailure('blocked_fixture_pid_invalid')
            self.pids.append(int(raw))
        if len(set(self.pids)) != 2:
            raise BlockedFixtureFailure('blocked_fixture_pid_invalid')
        targets = self.verify()
        final_primary = [row for row in snapshot(self.socket) if row.get('pane_id') == self.config['paneId']]
        if len(final_primary) != 1 or final_primary[0].get('terminal_id') != primary_terminal:
            raise BlockedFixtureFailure('blocked_fixture_primary_changed')
        return targets

    def verify(self):
        if len(self.pids) != 2 or not all(_alive(pid) for pid in self.pids):
            raise BlockedFixtureFailure('blocked_fixture_waiter_not_alive')
        return bindings(snapshot(self.socket),self.targets)

    def stop(self):
        if self.stopped:
            raise BlockedFixtureFailure('blocked_fixture_already_stopped')
        self.stopped = True
        for directory in self.directories:
            with (directory/'stop-capture').open('xb') as output:
                output.write(b'stop\n')
        deadline = time.monotonic() + 8
        while (any((directory/'capture-running').exists() for directory in self.directories) or
               any(_alive(pid) for pid in self.pids)):
            if time.monotonic() >= deadline:
                raise BlockedFixtureFailure('blocked_fixture_stop_timeout')
            time.sleep(0.05)
        if len(self.pids) != 2:
            raise BlockedFixtureFailure('blocked_fixture_stop_unconfirmed')
        # The final publication is written before capture-running is removed.
        for directory in self.directories:
            try:
                with (directory/'received.bin').open('rb') as stream:
                    received = stream.read(4097)
                record = json.loads((directory/'pty-size.json').read_text())
                keys = ('state','endReason','changes','readErrors','captureErrors',
                        'initialRows','initialColumns','rows','columns')
                if (not isinstance(record,dict) or
                        any(type(record.get(key)) is not int or record[key] < 0 for key in keys) or
                        not 1 <= record['rows'] <= 65535 or not 1 <= record['columns'] <= 65535 or
                        received or record.get('state') != 2 or record.get('endReason') != 1 or
                        record.get('changes') != 0 or record.get('readErrors') != 0 or record.get('captureErrors') != 0 or
                        record.get('initialRows') != record.get('rows') or record.get('initialColumns') != record.get('columns')):
                    raise ValueError()
            except (OSError,ValueError,TypeError):
                raise BlockedFixtureFailure('blocked_fixture_boundary_unconfirmed') from None
        return {'targetCount':len(self.targets),'sameAgentLabel':True,'realSnapshotBindings':True,
                'receivedInputBytes':0,'noObservedResize':True,'ownedWaitingProcessesStopped':True}


def run_waiting_pane(directory, path, pane, sample, timeout=900):
    from capture_input import PtySizeRecorder
    if sample not in SAMPLES or not PANE.fullmatch(pane):
        raise BlockedFixtureFailure('blocked_fixture_child_invalid')
    directory = Path(directory)
    fd = sys.stdin.fileno()
    recorder = PtySizeRecorder(directory,fd)
    saved = termios.tcgetattr(fd)
    ending = 0
    handlers = {}
    def stop_signal(number,_frame):
        nonlocal ending
        ending = number
    reason, errors = 5, 0
    try:
        for number in (signal.SIGTERM,signal.SIGHUP,signal.SIGINT):
            handlers[number] = signal.signal(number,stop_signal)
        if hasattr(signal,'SIGWINCH'):
            handlers[signal.SIGWINCH] = signal.signal(signal.SIGWINCH,recorder.note_winch)
            recorder.record['signalAvailable'] = 1
        tty.setraw(fd)
        (directory/'received.bin').write_bytes(b'')
        # Keep the entire marker inside the rounded phone viewport's readable
        # cells. The renderer still has to draw every letter of the chosen pane.
        marker = '    POCKET-BLOCKED-' + sample
        os.write(1,(marker + '\r\nSynthetic waiting process; no AI account.\r\n').encode())
        recorder.start()
        result = rpc(path,'pane.report_agent',{'pane_id':pane,'source':SOURCE,'agent':AGENT,'state':'blocked','seq':1})
        if result != {'type':'ok'}:
            raise BlockedFixtureFailure('blocked_fixture_report_unconfirmed')
        (directory/'capture-running').write_text(str(os.getpid()))
        (directory/'capture-ready').write_bytes(b'ready\n')
        deadline, next_frame, frame = time.monotonic()+timeout,0.0,0
        while True:
            recorder.poll()
            if ending:
                reason=6
                break
            if (directory/'stop-capture').is_file():
                reason=1
                break
            now=time.monotonic()
            if now>=deadline:
                reason=2
                break
            if now>=next_frame:
                frame+=1
                os.write(1,(marker + ' frame ' + str(frame) + '\r\n').encode())
                next_frame=now+0.5
            if select.select([fd],[],[],0.05)[0]:
                data=os.read(fd,4097)
                if not data:
                    reason=4
                    break
                with (directory/'received.bin').open('ab') as output:
                    output.write(data)
                reason=3
                break
    except Exception:
        errors=1
    finally:
        try:
            termios.tcsetattr(fd,termios.TCSANOW,saved)
        except (OSError,termios.error):
            errors+=1
        recorder.finish(reason,ending,errors)
        (directory/'capture-running').unlink(missing_ok=True)
        for number,previous in handlers.items():
            signal.signal(number,previous)
    return 0 if recorder.record['state']==2 else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--socket',type=Path,required=True)
    parser.add_argument('--pane',required=True)
    parser.add_argument('--sample',choices=SAMPLES,required=True)
    args=parser.parse_args()
    try:
        raise SystemExit(run_waiting_pane(args.directory,args.socket,args.pane,args.sample))
    except Exception:
        raise SystemExit(1)
