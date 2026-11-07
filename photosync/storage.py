import os
import re
from pathlib import Path


def storage_ready(root: Path, marker: str, require_nfs: bool) -> bool:
    if not marker or not root.is_dir():
        return False
    try:
        if (root / ".photosync-storage-id").read_text(encoding="utf-8").strip() != marker:
            return False
        if require_nfs:
            target = str(root.resolve())
            matches = []
            for line in Path("/proc/self/mountinfo").read_text().splitlines():
                left, right = line.split(" - ", 1)
                fields = left.split()
                mount = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), fields[4])
                if target == mount or target.startswith(mount.rstrip("/") + "/"):
                    matches.append((len(mount), right.split()[0]))
            if not matches or max(matches)[1] not in {"nfs", "nfs4"}:
                return False
        return os.access(root, os.W_OK)
    except (OSError, ValueError, IndexError):
        return False
