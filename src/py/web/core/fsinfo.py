"""Which kind of filesystem a path is on (Linux only; anywhere else the answer is "unknown")."""

import re
from pathlib import Path

MOUNTINFO = Path("/proc/self/mountinfo")

# Filesystems shared between machines, where SQLite's WAL mode cannot coordinate its readers through shared memory.
NETWORK_FILESYSTEMS = frozenset(
    {"nfs", "nfs4", "cifs", "smb3", "smbfs", "9p", "ceph", "glusterfs", "lustre", "fuse.sshfs"}
)

MOUNT_POINT_FIELD = 4  # the fifth field of a mountinfo line

_OCTAL_ESCAPE = re.compile(r"\\([0-7]{3})")


def _unescape(field: str) -> str:
    """Decode the octal escapes mountinfo uses in paths (a space is written as a backslash and 040)."""
    return _OCTAL_ESCAPE.sub(lambda m: chr(int(m.group(1), 8)), field)


def filesystem_type(path: Path, mountinfo: Path = MOUNTINFO) -> str | None:
    """The filesystem type (e.g. "ext4", "nfs4") of the mount holding `path`, or None if it can't be told."""
    try:
        lines = mountinfo.read_text().splitlines()
    except OSError:
        return None
    target = str(path.resolve())
    best_mount, best_type = "", None
    for line in lines:
        before, separator, after = line.partition(" - ")
        fields = before.split()
        if not separator or len(fields) <= MOUNT_POINT_FIELD or not after:
            continue
        mount = _unescape(fields[MOUNT_POINT_FIELD])
        is_parent = target == mount or target.startswith(mount.rstrip("/") + "/")
        if is_parent and len(mount) >= len(best_mount):
            best_mount, best_type = mount, after.split()[0]
    return best_type


def is_network_filesystem(path: Path, mountinfo: Path = MOUNTINFO) -> bool:
    """Whether `path` sits on a filesystem shared between machines (NFS, SMB, ...)."""
    return filesystem_type(path, mountinfo) in NETWORK_FILESYSTEMS
