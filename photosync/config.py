import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    storage: Path
    database: Path
    marker: str
    require_nfs: bool
    max_bytes: int
    max_uploads: int

    @classmethod
    def from_env(cls):
        return cls(
            Path(os.getenv("PHOTOSYNC_STORAGE", "/mnt/hsk/photosync")),
            Path(os.getenv("PHOTOSYNC_DATABASE", "/var/lib/photosync/photosync.db")),
            os.getenv("PHOTOSYNC_STORAGE_ID", ""),
            os.getenv("PHOTOSYNC_REQUIRE_NFS", "1") == "1",
            int(os.getenv("PHOTOSYNC_MAX_BYTES", str(10 * 1024**3))),
            int(os.getenv("PHOTOSYNC_MAX_UPLOADS", "2")),
        )
