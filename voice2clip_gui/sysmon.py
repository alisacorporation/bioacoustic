"""System load for the CPU / GPU bars: /proc/stat for CPU, nvidia-smi (async, via QProcess) for GPU."""

from PySide6.QtCore import QObject, QProcess, QTimer, Signal


class SysMonitor(QObject):
    # cpu %, gpu % (-1 = unknown), vram used MiB, vram total MiB
    updated = Signal(float, float, float, float)

    def __init__(self, parent=None, interval_ms: int = 1000):
        super().__init__(parent)
        self._prev = self._cpu_times()
        self._gpu = (-1.0, 0.0, 0.0)
        self._proc = QProcess(self)
        self._proc.finished.connect(self._on_gpu)
        self._timer = QTimer(self, interval=interval_ms, timeout=self._tick)
        self._timer.start()

    @staticmethod
    def _cpu_times():
        try:
            with open("/proc/stat") as f:
                v = [int(x) for x in f.readline().split()[1:]]
            idle = v[3] + (v[4] if len(v) > 4 else 0)
            return sum(v), idle
        except OSError:
            return 0, 0

    def _tick(self):
        total, idle = self._cpu_times()
        dt, di = total - self._prev[0], idle - self._prev[1]
        self._prev = (total, idle)
        cpu = 100.0 * (1 - di / dt) if dt > 0 else 0.0
        if self._proc.state() == QProcess.NotRunning:
            self._proc.start("nvidia-smi", ["--query-gpu=utilization.gpu,memory.used,memory.total",
                                            "--format=csv,noheader,nounits"])
        self.updated.emit(cpu, *self._gpu)

    def _on_gpu(self, code, _status):
        try:
            if code != 0:
                raise ValueError
            line = bytes(self._proc.readAllStandardOutput()).decode().strip().splitlines()[0]
            util, used, total = (float(x) for x in line.split(","))
            self._gpu = (util, used, total)
        except (ValueError, IndexError):
            self._gpu = (-1.0, 0.0, 0.0)   # no NVIDIA GPU / nvidia-smi missing
