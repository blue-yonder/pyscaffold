import logging
import os
import re
from configparser import ConfigParser
from os.path import join as path_join
from pathlib import Path
from textwrap import dedent

import pytest
from packaging.version import Version

from pyscaffold import __path__ as pyscaffold_paths
from pyscaffold import __version__, info, update
from pyscaffold.file_system import chdir

EDITABLE_PYSCAFFOLD = re.compile(r"^-e.+pyscaffold.*$", re.M | re.I)


class VenvManager(object):
    def __init__(self, tmpdir, venv, pytestconfig):
        self.tmpdir = str(tmpdir)  # convert Path to str
        self.installed = False
        self.venv = venv
        self.venv_path = str(venv.virtualenv)
        self.pytestconfig = pytestconfig
        self.install("coverage")
        self.running_version = Version(__version__)

    def install(self, pkg=None, editable=False):
        pkg = f'"{pkg}"'  # Windows requires double quotes to work properly with ranges
        if editable:
            pkg = f"--editable {pkg}"

        python = self.venv.python
        assert Path(python).exists()

        # Sometimes Windows complain about SSL, despite all the efforts on using a env
        # var for trusted hosts
        return self.run(
            f"{python} -m pip install {pkg} --trusted-host pypi.python.org "
            "--trusted-host files.pythonhosted.org --trusted-host pypi.org"
        )

    def install_this_pyscaffold(self):
        # Normally the following command should do the trick
        # self.venv.install_package('PyScaffold')
        # but sadly pytest-virtualenv chokes on the src-layout of PyScaffold
        if "TOXINIDIR" in os.environ:
            # so pytest runs within tox
            proj_dir = Path(os.environ["TOXINIDIR"])
            logging.debug("SRC via TOXINIDIR: %s", proj_dir)
        else:
            try:
                location = Path(pyscaffold_paths[0])
                assert location.parent.name == "src"
                proj_dir = location.parent.parent
            except:  # noqa
                print("\n\nInstall PyScaffold with python setup.py develop!\n\n")
                raise

            logging.debug("SRC via working_set: %s, location: %s", proj_dir, location)

        assert proj_dir.exists(), f"{proj_dir} is supposed to exist"
        self.install(proj_dir, editable=True)
        # Make sure pyscaffold was not installed using PyPI
        assert self.running_version.public <= self.pyscaffold_version().public
        pkg_list = self.run("{} -m pip freeze".format(self.venv.python))
        assert EDITABLE_PYSCAFFOLD.findall(pkg_list)
        self.installed = True
        return self

    def install_pyscaffold(self, major, minor):
        ver = "pyscaffold>={major}.{minor},<{major}.{next_minor}a0".format(
            major=major, minor=minor, next_minor=minor + 1
        )
        self.install(ver)
        installed_version = self.pyscaffold_version()._version.release[:2]
        assert installed_version == (major, minor)
        self.installed = True
        return self

    def uninstall_pyscaffold(self):
        self.run("{} -m pip uninstall -y pyscaffold".format(self.venv.python))
        assert "PyScaffold" not in self.venv.installed_packages().keys()
        self.installed = False
        return self

    def pyscaffold_version(self):
        version = self.venv.installed_packages().get("PyScaffold", None)
        if version:
            return Version(version.version)
        else:
            return None

    def putup(self, *args, with_coverage=False, **kwargs):
        if with_coverage:
            # need to pass here as list since its args to coverage.py
            args = [subarg for arg in args for subarg in arg.split()]
            putup_path = path_join(self.venv_path, "bin", "putup")
            cmd = [putup_path] + args
        else:
            # need to pass here as string since it's the cmd itself
            cmd = " ".join(["putup"] + list(args))
        self.run(cmd, with_coverage=with_coverage, **kwargs)
        return self

    def run(self, cmd, with_coverage=False, **kwargs):
        if with_coverage:
            kwargs.setdefault("pytestconfig", self.pytestconfig)
            # change to directory where .coverage needs to be created
            kwargs.setdefault("cd", os.getcwd())
            return self.venv.run_with_coverage(cmd, **kwargs).strip()
        else:
            with chdir(self.tmpdir):
                kwargs.setdefault("cwd", self.tmpdir)
                return self.venv.run(cmd, capture=True, **kwargs).strip()

    def get_file(self, path):
        with chdir(self.tmpdir):
            return Path(path).read_text()


@pytest.fixture
def venv_mgr(tmpdir, venv, pytestconfig):
    return VenvManager(tmpdir, venv, pytestconfig)


@pytest.mark.slow
def test_update_version_3_0_to_3_1(with_coverage, venv_mgr):
    project = path_join(venv_mgr.venv_path, "my_old_project")
    (
        venv_mgr.install_pyscaffold(3, 0)
        .putup(project)
        .uninstall_pyscaffold()
        .install_this_pyscaffold()
        .putup("--update {}".format(project), with_coverage=with_coverage)
    )
    setup_cfg = venv_mgr.get_file(path_join(project, "setup.cfg"))
    assert "[options.entry_points]" in setup_cfg


