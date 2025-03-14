import io
import os
import errno
import unittest

from pathlib.types import _JoinablePath, _ReadablePath, _WritablePath
import posixpath

from test.support.os_helper import TESTFN


_tests_needing_posix = set()
_tests_needing_windows = set()


def needs_posix(fn):
    """Decorator that marks a test as requiring a POSIX-flavoured path class."""
    _tests_needing_posix.add(fn.__name__)
    return fn

def needs_windows(fn):
    """Decorator that marks a test as requiring a Windows-flavoured path class."""
    _tests_needing_windows.add(fn.__name__)
    return fn


#
# Tests for the pure classes.
#


class DummyJoinablePath(_JoinablePath):
    __slots__ = ('_segments',)

    parser = posixpath

    def __init__(self, *segments):
        self._segments = segments

    def __str__(self):
        if self._segments:
            return self.parser.join(*self._segments)
        return ''

    def __eq__(self, other):
        if not isinstance(other, DummyJoinablePath):
            return NotImplemented
        return str(self) == str(other)

    def __hash__(self):
        return hash(str(self))

    def __repr__(self):
        return "{}({!r})".format(self.__class__.__name__, str(self))

    def with_segments(self, *pathsegments):
        return type(self)(*pathsegments)


class JoinablePathTest(unittest.TestCase):
    cls = DummyJoinablePath

    # Use a base path that's unrelated to any real filesystem path.
    base = f'/this/path/kills/fascists/{TESTFN}'

    def setUp(self):
        name = self.id().split('.')[-1]
        if name in _tests_needing_posix and self.cls.parser is not posixpath:
            self.skipTest('requires POSIX-flavoured path class')
        if name in _tests_needing_windows and self.cls.parser is posixpath:
            self.skipTest('requires Windows-flavoured path class')
        p = self.cls('a')
        self.parser = p.parser
        self.sep = self.parser.sep
        self.altsep = self.parser.altsep

    def _check_str_subclass(self, *args):
        # Issue #21127: it should be possible to construct a PurePath object
        # from a str subclass instance, and it then gets converted to
        # a pure str object.
        class StrSubclass(str):
            pass
        P = self.cls
        p = P(*(StrSubclass(x) for x in args))
        self.assertEqual(p, P(*args))
        for part in p.parts:
            self.assertIs(type(part), str)

    def test_str_subclass_common(self):
        self._check_str_subclass('')
        self._check_str_subclass('.')
        self._check_str_subclass('a')
        self._check_str_subclass('a/b.txt')
        self._check_str_subclass('/a/b.txt')

    @needs_windows
    def test_str_subclass_windows(self):
        self._check_str_subclass('.\\a:b')
        self._check_str_subclass('c:')
        self._check_str_subclass('c:a')
        self._check_str_subclass('c:a\\b.txt')
        self._check_str_subclass('c:\\')
        self._check_str_subclass('c:\\a')
        self._check_str_subclass('c:\\a\\b.txt')
        self._check_str_subclass('\\\\some\\share')
        self._check_str_subclass('\\\\some\\share\\a')
        self._check_str_subclass('\\\\some\\share\\a\\b.txt')

    def _check_str(self, expected, args):
        p = self.cls(*args)
        self.assertEqual(str(p), expected.replace('/', self.sep))

    def test_str_common(self):
        # Canonicalized paths roundtrip.
        for pathstr in ('a', 'a/b', 'a/b/c', '/', '/a/b', '/a/b/c'):
            self._check_str(pathstr, (pathstr,))
        # Other tests for str() are in test_equivalences().

    @needs_windows
    def test_str_windows(self):
        p = self.cls('a/b/c')
        self.assertEqual(str(p), 'a\\b\\c')
        p = self.cls('c:/a/b/c')
        self.assertEqual(str(p), 'c:\\a\\b\\c')
        p = self.cls('//a/b')
        self.assertEqual(str(p), '\\\\a\\b\\')
        p = self.cls('//a/b/c')
        self.assertEqual(str(p), '\\\\a\\b\\c')
        p = self.cls('//a/b/c/d')
        self.assertEqual(str(p), '\\\\a\\b\\c\\d')


