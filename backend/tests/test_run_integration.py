import subprocess
import unittest
from unittest.mock import patch

import run_integration


class IntegrationRunnerTests(unittest.TestCase):
    def test_database_tests_use_separate_explicit_discovery_processes(self):
        with patch.object(run_integration, 'check_target') as guard, \
             patch.object(run_integration.subprocess, 'run') as run:
            run_integration.main()
        guard.assert_called_once_with()
        commands = [entry.args[0] for entry in run.call_args_list]
        self.assertEqual(commands[0][1:], ['-m', 'alembic', 'upgrade', 'head'])
        self.assertEqual([command[-2:] for command in commands[1:]],
                         [['test_api.py', '-v'], ['test_pipeline.py', '-v']])
        self.assertTrue(all(entry.kwargs == {'check': True} for entry in run.call_args_list))

    def test_failed_guard_prevents_all_subprocesses(self):
        with patch.object(run_integration, 'check_target', side_effect=RuntimeError), \
             patch.object(run_integration.subprocess, 'run') as run:
            with self.assertRaises(RuntimeError):
                run_integration.main()
        run.assert_not_called()

    def test_failed_migration_prevents_tests(self):
        with patch.object(run_integration, 'check_target'), \
             patch.object(run_integration.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'alembic')) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                run_integration.main()
        self.assertEqual(run.call_count, 1)
