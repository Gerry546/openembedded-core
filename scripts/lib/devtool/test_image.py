# Development tool - test-image plugin
#
# Copyright (C) 2026 Authors
#
# SPDX-License-Identifier: GPL-2.0-only

"""Devtool plugin containing the test-image subcommand.

Builds a target image, installs specified package(s) from the workspace or
layer, and runs the image's test suite via the BitBake `testimage` task.
"""

import os
import logging

from devtool import DevtoolError
from devtool.build_image import build_image_task

logger = logging.getLogger('devtool')


def _create_ptest_recipe_appends(config, package_names):
    """Create temporary per-package appends forcing PTEST_ENABLED=1.

    Returns list of created file paths for cleanup.
    """
    created = []
    appends_dir = os.path.join(config.workspace_path, 'appends')
    os.makedirs(appends_dir, exist_ok=True)

    for pn in sorted(set(package_names)):
        appendfile = os.path.join(appends_dir, f'{pn}_%.bbappend')
        if os.path.exists(appendfile):
            logger.debug('Using existing append %s', appendfile)
            continue
        with open(appendfile, 'w') as afile:
            afile.write('PTEST_ENABLED = "1"\n')
        created.append(appendfile)

    return created


def test_image(args, config, basepath, workspace):
    """Entry point for the devtool 'test-image' subcommand."""

    if not args.package:
        raise DevtoolError('Package(s) to install must be specified via -p/--package')

    package_names = [p.strip() for p in args.package.split(',') if p.strip()]
    if not package_names:
        raise DevtoolError('No valid package name(s) provided')

    if args.imagename:
        imagename = args.imagename
    else:
        if len(package_names) != 1:
            raise DevtoolError('Image recipe must be specified when testing multiple packages')
        imagename = f'core-image-ptest-{package_names[0]}'

    install_pkgs = package_names

    logdir = os.path.join(config.workspace_path, 'testimage-logs')
    try:
        os.makedirs(logdir, exist_ok=True)
    except Exception as exc:
        raise DevtoolError(f'Failed to create test logs directory {logdir}: {exc}')

    pkg_append = ' '.join(sorted(set(install_pkgs)))
    ptest_pkg_append = ' '.join(f'{pn}-ptest' for pn in sorted(set(install_pkgs)))
    extra_append = [
        f'TEST_LOG_DIR = "{logdir}"',
        'IMAGE_CLASSES += " testimage"',
        'IMAGE_FEATURES += "allow-empty-password empty-root-password allow-root-login"',
        'IMAGE_INSTALL:append = " ptest-runner sshd"',
        # Ensure requested packages (and -ptest where available) are installed
        f'IMAGE_INSTALL:append = " {pkg_append}"',
        f'IMAGE_INSTALL:append = " {ptest_pkg_append}"',
    ]
    if args.test_suites:
        suites = ' '.join(args.test_suites.split())
        if suites:
            extra_append.append(f'TEST_SUITES = "{suites}"')

    temp_ptest_appends = _create_ptest_recipe_appends(config, package_names)

    logger.info('Running testimage for %s with packages: %s',
                imagename, ' '.join(install_pkgs))
    try:
        result, _outputdir = build_image_task(
            config,
            basepath,
            workspace,
            imagename,
            add_packages=None,
            extra_append=extra_append,
        )
        if result == 0:
            result, _outputdir = build_image_task(
                config,
                basepath,
                workspace,
                imagename,
                add_packages=None,
                task='testimage',
                extra_append=extra_append,
            )
    finally:
        for appendfile in temp_ptest_appends:
            if os.path.exists(appendfile):
                os.unlink(appendfile)

    if result == 0:
        logger.info('Testimage completed. Logs are in %s', logdir)
    return result


def register_commands(subparsers, context):
    """Register devtool subcommands from the test-image plugin"""
    parser = subparsers.add_parser(
        'test-image',
        help='Build image, install package(s), and run selected test suites',
        description=(
            'Builds an image, installs specified package(s), and runs the\n'
            'BitBake testimage task. Use --test-suites to limit runtime suites\n'
            '(for example: "ping ssh ptest").'
        ),
        group='testbuild',
        order=-9,
    )
    parser.add_argument('imagename', help='Image recipe to test (defaults to core-image-ptest-<package>)', nargs='?')
    parser.add_argument(
        '-p', '--package', '--packages',
        help='Package(s) to install into the image (comma-separated)',
        metavar='PACKAGES',
    )
    parser.add_argument(
        '--test-suites',
        help='Override TEST_SUITES for this invocation (space-separated)',
        metavar='SUITES',
    )
    parser.set_defaults(func=test_image)
