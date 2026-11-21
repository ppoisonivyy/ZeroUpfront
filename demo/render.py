"""Cut the measured browser recording into a silent 30-second film and burn in its captions."""

import json
import os
import shutil
import subprocess
from argparse import ArgumentParser
from itertools import accumulate
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FPS = 30
DURATIONS = {1: 3, 2: 1, 3: 1, 4: 4, 5: 3, 6: 2, 61: 2, 62: 2, 70: 1, 7: 2, 8: 1, 9: 5, 10: 3}


def ffmpeg_binary():
    candidates = [
        os.getenv("FFMPEG"),
        shutil.which("ffmpeg"),
        "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
    ]
    for exe in filter(None, candidates):
        if Path(exe).is_file() and " ass " in subprocess.check_output(
            [exe, "-hide_banner", "-filters"], text=True, stderr=subprocess.STDOUT
        ):
            return exe
    raise SystemExit(
        "Install FFmpeg with libass support (on Homebrew, ffmpeg-full), or set FFMPEG."
    )


def run(*args):
    subprocess.run(args, check=True, stdin=subprocess.DEVNULL)


def timestamp(seconds, ass=False):
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if ass:
        return f"{hours}:{minutes:02}:{secs:02}.00"
    return f"{hours:02}:{minutes:02}:{secs:02},000"


def locate(pixels, color, start=0):
    for n in range(start, len(pixels) // 3):
        if max(abs(c - pixels[3 * n + i]) for i, c in enumerate(color)) < 18:
            return n
    raise RuntimeError(f"Video timing marker missing: {color}")


def render(metadata, raw, dest, scratch):
    exe = ffmpeg_binary()
    scenes = metadata["scenes"]
    if not scenes or scenes[0]["id"] != 1 or scenes[-1]["id"] != 10:
        raise ValueError("The recording must contain its opening and closing cards.")
    # The export bar covers these recording-only color markers. Reading their pixels aligns
    # cuts to actual video frames, independently of Chromium startup or machine speed.
    pixels = subprocess.check_output(
        [
            exe,
            "-v",
            "error",
            "-i",
            str(raw),
            "-vf",
            "fps=25,crop=8:8:12:1062,scale=1:1,format=rgb24",
            "-f",
            "rawvideo",
            "-an",
            "-",
        ]
    )
    weights = [DURATIONS.get(scene["id"], 8) for scene in scenes[1:-1]]
    ends = [round(24 * x / sum(weights)) for x in accumulate(weights)]
    lengths = [3] + [b - a for a, b in zip([0] + ends, ends)] + [3]
    cursor = timeline = 0
    cues, parts, chapters = [], [], []
    for i, (scene, length) in enumerate(zip(scenes, lengths)):
        lo = locate(pixels, scene["start"], cursor)
        hi = locate(pixels, scene["end"], lo + 1)
        cursor = hi
        # Exclude the initial synchronization hold. Keep the end-of-step settling hold.
        begin, finish = (lo + 7) / 25, hi / 25
        actual = max(0.12, finish - begin)
        caption = scene["caption"]
        if caption:
            if cues and cues[-1][1] == timeline and cues[-1][2] == caption:
                cues[-1] = (cues[-1][0], timeline + length, caption)
            else:
                cues.append((timeline, timeline + length, caption))
        chapters.append(
            {"step": scene["id"], "start": timeline, "end": timeline + length}
        )
        timeline += length
        target = scratch / f"cut-{i:02}.mp4"
        if scene["id"] in {1, 10}:
            vf = "fps=30,tpad=stop_mode=clone:stop_duration=4"
        else:
            # Accelerate navigation while reserving a distinct, readable result hold.
            hold = 4.0 if scene["id"] == 9 else min(2.5, length * 0.65)
            action_time = max(
                0.15, actual - min(actual * 0.8, 2.5 if scene["id"] != 9 else 4)
            )
            if scene["id"] in {61, 62}:
                hold = 1.15
            moving = min(action_time, length - hold)
            ratio = moving / action_time
            vf = (
                f"setpts=PTS-STARTPTS,setpts='if(lt(T,{action_time:.5f}),PTS*{ratio:.8f},"
                f"({moving:.5f}+T-{action_time:.5f})/TB)',fps=30,tpad=stop_mode=clone:stop_duration={length}"
            )
        if frame := scene.get("frame"):
            vf += ",crop={width}:{height}:{x}:{y},scale=1920:1080:flags=lanczos".format(**frame)
        mask = (
            "drawbox=x=0:y=ih-32:w=48:h=32:color=0x1F4D3F:t=fill"
            if scene["id"] in {1, 10}
            else "drawbox=x=0:y=ih-86:w=iw:h=86:color=0x1F4D3F:t=fill"
        )
        run(
            exe,
            "-v",
            "error",
            "-y",
            "-ss",
            f"{begin:.3f}",
            "-t",
            f"{actual:.3f}",
            "-i",
            str(raw),
            "-vf",
            vf + "," + mask,
            "-frames:v",
            str(length * FPS),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "17",
            "-pix_fmt",
            "yuv420p",
            str(target),
        )
        parts.append(target)
    assert timeline == 30
    srt = dest / "captions.srt"
    srt.write_text(
        "".join(
            f"{i}\n{timestamp(a)} --> {timestamp(b)}\n{s}\n\n"
            for i, (a, b, s) in enumerate(cues, 1)
        )
    )
    ass = scratch / "captions.ass"
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Caption,Arial,40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,36,36,25,1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    ass.write_text(
        header
        + "".join(
            f"Dialogue: 0,{timestamp(a, True)},{timestamp(b, True)},Caption,,0,0,0,,{s}\n"
            for a, b, s in cues
        )
    )
    listing = scratch / "cuts.txt"
    listing.write_text("".join(f"file '{file.name}'\n" for file in parts))
    movie = dest / "zeroupfront-demo.mp4"
    # Use a relative libass filename, avoiding platform-specific path and escaping rules.
    subprocess.run(
        [
            exe,
            "-v",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            listing.name,
            "-vf",
            "ass=captions.ass",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-maxrate",
            "3600k",
            "-bufsize",
            "6000k",
            "-r",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(movie),
        ],
        cwd=scratch,
        check=True,
    )
    probe = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(movie),
            ]
        )
    )
    streams = probe["streams"]
    assert len(streams) == 1 and streams[0]["codec_name"] == "h264"
    assert (
        streams[0]["width"],
        streams[0]["height"],
        streams[0]["avg_frame_rate"],
    ) == (1920, 1080, "30/1")
    assert (
        abs(float(probe["format"]["duration"]) - 30) < 0.05
        and movie.stat().st_size < 50_000_000
    )
    (scratch / "verified.json").write_text(
        json.dumps(
            {
                "chapters": chapters,
                "skipped": metadata["skipped"],
                "bytes": movie.stat().st_size,
            },
            indent=2,
        )
    )
    print(
        f"{movie}\n30.00 seconds; {movie.stat().st_size / 1_000_000:.2f} MB; silent H.264"
    )
    if not metadata["skipped"]:
        print("Skipped scenes: none")
    for step in metadata["skipped"]:
        print(f"Skipped step {step['id']}: {step['reason']}")


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("metadata", type=Path)
    parser.add_argument("video", type=Path)
    args = parser.parse_args()
    render(
        json.loads(args.metadata.read_text()),
        args.video,
        ROOT / "demo",
        args.metadata.resolve().parent,
    )
