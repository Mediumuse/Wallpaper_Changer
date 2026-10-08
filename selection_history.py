import hashlib
import json
import os
import random

from artist_blurbs import normalize_file_title
from app_paths import get_app_data_dir


def get_selection_state_path(gallery_page):
    gallery_id = hashlib.sha256(gallery_page.casefold().encode("utf-8")).hexdigest()[:16]
    return os.path.join(get_app_data_dir(), "selection", f"{gallery_id}.json")


def _read_state(state_path):
    try:
        with open(state_path, "r", encoding="utf-8") as state_file:
            state = json.load(state_file)
    except FileNotFoundError:
        return {"remaining": [], "last_used": None}
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(f"Could not read selection history {state_path}: {e}") from e

    if not isinstance(state, dict):
        raise ValueError(f"Selection history {state_path} must contain a JSON object.")
    remaining = state.get("remaining", [])
    last_used = state.get("last_used")
    if not isinstance(remaining, list) or not all(
        isinstance(title, str) for title in remaining
    ):
        raise ValueError(f"Selection history {state_path} has an invalid remaining list.")
    if last_used is not None and not isinstance(last_used, str):
        raise ValueError(f"Selection history {state_path} has an invalid last_used value.")

    return {"remaining": remaining, "last_used": last_used}


def _write_state(state_path, state):
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    temporary_path = f"{state_path}.tmp"
    try:
        with open(temporary_path, "w", encoding="utf-8") as state_file:
            json.dump(state, state_file, ensure_ascii=False, indent=2)
        os.replace(temporary_path, state_path)
    except OSError as e:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise OSError(f"Could not save selection history {state_path}: {e}") from e


def choose_random_candidates(images, state_path, count=3, rng=None, previous_image=None):
    if count <= 0:
        return []

    rng = rng or random.SystemRandom()
    available = {}
    for title in images:
        key = normalize_file_title(title)
        if key not in available:
            available[key] = title
    if not available:
        return []

    state = _read_state(state_path)
    remaining = []
    seen = set()
    for title in state["remaining"]:
        key = normalize_file_title(title)
        if key in available and key not in seen:
            remaining.append(available[key])
            seen.add(key)

    new_images = [
        title for key, title in available.items() if key not in seen
    ]
    rng.shuffle(new_images)
    remaining.extend(new_images)

    if not remaining:
        remaining = list(available.values())
        rng.shuffle(remaining)

    avoid_key = normalize_file_title(previous_image) if previous_image else None
    last_key = normalize_file_title(state["last_used"]) if state["last_used"] else None
    cycle_boundary = not state["remaining"] or not remaining
    for repeat_key in (avoid_key, last_key if cycle_boundary else None):
        if repeat_key and len(remaining) > 1:
            repeat_index = next(
                (
                    index
                    for index, title in enumerate(remaining)
                    if normalize_file_title(title) == repeat_key
                ),
                None,
            )
            if repeat_index == 0:
                remaining.append(remaining.pop(0))

    selected = remaining[:count]
    leftover = remaining[count:]
    state["remaining"] = leftover
    if selected:
        state["last_used"] = selected[-1]
    _write_state(state_path, state)
    return selected
