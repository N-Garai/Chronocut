"""Child-process worker for local text-to-video generation.

Run as ``python -m app.tools.videoagen._worker --prompt ... --out ...``.
Downloads/loads the configured diffusers model, renders a short silent clip
and exits non-zero with a short stderr tail on any failure. Kept free of
app imports (except stdlib/argparse) so it stays cheap to spawn.
"""
import argparse
import os
import sys


def _log(msg: str) -> None:
    print(f"[videoagen] {msg}", file=sys.stderr, flush=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--prompt", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--seconds", type=float, default=4.0)
    p.add_argument("--width", type=int, default=480)
    p.add_argument("--height", type=int, default=320)
    p.add_argument("--model", default="Wan-AI/Wan2.1-T2V-1.3B")
    args = p.parse_args()

    try:
        import torch
    except Exception as e:
        _log(f"torch unavailable: {e}")
        return 2

    try:
        from diffusers.utils.export_utils import export_to_video
    except Exception:
        from diffusers.utils import export_to_video  # older layouts

    model = args.model
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    _log(f"loading {model} ({'cuda' if torch.cuda.is_available() else 'cpu'})…")

    pipe = None
    fps = 8
    num_frames = max(9, min(int(args.seconds * fps) | 1, 33))
    call = {"prompt": args.prompt, "num_frames": num_frames,
            "height": args.height, "width": args.width}

    try:
        if "wan" in model.lower():
            from diffusers import WanPipeline
            pipe = WanPipeline.from_pretrained(model, torch_dtype=dtype)
            fps = 16
            num_frames = max(5, min(int(args.seconds * fps) | 1, 33))
            call = {"prompt": args.prompt, "num_frames": num_frames,
                    "height": args.height, "width": args.width}
        elif "cogvideox" in model.lower():
            from diffusers import CogVideoXPipeline
            pipe = CogVideoXPipeline.from_pretrained(model, torch_dtype=dtype)
        else:
            from diffusers import DiffusionPipeline
            pipe = DiffusionPipeline.from_pretrained(model, torch_dtype=dtype)
    except Exception as e:
        _log(f"pipeline load failed: {type(e).__name__}: {str(e)[:300]}")
        return 3

    try:
        if torch.cuda.is_available():
            pipe.to("cuda")
        else:
            try:
                pipe.enable_model_cpu_offload()
            except Exception:
                pass
        for opt in ("enable_attention_slicing", "enable_vae_slicing", "enable_vae_tiling"):
            try:
                getattr(pipe, opt)()
            except Exception:
                pass
    except Exception as e:
        _log(f"acceleration setup skipped: {e}")

    try:
        result = pipe(**call)
        frames = result.frames[0] if hasattr(result, "frames") else result[0][0]
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        export_to_video(frames, args.out, fps=fps)
    except TypeError:
        # Model family with a narrower call signature — retry minimal.
        try:
            result = pipe(prompt=args.prompt)
            frames = result.frames[0] if hasattr(result, "frames") else result[0][0]
            export_to_video(frames, args.out, fps=fps)
        except Exception as e:
            _log(f"generation failed: {type(e).__name__}: {str(e)[:300]}")
            return 4
    except Exception as e:
        _log(f"generation failed: {type(e).__name__}: {str(e)[:300]}")
        return 4

    _log(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
