#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys

import pytest

from pyscaffold import runner

from .fixtures import nogit_mock, tmpdir, git_mock


__author__ = "Florian Wilhelm"
__copyright__ = "Blue Yonder"
__license__ = "new BSD"


def test_parse_args():
    args = ["my-project"]
    opts = runner.parse_args(args)
    assert opts.package == "my_project"


def test_main_with_nogit(nogit_mock):
    args = ["my-project"]
    with pytest.raises(RuntimeError):
        runner.main(args)


def test_main_when_folder_exists(tmpdir, git_mock):
    args = ["my-project"]
    os.mkdir(args[0])
    with pytest.raises(RuntimeError):
        runner.main(args)


def test_main(tmpdir, git_mock):
    args = ["my-project"]
    runner.main(args)
    assert os.path.exists(args[0])


def test_main_with_license(tmpdir, git_mock):
    args = ["my-project", "-l", "new-bsd"]
    runner.main(args)
    assert os.path.exists(args[0])


def test_run(tmpdir, git_mock):
    sys.argv = ["pyscaffold", "my-project"]
    runner.run()
    assert os.path.exists(sys.argv[1])