#
# Tests for the virtual classes.
#


class DummyWritablePathIO(io.BytesIO):
    """
    Used by DummyWritablePath to implement `__open_wb__()`
    """

    def __init__(self, files, path):
        super().__init__()
        self.files = files
        self.path = path

    def close(self):
        self.files[self.path] = self.getvalue()
        super().close()


class DummyReadablePathInfo:
    __slots__ = ('_is_dir', '_is_file')

    def __init__(self, is_dir, is_file):
        self._is_dir = is_dir
        self._is_file = is_file

    def exists(self, *, follow_symlinks=True):
        return self._is_dir or self._is_file

    def is_dir(self, *, follow_symlinks=True):
        return self._is_dir

    def is_file(self, *, follow_symlinks=True):
        return self._is_file

    def is_symlink(self):
        return False


class DummyReadablePath(_ReadablePath, DummyJoinablePath):
    """
    Simple implementation of DummyReadablePath that keeps files and
    directories in memory.
    """
    __slots__ = ('_info')

    _files = {}
    _directories = {}
    parser = posixpath

    def __init__(self, *segments):
        super().__init__(*segments)
        self._info = None

    @property
    def info(self):
        if self._info is None:
            path_str = str(self)
            self._info = DummyReadablePathInfo(
                is_dir=path_str.rstrip('/') in self._directories,
                is_file=path_str in self._files)
        return self._info

    def __open_rb__(self, buffering=-1):
        path = str(self)
        if path in self._directories:
            raise IsADirectoryError(errno.EISDIR, "Is a directory", path)
        elif path not in self._files:
            raise FileNotFoundError(errno.ENOENT, "File not found", path)
        return io.BytesIO(self._files[path])

    def iterdir(self):
        path = str(self).rstrip('/')
        if path in self._files:
            raise NotADirectoryError(errno.ENOTDIR, "Not a directory", path)
        elif path in self._directories:
            return iter([self / name for name in self._directories[path]])
        else:
            raise FileNotFoundError(errno.ENOENT, "File not found", path)

    def readlink(self):
        raise NotImplementedError


class DummyWritablePath(_WritablePath, DummyJoinablePath):
    __slots__ = ()

    def __open_wb__(self, buffering=-1):
        path = str(self)
        if path in self._directories:
            raise IsADirectoryError(errno.EISDIR, "Is a directory", path)
        parent, name = posixpath.split(path)
        if parent not in self._directories:
            raise FileNotFoundError(errno.ENOENT, "File not found", parent)
        self._files[path] = b''
        self._directories[parent].add(name)
        return DummyWritablePathIO(self._files, path)

    def mkdir(self):
        path = str(self)
        parent = str(self.parent)
        if path in self._directories:
            raise FileExistsError(errno.EEXIST, "File exists", path)
        try:
            if self.name:
                self._directories[parent].add(self.name)
            self._directories[path] = set()
        except KeyError:
            raise FileNotFoundError(errno.ENOENT, "File not found", parent) from None

    def symlink_to(self, target, target_is_directory=False):
        raise NotImplementedError


