"""Telling local disks from network shares, so the database can warn when it is on the wrong one."""

from pathlib import Path

from web.core import fsinfo

MOUNTINFO = r"""\
24 1 8:1 / / rw,relatime - ext4 /dev/sda1 rw
31 24 0:27 / /mnt/nas/data rw,relatime - nfs4 192.168.2.217:/volume1/data rw,vers=4.1
32 31 0:28 / /mnt/nas/data/with\040space rw - cifs //nas/share rw
40 24 8:2 / /srv/cyno rw - ext4 /dev/sdb1 rw
"""


def _mountinfo(tmp_path: Path) -> Path:
    path = tmp_path / "mountinfo"
    path.write_text(MOUNTINFO)
    return path


def test_the_longest_matching_mount_decides(tmp_path: Path) -> None:
    """Test that a path is judged by the deepest mount that contains it, not by the root filesystem."""
    info = _mountinfo(tmp_path)
    assert fsinfo.filesystem_type(Path("/mnt/nas/data/cyno-studio/data"), info) == "nfs4"
    assert fsinfo.filesystem_type(Path("/srv/cyno/db"), info) == "ext4"
    assert fsinfo.filesystem_type(Path("/home/pete"), info) == "ext4"


def test_a_sibling_with_a_shared_prefix_is_not_inside_the_mount(tmp_path: Path) -> None:
    """Test that /mnt/nas/data-other is not mistaken for a path inside /mnt/nas/data."""
    assert fsinfo.filesystem_type(Path("/mnt/nas/data-other"), _mountinfo(tmp_path)) == "ext4"


def test_escaped_spaces_in_mount_points_are_decoded(tmp_path: Path) -> None:
    """Test that a mount point containing a space (escaped as octal 040 in mountinfo) is matched."""
    assert fsinfo.filesystem_type(Path("/mnt/nas/data/with space/x"), _mountinfo(tmp_path)) == "cifs"


def test_network_filesystems_are_recognised(tmp_path: Path) -> None:
    """Test that NFS and SMB count as network filesystems and a local disk does not."""
    info = _mountinfo(tmp_path)
    assert fsinfo.is_network_filesystem(Path("/mnt/nas/data/x"), info)
    assert fsinfo.is_network_filesystem(Path("/mnt/nas/data/with space"), info)
    assert not fsinfo.is_network_filesystem(Path("/srv/cyno/db"), info)


def test_an_unreadable_mountinfo_means_unknown(tmp_path: Path) -> None:
    """Test that where /proc is missing (macOS, Windows) the answer is unknown, not a false alarm."""
    missing = tmp_path / "nope"
    assert fsinfo.filesystem_type(Path("/srv"), missing) is None
    assert not fsinfo.is_network_filesystem(Path("/srv"), missing)
