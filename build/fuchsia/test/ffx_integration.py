# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Provide helpers for running Fuchsia's `ffx`."""

import logging
import os
import json
import random
import subprocess
import tempfile

from contextlib import AbstractContextManager
from typing import Iterable, Optional

from common import get_host_arch, run_ffx_command, run_continuous_ffx_command, \
                   SDK_ROOT


def get_config(name: str) -> Optional[str]:
    """Run a ffx config get command to retrieve the config value."""

    try:
        return run_ffx_command(['config', 'get', name],
                               capture_output=True).stdout.strip()
    except subprocess.CalledProcessError as cpe:
        # A return code of 2 indicates no previous value set.
        if cpe.returncode == 2:
            return None
        raise


class ScopedFfxConfig(AbstractContextManager):
    """Temporarily overrides `ffx` configuration. Restores the previous value
    upon exit."""

    def __init__(self, name: str, value: str) -> None:
        """
        Args:
            name: The name of the property to set.
            value: The value to associate with `name`.
        """
        self._old_value = None
        self._new_value = value
        self._name = name

    def __enter__(self):
        """Override the configuration."""

        # Cache the old value.
        self._old_value = get_config(self._name)
        if self._new_value != self._old_value:
            run_ffx_command(['config', 'set', self._name, self._new_value])
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._new_value != self._old_value:
            run_ffx_command(['config', 'remove', self._name])
            if self._old_value is not None:
                # Explicitly set the value back only if removing the new value
                # doesn't already restore the old value.
                if  self._old_value != \
                    run_ffx_command(['config', 'get', self._name],
                                    capture_output=True).stdout.strip():
                    run_ffx_command(
                        ['config', 'set', self._name, self._old_value])

        # Do not suppress exceptions.
        return False


def test_connection(target_id: Optional[str]) -> None:
    """Run an echo test to verify that the device can be connected to."""

    run_ffx_command(('target', 'echo'), target_id)


class FfxEmulator(AbstractContextManager):
    """A helper for managing emulators."""

    def __init__(self,
                 enable_graphics: bool,
                 hardware_gpu: bool,
                 product_bundle: Optional[str],
                 with_network: bool,
                 logs_dir: Optional[str] = None) -> None:
        if product_bundle:
            self._product_bundle = product_bundle
        else:
            target_cpu = get_host_arch()
            self._product_bundle = f'terminal.qemu-{target_cpu}'

        self._enable_graphics = enable_graphics
        self._hardware_gpu = hardware_gpu
        self._logs_dir = logs_dir
        self._with_network = with_network
        node_name_suffix = random.randint(1, 9999)
        self._node_name = f'fuchsia-emulator-{node_name_suffix}'

        # Always set the download path parallel to Fuchsia SDK directory
        # so that old product bundles can be properly removed.
        self._scoped_pb_storage = ScopedFfxConfig(
            'pbms.storage.path', os.path.join(SDK_ROOT, os.pardir, 'images'))

    @staticmethod
    def _check_ssh_config_file() -> None:
        """Checks for ssh keys and generates them if they are missing."""
        script_path = os.path.join(SDK_ROOT, 'bin', 'fuchsia-common.sh')
        check_cmd = [
            'bash', '-c', f'. {script_path}; check-fuchsia-ssh-config'
        ]
        subprocess.run(check_cmd, check=True)

    def _download_product_bundle_if_necessary(self) -> None:
        """Download the image for a given product bundle."""

        # Check if the product bundle has already been downloaded.
        # TODO: remove when `ffx product-bundle get` doesn't automatically
        # redownload.
        list_cmd = run_ffx_command(('product-bundle', 'list'),
                                   capture_output=True)
        sdk_version = run_ffx_command(('sdk', 'version'),
                                      capture_output=True).stdout.strip()
        for line in list_cmd.stdout.splitlines():
            if (self._product_bundle in line and sdk_version in line
                    and '*' in line):
                return

        run_ffx_command(('product-bundle', 'get', self._product_bundle))

    def __enter__(self) -> str:
        """Start the emulator.

        Returns:
            The node name of the emulator.
        """

        self._scoped_pb_storage.__enter__()
        self._check_ssh_config_file()
        self._download_product_bundle_if_necessary()
        emu_command = [
            'emu', 'start', self._product_bundle, '--name', self._node_name
        ]
        if not self._enable_graphics:
            emu_command.append('-H')
        if self._hardware_gpu:
            emu_command.append('--gpu')
        if self._logs_dir:
            emu_command.extend(
                ('-l', os.path.join(self._logs_dir, 'emulator_log')))
        if self._with_network:
            emu_command.extend(('--net', 'tap'))
        run_ffx_command(emu_command)
        return self._node_name

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        """Shutdown the emulator."""

        # The emulator might have shut down unexpectedly, so this command
        # might fail.
        run_ffx_command(('emu', 'stop', self._node_name), check=False)

        self._scoped_pb_storage.__exit__(exc_type, exc_value, traceback)

        # Do not suppress exceptions.
        return False


