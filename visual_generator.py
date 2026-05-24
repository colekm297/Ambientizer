"""
visual_generator.py — Generates visuals for ambient soundscape videos.

Two animation modes:
  - AI Animation: Grok Imagine Video (image-to-video) — $0.05/sec, up to 15s clips
  - Ken Burns: Free local ffmpeg zoom/pan effect (fallback)

Scene stills use grok-imagine-image-quality at 2k / 16:9 for YouTube-ready visuals.

Both get looped to match audio duration and combined into a YouTube-ready MP4.
"""

import os
import subprocess
import time
import requests
import base64
from pathlib import Path
from typing import Optional
from requests import HTTPError


class VisualGenerator:
    """Generates images and videos for ambient soundscape content."""

    HEADERS_JSON = {"Content-Type": "application/json"}

    def __init__(self, xai_api_key: str, output_dir: str = "./output"):
        self.api_key = xai_api_key
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            **self.HEADERS_JSON,
        }

    # ── Image Generation ──────────────────────────────────

    def generate_image(
        self,
        prompt: str,
        model: str = "grok-imagine-image-quality",
        output_path: Optional[str] = None,
        resolution: str = "2k",
        aspect_ratio: str = "16:9",
    ) -> str:
        """Generate a scene image using Grok Imagine API. Returns saved path."""
        if not output_path:
            safe = "".join(c if c.isalnum() or c in " -_" else "" for c in prompt[:40])
            output_path = str(self.output_dir / f"{safe}_visual.png")

        response = requests.post(
            "https://api.x.ai/v1/images/generations",
            headers=self._auth_headers(),
            json={
                "model": model,
                "prompt": prompt,
                "n": 1,
                "resolution": resolution,
                "aspect_ratio": aspect_ratio,
                "response_format": "b64_json",
            },
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()

        b64_data = data["data"][0]["b64_json"]
        image_bytes = base64.b64decode(b64_data)

        with open(output_path, "wb") as f:
            f.write(image_bytes)

        print(
            f"  Generated image: {output_path} ({len(image_bytes) / 1024:.0f} KB, "
            f"{model}, {resolution}, {aspect_ratio})"
        )
        return output_path

    # ── AI Video (Grok Imagine Video) ─────────────────────

    def animate_image(
        self,
        image_path: str,
        motion_prompt: str,
        duration: int = 10,
        output_path: Optional[str] = None,
        on_status=None,
    ) -> str:
        """
        Animate a still image using Grok Imagine Video (image-to-video).

        Costs $0.05/sec — a 10s clip costs $0.50.
        The API is async: submit, then poll until done.
        """
        if not output_path:
            stem = Path(image_path).stem
            output_path = str(self.output_dir / f"{stem}_animated.mp4")

        duration = max(1, min(15, duration))

        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")

        ext = Path(image_path).suffix.lower()
        mime = "image/png" if ext == ".png" else "image/jpeg"
        data_uri = f"data:{mime};base64,{image_b64}"

        def status(msg):
            print(f"  {msg}")
            if on_status:
                on_status(msg)

        status(f"Submitting image-to-video request ({duration}s, 720p)...")

        resp = requests.post(
            "https://api.x.ai/v1/videos/generations",
            headers=self._auth_headers(),
            json={
                "model": "grok-imagine-video",
                "prompt": motion_prompt,
                "image": {"url": data_uri},
                "duration": duration,
                "aspect_ratio": "16:9",
                "resolution": "720p",
            },
            timeout=30,
        )
        try:
            resp.raise_for_status()
        except HTTPError as e:
            body = resp.text[:2000] if resp.text else ""
            status(f"xAI video request failed: HTTP {resp.status_code} {body}")
            raise RuntimeError(f"xAI video request failed: HTTP {resp.status_code} {body}") from e
        request_id = resp.json()["request_id"]
        status(f"Video queued (id: {request_id}). Waiting for render...")

        video_url = self._poll_video(request_id, on_status=on_status)

        status("Downloading video...")
        video_resp = requests.get(video_url, timeout=120)
        video_resp.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(video_resp.content)

        size_mb = len(video_resp.content) / (1024 * 1024)
        status(f"AI animation ready: {output_path} ({size_mb:.1f} MB)")
        return output_path

    def extend_video(
        self,
        video_path: str,
        prompt: str,
        duration: int = 10,
        output_path: Optional[str] = None,
        on_status=None,
    ) -> str:
        """
        Extend an existing video with Grok Imagine Video.

        The xAI extensions endpoint accepts a public URL, file_id, or base64 data URI.
        We use a data URI so local preview clips and uploads can be extended without
        first publishing them anywhere.
        """
        if not output_path:
            stem = Path(video_path).stem
            output_path = str(self.output_dir / f"{stem}_extension.mp4")

        duration = max(1, min(10, int(duration)))
        if not prompt:
            prompt = "Continue the same slow ambient motion seamlessly. Keep the camera movement gentle, atmospheric, and loop-friendly."

        with open(video_path, "rb") as f:
            video_b64 = base64.b64encode(f.read()).decode("utf-8")
        data_uri = f"data:video/mp4;base64,{video_b64}"

        def status(msg):
            print(f"  {msg}")
            if on_status:
                on_status(msg)

        status(f"Submitting video extension request ({duration}s)...")
        resp = requests.post(
            "https://api.x.ai/v1/videos/extensions",
            headers=self._auth_headers(),
            json={
                "model": "grok-imagine-video",
                "prompt": prompt,
                "video": {"url": data_uri},
                "duration": duration,
            },
            timeout=60,
        )
        try:
            resp.raise_for_status()
        except HTTPError as e:
            body = resp.text[:2000] if resp.text else ""
            status(f"xAI video extension failed: HTTP {resp.status_code} {body}")
            raise RuntimeError(f"xAI video extension failed: HTTP {resp.status_code} {body}") from e

        request_id = resp.json()["request_id"]
        status(f"Video extension queued (id: {request_id}). Waiting for render...")
        video_url = self._poll_video(request_id, on_status=on_status)

        status("Downloading video extension...")
        video_resp = requests.get(video_url, timeout=120)
        video_resp.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(video_resp.content)

        size_mb = len(video_resp.content) / (1024 * 1024)
        status(f"Video extension ready: {output_path} ({size_mb:.1f} MB)")
        return output_path

    def _poll_video(self, request_id: str, timeout: int = 600, interval: int = 5, on_status=None) -> str:
        """Poll the xAI video endpoint until the video is ready. Returns the video URL."""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        start = time.time()

        while time.time() - start < timeout:
            result = requests.get(
                f"https://api.x.ai/v1/videos/{request_id}",
                headers=headers,
                timeout=15,
            )
            try:
                result.raise_for_status()
            except HTTPError as e:
                body = result.text[:2000] if result.text else ""
                if result.status_code == 429:
                    if on_status:
                        on_status("xAI is rate-limiting the status check; waiting and retrying...")
                    time.sleep(min(30, interval * 2))
                    continue
                raise RuntimeError(f"xAI video poll failed: HTTP {result.status_code} {body}") from e
            data = result.json()
            status = data.get("status")

            if status == "done":
                return data["video"]["url"]
            elif status in ("expired", "failed"):
                raise RuntimeError(f"Video generation {status}: {data}")

            elapsed = int(time.time() - start)
            if on_status and elapsed % 15 < interval:
                on_status(f"Still rendering... ({elapsed}s)")

            time.sleep(interval)

        raise TimeoutError(f"Video generation timed out after {timeout}s")

    # ── Ken Burns (free ffmpeg fallback) ──────────────────

    def create_ken_burns_video(
        self,
        image_path: str,
        duration_sec: float = 30.0,
        output_path: Optional[str] = None,
        zoom_speed: float = 0.0003,
        fps: int = 24,
    ) -> str:
        """Create a Ken Burns (slow zoom) video from a static image using ffmpeg."""
        if not output_path:
            stem = Path(image_path).stem
            output_path = str(self.output_dir / f"{stem}_kenburns.mp4")

        total_frames = int(duration_sec * fps)
        max_zoom = 1 + (zoom_speed * total_frames)
        if max_zoom > 1.8:
            zoom_speed = 0.8 / total_frames

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", image_path,
            "-vf", (
                f"scale=8000:-1,"
                f"zoompan=z='min(zoom+{zoom_speed},{1 + zoom_speed * total_frames:.4f})':"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d={total_frames}:s=1920x1080:fps={fps}"
            ),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-t", str(duration_sec),
            output_path,
        ]

        print(f"  Creating Ken Burns video ({duration_sec:.0f}s)...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr[-500:]}")

        print(f"  Video created: {output_path}")
        return output_path

    # ── Shared utilities ──────────────────────────────────

    def concat_videos(self, video_paths: list[str], output_path: str) -> str:
        """Join video clips into one MP4, re-encoding for codec/resolution safety."""
        if len(video_paths) < 2:
            raise ValueError("Need at least two videos to concatenate")

        inputs = []
        filter_inputs = []
        for idx, path in enumerate(video_paths):
            inputs.extend(["-i", path])
            filter_inputs.append(f"[{idx}:v:0]")

        filter_complex = "".join(filter_inputs) + f"concat=n={len(video_paths)}:v=1:a=0[v]"
        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-an",
            output_path,
        ]

        print(f"  Concatenating {len(video_paths)} video segment(s)...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed: {result.stderr[-1000:]}")

        print(f"  Concatenated video: {output_path}")
        return output_path

    def slow_video(self, video_path: str, speed: float, output_path: str) -> str:
        """Create a real slowed-down MP4 clip for preview/export."""
        speed = max(0.25, min(1.0, float(speed)))
        setpts = 1.0 / speed
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-filter:v", f"setpts={setpts:.6f}*PTS",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-an",
            output_path,
        ]

        print(f"  Slowing video to {speed:.2f}x...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg slow video failed: {result.stderr[-1000:]}")

        print(f"  Slowed video: {output_path}")
        return output_path

    def loop_video(
        self,
        video_path: str,
        target_duration_sec: float,
        output_path: Optional[str] = None,
    ) -> str:
        """Loop a short video clip to fill a target duration using ffmpeg."""
        if not output_path:
            stem = Path(video_path).stem
            mins = int(target_duration_sec / 60)
            output_path = str(self.output_dir / f"{stem}_{mins}min.mp4")

        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1",
            "-i", video_path,
            "-t", str(target_duration_sec),
            "-an",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            output_path,
        ]

        print(f"  Looping video to {target_duration_sec / 60:.0f} minutes...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg loop failed: {result.stderr[-500:]}")

        print(f"  Looped video: {output_path}")
        return output_path

    def combine_audio_video(
        self,
        video_path: str,
        audio_path: str,
        output_path: Optional[str] = None,
    ) -> str:
        """Combine a video and audio file into a final YouTube-ready MP4."""
        if not output_path:
            stem = Path(video_path).stem
            output_path = str(self.output_dir / f"{stem}_final.mp4")

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "320k",
            "-cutoff", "20000",
            "-shortest",
            output_path,
        ]

        print(f"  Combining audio + video...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg combine failed: {result.stderr[-500:]}")

        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"  Final video: {output_path} ({size_mb:.1f} MB)")
        return output_path
