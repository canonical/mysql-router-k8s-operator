# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import functools
import pathlib

import rock

_Path = functools.partial(rock._Path, container_=None)


def test_path_joining():
    assert _Path("/foo") == _Path("/foo")
    assert _Path("/foo") / "bar" == _Path("/foo/bar")
    assert "/etc" / _Path("foo") / "bar" == _Path("/etc/foo/bar")
    assert "/etc" / _Path("foo") / "bar" / "baz" == _Path("/etc/foo/bar/baz")
    assert _Path("/etc", "foo", "bar", "baz") == _Path("/etc/foo/bar/baz")
    assert _Path("foo") == _Path("foo")
    assert "etc" / _Path("foo") / "bar" / "baz" == _Path("etc/foo/bar/baz")


def test_relative_to_container():
    assert _Path("/foo").relative_to_container == pathlib.PurePath("/foo")
    assert _Path("/foo/bar").relative_to_container == pathlib.PurePath("/foo/bar")
    assert _Path("baz").relative_to_container == pathlib.PurePath("baz")
