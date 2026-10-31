from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DiskStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mount_point: str = Field(min_length=1, max_length=128)
    total_bytes: int = Field(ge=0)
    used_bytes: int = Field(ge=0)
    available_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_sizes(self) -> "DiskStatus":
        if self.used_bytes > self.total_bytes or self.available_bytes > self.total_bytes:
            raise ValueError("disk used and available bytes cannot exceed total bytes")
        return self


class ResticBackup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: str = Field(min_length=1, max_length=64)
    snapshot_time: datetime
    snapshot_id: str | None = Field(default=None, max_length=64)
    data_added_bytes: int | None = Field(default=None, ge=0)
    last_run_successful: bool | None = None


class StatusReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1, le=1)
    collected_at: datetime
    uptime_seconds: int = Field(ge=0)
    reboot_required: bool | None = None
    os_version: str | None = Field(default=None, min_length=1, max_length=128)
    kernel_version: str | None = Field(default=None, min_length=1, max_length=128)
    load_average: tuple[float, float, float] | None = None
    memory_available_bytes: int | None = Field(default=None, ge=0)
    memory_total_bytes: int | None = Field(default=None, ge=0)
    disks: list[DiskStatus] = Field(default_factory=list, max_length=16)
    restic_backups: list[ResticBackup] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def unique_entries(self) -> "StatusReport":
        mounts = [disk.mount_point for disk in self.disks]
        repositories = [backup.repository for backup in self.restic_backups]
        if len(mounts) != len(set(mounts)):
            raise ValueError("disk mount points must be unique")
        if len(repositories) != len(set(repositories)):
            raise ValueError("Restic repository labels must be unique")
        if self.collected_at.tzinfo is None:
            raise ValueError("collected_at must include a timezone")
        if self.load_average is not None and any(value < 0 for value in self.load_average):
            raise ValueError("load averages cannot be negative")
        if (
            self.memory_available_bytes is not None
            and self.memory_total_bytes is not None
            and self.memory_available_bytes > self.memory_total_bytes
        ):
            raise ValueError("available memory cannot exceed total memory")
        return self

