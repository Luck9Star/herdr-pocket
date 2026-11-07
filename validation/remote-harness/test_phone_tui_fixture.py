"""Semantic checks in an owned PTY. No SSH, device, renderer or account."""
import os
import unittest

if os.name == 'posix':
    import curses
    from phone_tui_probe import confirmed, drive


@unittest.skipUnless(os.name == 'posix', 'requires a POSIX PTY')
class PhoneTerminalTests(unittest.TestCase):
    def test_application_decodes_the_system_terminfo_keys(self):
        curses.setupterm('xterm-256color')
        sequence = [curses.tigetstr('kcud1'), b'\t', b'\x7f', curses.tigetstr('kcbt'),
                    curses.tigetstr('kich1'), curses.tigetstr('kdch1'),
                    curses.tigetstr('kf1'), curses.tigetstr('kf1'),
                    curses.tigetstr('kf5'), curses.tigetstr('kf10')]
        self.assertTrue(confirmed(drive(lambda _: sequence)))

    def test_partial_or_incorrect_actions_do_not_pass_on_exit(self):
        result = drive(lambda _: [b'x', b'\x1b[21~'])
        self.assertEqual(result['application']['actions'], ['unhandled', 'finish'])
        self.assertEqual(result['application']['selected'], 'Build')
        self.assertTrue(result['modesRestored'])
        self.assertFalse(confirmed(result))

    def test_cancel_and_timeout_leave_the_tty_in_its_original_mode(self):
        for cancel, outcome in [(True, 'cancelled'), (False, 'timeout')]:
            with self.subTest(outcome=outcome):
                result = drive(lambda _: [], seconds=1, cancel=cancel)
                self.assertEqual(result['application']['status'], outcome)
                self.assertEqual(result['application']['actions'], [])
                self.assertTrue(result['modesRestored'])
                self.assertTrue(result['leftAlternateScreen'])
                self.assertFalse(confirmed(result))
