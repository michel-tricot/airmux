from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, NonNegativeFloat, NonNegativeInt, PositiveFloat

ProcessRole = Literal["gateway", "provider", "client"]


class ResourceUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    elapsed_s: PositiveFloat
    cpu_seconds: dict[ProcessRole, NonNegativeFloat]
    gateway_cpu_seconds_by_pid: dict[int, NonNegativeFloat]
    provider_connections: NonNegativeInt


def process_times() -> dict[int, tuple[int, float]]:
    if Path("/proc/self/stat").is_file():
        frequency = os.sysconf("SC_CLK_TCK")
        processes = {}
        for path in Path("/proc").glob("[0-9]*/stat"):
            try:
                fields = path.read_text().rsplit(")", 1)[1].split()
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
            processes[int(path.parent.name)] = (int(fields[1]), (int(fields[11]) + int(fields[12])) / frequency)
        return processes
    result = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,time="], check=True, capture_output=True, text=True)  # noqa: S607 fixed process inspection command
    processes = {}
    for line in result.stdout.splitlines():
        pid, parent, duration = line.split()
        days, separator, clock = duration.partition("-")
        seconds = float(days) * 86400 if separator else 0.0
        for index, component in enumerate(reversed((clock if separator else duration).split(":"))):
            seconds += float(component) * 60**index
        processes[int(pid)] = (int(parent), seconds)
    return processes


def process_tree_times(roots: dict[ProcessRole, int]) -> dict[ProcessRole, dict[int, float]]:
    processes = process_times()

    def tree(root: int) -> dict[int, float]:
        descendants = {root}
        while children := {pid for pid, (parent, _) in processes.items() if parent in descendants} - descendants:
            descendants |= children
        return {pid: seconds for pid, (_, seconds) in processes.items() if pid in descendants}

    return {role: {pid: processes[pid][1]} if role == "client" else tree(pid) for role, pid in roots.items()}