class FfxTestRunner(AbstractContextManager):
    """A context manager that manages a session for running a test via `ffx`.

    Upon entry, an instance of this class configures `ffx` to retrieve files
    generated by a test and prepares a directory to hold these files either in a
    specified directory or in tmp. On exit, any previous configuration of
    `ffx` is restored and the temporary directory, if used, is deleted.

    The prepared directory is used when invoking `ffx test run`.
    """

    def __init__(self, results_dir: Optional[str] = None) -> None:
        """
        Args:
            results_dir: Directory on the host where results should be stored.
        """
        self._results_dir = results_dir
        self._custom_artifact_directory = None
        self._structured_output_config = None
        self._temp_results_dir = None

    def __enter__(self):
        self._structured_output_config = ScopedFfxConfig(
            'test.experimental_structured_output', 'true')
        self._structured_output_config.__enter__()
        if self._results_dir:
            os.makedirs(self._results_dir, exist_ok=True)
        else:
            self._temp_results_dir = tempfile.TemporaryDirectory()
            self._results_dir = self._temp_results_dir.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._temp_results_dir:
            self._temp_results_dir.__exit__(exc_type, exc_val, exc_tb)
            self._temp_results_dir = None
        self._structured_output_config.__exit__(exc_type, exc_val, exc_tb)
        self._structured_output_config = None

        # Do not suppress exceptions.
        return False

    def run_test(self,
                 component_uri: str,
                 test_args: Optional[Iterable[str]] = None,
                 node_name: Optional[str] = None) -> subprocess.Popen:
        """Starts a subprocess to run a test on a target.
        Args:
            component_uri: The test component URI.
            test_args: Arguments to the test package, if any.
            node_name: The target on which to run the test.
        Returns:
            A subprocess.Popen object.
        """
        command = [
            'test', 'run', '--output-directory', self._results_dir,
            component_uri
        ]
        if test_args:
            command.append('--')
            command.extend(test_args)
        return run_continuous_ffx_command(command,
                                          node_name,
                                          stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT)

    def _parse_test_outputs(self):
        """Parses the output files generated by the test runner.

        The instance's `_custom_artifact_directory` member is set to the
        directory holding output files emitted by the test.

        This function is idempotent, and performs no work if it has already been
        called.
        """
        if self._custom_artifact_directory:
            return

        run_summary_path = os.path.join(self._results_dir, 'run_summary.json')
        try:
            with open(run_summary_path) as run_summary_file:
                run_summary = json.load(run_summary_file)
        except IOError:
            logging.exception('Error reading run summary file.')
            return
        except ValueError:
            logging.exception('Error parsing run summary file %s',
                              run_summary_path)
            return

        assert run_summary['version'] == '0', \
            'Unsupported version found in %s' % run_summary_path

        # There should be precisely one suite for the test that ran. Find and
        # parse its file.
        suite_summary_filename = run_summary.get('suites',
                                                 [{}])[0].get('summary')
        suite_summary_path = os.path.join(self._results_dir,
                                          suite_summary_filename)
        with open(suite_summary_path) as suite_summary_file:
            suite_summary = json.load(suite_summary_file)

        assert suite_summary['version'] == '0', \
            'Unsupported version found in %s' % suite_summary_path

        # Get the top-level directory holding all artifacts for this suite.
        artifact_dir = suite_summary.get('artifact_dir')
        if not artifact_dir:
            logging.error('Failed to find suite\'s artifact_dir in %s',
                          suite_summary_path)
            return

        # Get the path corresponding to the CUSTOM artifact.
        for artifact_path, artifact in suite_summary['artifacts'].items():
            if artifact['artifact_type'] != 'CUSTOM':
                continue
            self._custom_artifact_directory = os.path.join(
                self._results_dir, artifact_dir, artifact_path)
            break

    def get_custom_artifact_directory(self) -> str:
        """Returns the full path to the directory holding custom artifacts
        emitted by the test or None if the directory could not be discovered.
        """
        self._parse_test_outputs()
        return self._custom_artifact_directory
