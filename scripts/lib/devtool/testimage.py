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

from devtool import setup_tinfoil, parse_recipe, DevtoolError
from devtool.build_image import build_image_task

logger = logging.getLogger('devtool')


def _collect_install_packages(tinfoil, config, package_names):
    """Return list of packages to install, including -ptest when available.

    package_names: list of PN values (typically recipe names).
    """
    install = []
    for pn in package_names:
        rd = parse_recipe(config, tinfoil, pn, True)
        if not rd:
            # parse_recipe already logs errors
            raise DevtoolError(f'Unable to find or parse recipe for package {pn}')

        install.append(pn)
        packages_var = rd.getVar('PACKAGES') or ''
        packages = packages_var.split()
        ptest_pkg = f'{pn}-ptest'
        if ptest_pkg in packages:
            install.append(ptest_pkg)
            logger.info('Including ptest package %s', ptest_pkg)
        else:
            logger.debug('No ptest package found for %s', pn)
    return install


def test_image(args, config, basepath, workspace):
    """Entry point for the devtool 'test-image' subcommand."""

    if not args.imagename:
        raise DevtoolError('Image recipe to test must be specified')
    if not args.package:
        raise DevtoolError('Package(s) to install must be specified via -p/--package')

    package_names = [p.strip() for p in args.package.split(',') if p.strip()]
    if not package_names:
        raise DevtoolError('No valid package name(s) provided')

    # Prepare a bbappend with IMAGE_INSTALL and testimage variables
    tinfoil = setup_tinfoil(basepath=basepath)
    try:
        install_pkgs = _collect_install_packages(tinfoil, config, package_names)
    finally:
        tinfoil.shutdown()

    logdir = os.path.join(config.workspace_path, 'testimage-logs')
    try:
        os.makedirs(logdir, exist_ok=True)
    except Exception as exc:
        raise DevtoolError(f'Failed to create test logs directory {logdir}: {exc}')

    pkg_append = ' '.join(sorted(set(install_pkgs)))
    extra_append = [
        f'TEST_LOG_DIR = "{logdir}"',
        # Ensure changes to these vars retrigger testimage and are visible
        'TESTIMAGE_UPDATE_VARS:append = " TEST_LOG_DIR IMAGE_CLASSES TEST_SUITES DISTRO_FEATURES"',
        # Ensure runtime test framework is enabled even if image/distro omitted it
        'IMAGE_CLASSES += " testimage"',
        # Ensure the image is actually built before do_testimage runs.
        # do_testimage reads ${DEPLOY_DIR_IMAGE}/${IMAGE_LINK_NAME}.testdata.json,
        # which is generated during the image build (rootfs postprocess).
        'do_testimage[depends] += " ${PN}:do_image_complete"',
        'TEST_SUITES = "ping ssh ptest"',
        'DISTRO_FEATURES:append = " ptest"',
        'TEST_RUNQEMUPARAMS = "slirp"',
        # Ensure a qemu-supported rootfs type is built/selected
        'IMAGE_FSTYPES:append = " ext4"',
        'QB_DEFAULT_FSTYPE = "ext4"',
        # Ensure requested packages (and -ptest where available) are installed
        f'IMAGE_INSTALL:append = " {pkg_append}"',
    ]

    logger.info('Building and testing image %s with packages: %s',
                args.imagename, ' '.join(install_pkgs))

    # Reuse build_image_task to run -c testimage with our bbappend.
    # The do_testimage[depends] tweak above ensures required image artifacts are built.
    result, _outputdir = build_image_task(
        config,
        basepath,
        workspace,
        args.imagename,
        add_packages=None,
        task='testimage',
        extra_append=extra_append,
    )

    if result == 0:
        logger.info('Testimage completed. Logs are in %s', logdir)
    return result


def register_commands(subparsers, context):
    """Register devtool subcommands from the test-image plugin"""
    parser = subparsers.add_parser(
        'test-image',
        help='Build image, install package(s), and run testimage',
        description=(
            'Builds an image, installs specified package(s), and runs the\n'
            'BitBake testimage task to validate on-target functionality.'
        ),
        group='testbuild',
        order=-9,
    )
    parser.add_argument('imagename', help='Image recipe to test')
    parser.add_argument(
        '-p', '--package', '--packages',
        help='Package(s) to install into the image (comma-separated)',
        metavar='PACKAGES',
    )
    parser.set_defaults(func=test_image)
