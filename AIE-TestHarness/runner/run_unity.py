"""Minimal Unity runner that replaces the Babylon dependency.

Usage:
    python -m runner.run_unity
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests


def _load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@dataclass
class RunnerConfig:
    unity_exe_path: Path
    api_url: str
    api_key: str
    run_duration_seconds: Optional[float]
    screenshot_interval_seconds: Optional[float]
    artifact_root: Path
    unity_args: List[str]

    @classmethod
    def from_env(cls, env_path: Path = Path(".env")) -> "RunnerConfig":
        _load_env_file(env_path)
        unity_exe = Path(os.environ.get("UNITY_EXE_PATH", "")).expanduser()
        if not unity_exe:
            raise RuntimeError(
                "UNITY_EXE_PATH must be defined (path to TestHarness.exe)"
            )
        api_url = os.environ.get("AIE_API_URL", "http://127.0.0.1:8000").rstrip("/")
        api_key = os.environ.get("AIE_API_KEY")
        if not api_key:
            raise RuntimeError("AIE_API_KEY must be provided in .env or environment")
        run_duration = os.environ.get("RUN_DURATION_SECONDS", "")
        screenshot_interval = os.environ.get("SCREENSHOT_EVERY_SECONDS", "")
        artifact_root = Path(os.environ.get("ARTIFACT_ROOT", "artifacts"))
        unity_args = shlex.split(os.environ.get("UNITY_ARGS", ""))
        return cls(
            unity_exe_path=unity_exe,
            api_url=api_url,
            api_key=api_key,
            run_duration_seconds=float(run_duration) if run_duration else None,
            screenshot_interval_seconds=float(screenshot_interval)
            if screenshot_interval
            else None,
            artifact_root=artifact_root,
            unity_args=unity_args,
        )


class EpisodeClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "AIE-TestHarness-Runner/1.0",
            }
        )

    def create_episode(self, payload: Dict, bundle_path: Path) -> Dict:
        url = f"{self.base_url}/api/episodes"
        files = None
        if bundle_path.exists():
            files = {
                "bundle": (bundle_path.name, bundle_path.open("rb"), "application/zip"),
            }
        try:
            response = self.session.post(
                url,
                data={"payload": json.dumps(payload)},
                files=files,
                timeout=120,
            )
            response.raise_for_status()
            try:
                return response.json()
            except ValueError:
                return {"raw_text": response.text}
        finally:
            if files:
                files["bundle"][1].close()


class ScreenshotSampler:
    def __init__(self, interval_seconds: float, output_dir: Path) -> None:
        self.interval_seconds = interval_seconds
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._mss = None
        self.captured: List[Path] = []

    def start(self) -> None:
        if not self.interval_seconds or self.interval_seconds <= 0:
            return
        try:
            import mss
        except ImportError:
            print("[screenshots] mss not installed; skipping captures")
            return
        self._mss = mss.mss()
        self._thread = threading.Thread(
            target=self._capture_loop, name="ScreenshotSampler", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if not self._thread:
            return
        self._event.set()
        self._thread.join(timeout=5)
        if self._mss:
            self._mss.close()

    def _capture_loop(self) -> None:
        assert self._mss is not None
        while not self._event.wait(self.interval_seconds):
            timestamp = datetime.utcnow().strftime("%H%M%S")
            path = self.output_dir / f"screenshot-{timestamp}.png"
            try:
                self._mss.shot(output=str(path))
                self.captured.append(path)
                print(f"[screenshots] captured {path.name}")
            except Exception as exc:  # noqa: BLE001
                print(f"[screenshots] failed: {exc}")


class StreamTee:
    def __init__(self, pipe, destination: Path, prefix: str) -> None:
        self.pipe = pipe
        self.destination = destination
        self.prefix = prefix
        self.bytes_written = 0
        self._thread = threading.Thread(
            target=self._run, name=f"tee-{prefix}", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def join(self) -> None:
        self._thread.join()

    def _run(self) -> None:
        if self.pipe is None:
            return
        with self.destination.open("w", encoding="utf-8") as handle:
            for line in iter(self.pipe.readline, ""):
                handle.write(line)
                self.bytes_written += len(line.encode("utf-8", errors="replace"))
                stripped = line.rstrip()
                if stripped:
                    print(f"[{self.prefix}] {stripped}")
            self.pipe.close()


class UnityRunner:
    def __init__(self, config: RunnerConfig) -> None:
        self.config = config
        self.episode_client = EpisodeClient(config.api_url, config.api_key)

    def run(self) -> None:
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        build_id = f"AIE-TestHarness-{timestamp}"
        episode_dir = self.config.artifact_root / timestamp
        episode_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = episode_dir / "stdout.log"
        stderr_path = episode_dir / "stderr.log"
        player_log_path = episode_dir / "player.log"
        metadata_path = episode_dir / "metadata.json"
        screenshots_dir = episode_dir / "screenshots"
        bundle_path = episode_dir / "episode-bundle.zip"

        cmd = [str(self.config.unity_exe_path)]
        if self.config.unity_args:
            cmd.extend(self.config.unity_args)
        cmd.extend(["-logfile", str(player_log_path)])

        creationflags = 0
        if os.name == "nt":  # CREATE_NEW_PROCESS_GROUP
            creationflags = 0x00000200

        print(f"[runner] launching {' '.join(cmd)}")
        start_time = time.time()
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            creationflags=creationflags,
        )

        stdout_tee = StreamTee(process.stdout, stdout_path, "STDOUT")
        stderr_tee = StreamTee(process.stderr, stderr_path, "STDERR")
        stdout_tee.start()
        stderr_tee.start()

        screenshot_sampler = ScreenshotSampler(
            self.config.screenshot_interval_seconds or 0,
            screenshots_dir,
        )
        screenshot_sampler.start()

        timed_out = False
        try:
            while True:
                try:
                    return_code = process.wait(timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    if self.config.run_duration_seconds:
                        elapsed = time.time() - start_time
                        if elapsed >= self.config.run_duration_seconds:
                            print("[runner] duration cap reached; terminating player")
                            timed_out = True
                            process.terminate()
                            try:
                                return_code = process.wait(timeout=10)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                return_code = process.wait(timeout=5)
                            break
        except KeyboardInterrupt:
            print("[runner] Ctrl+C detected, stopping player…")
            process.terminate()
            process.wait(timeout=10)
            raise
        finally:
            screenshot_sampler.stop()

        stdout_tee.join()
        stderr_tee.join()
        duration_seconds = time.time() - start_time

        artifacts = [
            {"name": "stdout.log", "path": str(stdout_path)},
            {"name": "stderr.log", "path": str(stderr_path)},
            {"name": "player.log", "path": str(player_log_path)},
        ]
        if screenshot_sampler.captured:
            artifacts.append({"name": "screenshots", "path": str(screenshots_dir)})

        metadata = {
            "build_id": build_id,
            "timestamp_utc": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
            "duration_seconds": duration_seconds,
            "exit_code": return_code,
            "timed_out": timed_out,
            "artifacts": artifacts,
        }
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        artifacts.append({"name": "metadata", "path": str(metadata_path)})

        with zipfile.ZipFile(
            bundle_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as bundle:
            for artifact in artifacts:
                path = Path(artifact["path"])
                if path.is_file():
                    bundle.write(path, arcname=path.name)
                elif path.is_dir():
                    for sub_path in sorted(path.rglob("*")):
                        if sub_path.is_file():
                            bundle.write(
                                sub_path,
                                arcname=f"{path.name}/{sub_path.relative_to(path)}",
                            )
        artifact_bytes = bundle_path.stat().st_size if bundle_path.exists() else 0
        if bundle_path.exists():
            artifacts.append({"name": "bundle", "path": str(bundle_path)})

        payload = {
            "source": "unity-runner",
            "mode": "freestyle",
            "project": "AIE-TestHarness",
            "build_id": build_id,
            "labels": ["c1", "harness"],
            "metrics": {
                "duration_seconds": round(duration_seconds, 2),
                "exit_code": return_code,
                "timed_out": timed_out,
                "artifact_bytes": artifact_bytes,
            },
            "artifacts": artifacts,
        }

        print("[runner] posting episode payload…")
        response = self.episode_client.create_episode(payload, bundle_path)
        print(f"[runner] episode response: {json.dumps(response, indent=2)}")


def main() -> None:
    config = RunnerConfig.from_env()
    config.artifact_root.mkdir(parents=True, exist_ok=True)
    runner = UnityRunner(config)
    runner.run()


if __name__ == "__main__":
    main()