@pytest.mark.slow
def test_update_version_3_0_to_3_1_pretend(with_coverage, venv_mgr):
    project = path_join(venv_mgr.venv_path, "my_old_project")
    (
        venv_mgr.install_pyscaffold(3, 0)
        .putup(project)
        .uninstall_pyscaffold()
        .install_this_pyscaffold()
        .putup("--pretend --update {}".format(project), with_coverage=with_coverage)
    )
    setup_cfg = venv_mgr.get_file(path_join(project, "setup.cfg"))
    assert "[options.entry_points]" not in setup_cfg


@pytest.mark.slow
def test_inplace_update(with_coverage, venv_mgr):
    # Given an existing project
    project = Path(venv_mgr.tmpdir) / "my-ns-proj"
    (
        venv_mgr.install_this_pyscaffold().putup(
            "--package project --namespace my_ns {}".format(project)
        )
    )

    # With an existing configuration
    parser = ConfigParser()
    parser.read(project / "setup.cfg")
    assert parser["metadata"]["name"] == "my-ns-proj"
    assert parser["pyscaffold"]["package"] == "project"
    assert parser["pyscaffold"]["namespace"] == "my_ns"

    # And without some extensions
    for file in (".pre-commit-config.yaml", ".isort.cfg"):
        assert not Path(project, file).exists()

    # When the project is updated
    # without repeating the information already given
    # but adding some information/extensions
    with chdir(str(project)):
        (
            venv_mgr.putup(
                "-vv --description asdf --pre-commit --update .",
                with_coverage=with_coverage,
                cwd=str(project),
            )
        )

    # Then existing configuration should be preserved + the additions
    parser = ConfigParser()
    parser.read(project / "setup.cfg")
    assert parser["metadata"]["name"] == "my-ns-proj"
    assert parser["pyscaffold"]["package"] == "project"
    assert parser["pyscaffold"]["namespace"] == "my_ns"

    # Some information (metadata) require manual update
    # unless the --force option is used
    assert parser["metadata"]["description"] != "asdf"

    # New extensions should take effect
    for file in ("tox.ini", ".pre-commit-config.yaml", ".isort.cfg"):
        assert Path(project, file).exists()

    # While using the existing information
    parser = ConfigParser()
    parser.read(project / ".isort.cfg")
    assert parser["settings"]["known_first_party"] == "my_ns"


@pytest.fixture
def existing_config(tmpfolder):
    config = dedent(
        """\
        [options]
        setup_requires =
            pyscaffold
            somedep>=3.8

        [pyscaffold]
        version = 3.2.2
        """
    )
    cfg = Path(tmpfolder) / "setup.cfg"
    cfg.write_text(config)

    yield cfg


def test_update_setup_cfg(tmpfolder, existing_config):
    # Given an existing setup.cfg with outdated setup_requires and pyscaffold version,
    # when we update it
    opts = {"project_path": tmpfolder, "pretend": False}
    update.update_setup_cfg({}, opts)
    cfg = info.read_setupcfg(existing_config)
    # Then setup_requirements should not be included
    assert "setup_requires" not in str(cfg["options"])
    # Finally pyscaffold.version should be updated
    assert cfg["pyscaffold"]["version"].value == __version__


def test_update_setup_cfg_no_pyproject(tmpfolder, existing_config):
    # Given an existing setup.cfg with outdated setup_requires and pyscaffold version,
    # when we update it without no_pyproject
    opts = {"project_path": tmpfolder, "pretend": False, "isolated_build": False}
    update.update_setup_cfg({}, opts)
    cfg = info.read_setupcfg(existing_config)
    # Then setup_requirements is left alone
    assert cfg["options"]["setup_requires"]
    # And pyscaffold.version should be updated
    assert cfg["pyscaffold"]["version"].value == __version__


@pytest.fixture
def pyproject_from_old_extension(tmpfolder):
    """Old pyproject.toml file as produced by pyscaffoldext-pyproject"""
    config = dedent(
        """\
        [build-system]
        requires = ["setuptools", "wheel"]
        """
    )
    pyproject = Path(tmpfolder) / "pyproject.toml"
    pyproject.write_text(config)
    yield pyproject


def test_update_pyproject_toml(tmpfolder, pyproject_from_old_extension):
    update.update_pyproject_toml({}, {"project_path": tmpfolder, "pretend": False})
    pyproject = info.read_pyproject(pyproject_from_old_extension)
    deps = " ".join(pyproject["build-system"]["requires"])
    assert "setuptools_scm" in deps
    assert "setuptools.build_meta" in pyproject["build-system"]["build-backend"]
    assert "setuptools_scm" in pyproject["tool"]


def test_migrate_setup_requires(tmpfolder, existing_config):
    # When a project with setup.cfg :: setup_requires is updated
    opts = {"project_path": tmpfolder, "pretend": False}
    _, opts = update.update_setup_cfg({}, opts)
    update.update_pyproject_toml({}, opts)
    # then the minimal dependencies are added
    pyproject = info.read_pyproject(tmpfolder)
    deps = " ".join(pyproject["build-system"]["requires"])
    assert "setuptools_scm" in deps
    # old dependencies are migrated from setup.cfg
    assert "somedep>=3.8" in deps
    setupcfg = info.read_setupcfg(existing_config)
    assert "setup_requires" not in setupcfg["options"]
    # but pyscaffold is not included.
    assert "pyscaffold" not in deps