class ReadablePathTest(JoinablePathTest):
    """Tests for ReadablePathTest methods that use stat(), open() and iterdir()."""

    cls = DummyReadablePath
    can_symlink = False

    # (self.base)
    #  |
    #  |-- brokenLink -> non-existing
    #  |-- dirA
    #  |   `-- linkC -> ../dirB
    #  |-- dirB
    #  |   |-- fileB
    #  |   `-- linkD -> ../dirB
    #  |-- dirC
    #  |   |-- dirD
    #  |   |   `-- fileD
    #  |   `-- fileC
    #  |   `-- novel.txt
    #  |-- dirE  # No permissions
    #  |-- fileA
    #  |-- linkA -> fileA
    #  |-- linkB -> dirB
    #  `-- brokenLinkLoop -> brokenLinkLoop
    #

    def setUp(self):
        super().setUp()
        self.createTestHierarchy()

    def createTestHierarchy(self):
        cls = self.cls
        cls._files = {
            f'{self.base}/fileA': b'this is file A\n',
            f'{self.base}/dirB/fileB': b'this is file B\n',
            f'{self.base}/dirC/fileC': b'this is file C\n',
            f'{self.base}/dirC/dirD/fileD': b'this is file D\n',
            f'{self.base}/dirC/novel.txt': b'this is a novel\n',
        }
        cls._directories = {
            f'{self.base}': {'fileA', 'dirA', 'dirB', 'dirC', 'dirE'},
            f'{self.base}/dirA': set(),
            f'{self.base}/dirB': {'fileB'},
            f'{self.base}/dirC': {'fileC', 'dirD', 'novel.txt'},
            f'{self.base}/dirC/dirD': {'fileD'},
            f'{self.base}/dirE': set(),
        }

    def tearDown(self):
        cls = self.cls
        cls._files.clear()
        cls._directories.clear()

    def tempdir(self):
        path = self.cls(self.base).with_name('tmp-dirD')
        path.mkdir()
        return path

    def assertFileNotFound(self, func, *args, **kwargs):
        with self.assertRaises(FileNotFoundError) as cm:
            func(*args, **kwargs)
        self.assertEqual(cm.exception.errno, errno.ENOENT)

    def assertEqualNormCase(self, path_a, path_b):
        normcase = self.parser.normcase
        self.assertEqual(normcase(path_a), normcase(path_b))

    @needs_posix
    def test_glob_posix(self):
        P = self.cls
        p = P(self.base)
        q = p / "FILEa"
        given = set(p.glob("FILEa"))
        expect = {q} if q.info.exists() else set()
        self.assertEqual(given, expect)
        self.assertEqual(set(p.glob("FILEa*")), set())

    @needs_windows
    def test_glob_windows(self):
        P = self.cls
        p = P(self.base)
        self.assertEqual(set(p.glob("FILEa")), { P(self.base, "fileA") })
        self.assertEqual(set(p.glob("*a\\")), { P(self.base, "dirA/") })
        self.assertEqual(set(p.glob("F*a")), { P(self.base, "fileA") })


class WritablePathTest(JoinablePathTest):
    cls = DummyWritablePath


class DummyRWPath(DummyWritablePath, DummyReadablePath):
    __slots__ = ()


class RWPathTest(WritablePathTest, ReadablePathTest):
    cls = DummyRWPath
    can_symlink = False


class ReadablePathWalkTest(unittest.TestCase):
    cls = DummyReadablePath
    base = ReadablePathTest.base
    can_symlink = False

    def setUp(self):
        self.walk_path = self.cls(self.base, "TEST1")
        self.sub1_path = self.walk_path / "SUB1"
        self.sub11_path = self.sub1_path / "SUB11"
        self.sub2_path = self.walk_path / "SUB2"
        self.link_path = self.sub2_path / "link"
        self.sub2_tree = (self.sub2_path, [], ["tmp3"])
        self.createTestHierarchy()

    def createTestHierarchy(self):
        cls = self.cls
        cls._files = {
            f'{self.base}/TEST1/tmp1': b'this is tmp1\n',
            f'{self.base}/TEST1/SUB1/tmp2': b'this is tmp2\n',
            f'{self.base}/TEST1/SUB2/tmp3': b'this is tmp3\n',
            f'{self.base}/TEST2/tmp4': b'this is tmp4\n',
        }
        cls._directories = {
            f'{self.base}': {'TEST1', 'TEST2'},
            f'{self.base}/TEST1': {'SUB1', 'SUB2', 'tmp1'},
            f'{self.base}/TEST1/SUB1': {'SUB11', 'tmp2'},
            f'{self.base}/TEST1/SUB1/SUB11': set(),
            f'{self.base}/TEST1/SUB2': {'tmp3'},
            f'{self.base}/TEST2': {'tmp4'},
        }

    def tearDown(self):
        cls = self.cls
        cls._files.clear()
        cls._directories.clear()


if __name__ == "__main__":
    unittest.main()
