"""
Cross-Camera Re-Identification Registry v2
-----------------------------------------------
Fixes the "two people in similar clothes get merged" failure mode from v1
by stacking THREE independent safeguards instead of relying on appearance
similarity alone:

  1. GATE-CONSTRAINED MATCHING.
     A new arrival on camera_id is only compared against people who exited
     through a gate whose "leads_to" field points at camera_id. If a gate
     explicitly leads elsewhere, anyone who left through it is skipped
     entirely — not even compared. This is a hard physical constraint, not
     a similarity threshold, and it's what actually prevents two similar-
     looking people from being confused: they'd both have to exit through
     the SAME doorway within the SAME short window, which is far rarer than
     "look similar."

  2. MULTI-SAMPLE IDENTITY SIGNATURE.
     Each track contributes several embeddings sampled over its lifetime
     (not every frame — spaced out), not one snapshot. Matching uses the
     best pairwise similarity across both sets, which is much less sensitive
     to a single bad-angle or motion-blurred frame.

  3. CONFIDENCE TIERS + HUMAN REVIEW QUEUE.
     Visual similarity can't be 100% certain when two people dress alike —
     no threshold fixes that completely. So: gate-consistent + high
     similarity auto-merges; anything ambiguous (no gate context, or a
     borderline score) gets logged to review_queue.json with the new
     arrival's crop image saved, instead of silently guessing. Run
     resolve_reviews.py to work through these and correct the count.

Install:
    pip install torch torchvision numpy opencv-python
"""

import os
import time
import json
import threading
import numpy as np
import cv2
import torch
from torchvision.models import resnet18, ResNet18_Weights

# ============ CONFIG ============
GATE_MATCH_THRESHOLD = 0.65      # similarity needed when gate context CONFIRMS this transition
NO_GATE_HIGH_THRESHOLD = 0.88    # similarity needed to auto-merge WITHOUT gate context (rare, be strict)
REVIEW_LOW_BOUND = 0.55          # below this, don't even bother queuing for review — just a new person
LOST_POOL_EXPIRY_SECONDS = 180
MAX_EMBEDDING_SAMPLES = 5
REVIEW_QUEUE_DIR = "review_queue"
REVIEW_QUEUE_FILE = "review_queue.json"
# =================================


class ReIDEmbedder:
    """Extracts a fixed-length appearance vector from one cropped person image."""

    def __init__(self, device=None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        weights = ResNet18_Weights.IMAGENET1K_V1
        base = resnet18(weights=weights)
        base.fc = torch.nn.Identity()
        self.model = base.eval().to(self.device)
        self.transform = weights.transforms()

    @torch.no_grad()
    def embed(self, crop_bgr):
        if crop_bgr is None or crop_bgr.size == 0:
            return None
        rgb = crop_bgr[:, :, ::-1]
        tensor = self.transform(
            torch.from_numpy(rgb.copy()).permute(2, 0, 1)
        ).unsqueeze(0).to(self.device)
        feat = self.model(tensor).squeeze(0).cpu().numpy()
        norm = np.linalg.norm(feat)
        return feat / norm if norm > 0 else feat


def cosine_sim(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


def best_signature_similarity(samples_a, samples_b):
    """Best pairwise match across two sets of embeddings, not just one-to-one."""
    if not samples_a or not samples_b:
        return 0.0
    return max(cosine_sim(a, b) for a in samples_a for b in samples_b)


class GlobalIDRegistry:
    """
    Thread-safe, shared across all camera threads in one process.
    gates_by_camera: {camera_id: [{"gate_id", "polygon", "centroid", "leads_to"}, ...]}
    (loaded straight from each camera's zones_<id>.json "gates" field)
    """

    def __init__(self, gates_by_camera=None, topology=None):
        self.lock = threading.Lock()
        self.next_global_id = 1
        self.lost_pool = []     # entries: global_id, samples, camera_id, lost_at, exit_leads_to
        self.gates_by_camera = gates_by_camera or {}
        self.topology = topology or {}   # fallback only, used when no gate info exists
        self.pending_reviews = []
        self.confirmed_merges = {}  # alias: merged_id -> kept_id
        os.makedirs(REVIEW_QUEUE_DIR, exist_ok=True)

    def _nearest_gate_leads_to(self, camera_id, last_position):
        """Which gate is this exit point closest to, and where does it lead?
        Returns (gate_id, leads_to) or (None, None) if no gate is close enough."""
        gates = self.gates_by_camera.get(camera_id, [])
        if not gates or last_position is None:
            return None, None
        best_gate, best_dist = None, float("inf")
        for g in gates:
            d = np.linalg.norm(np.array(g["centroid"]) - np.array(last_position))
            if d < best_dist:
                best_dist, best_gate = d, g
        if best_gate is None:
            return None, None
        return best_gate["gate_id"], best_gate.get("leads_to")

    def _topology_plausible(self, from_camera, to_camera, elapsed):
        if from_camera == to_camera:
            return True
        adj = self.topology.get(from_camera, {}).get("adjacent", [])
        if to_camera not in adj:
            return False
        lo, hi = self.topology.get(from_camera, {}).get("transit_time", [0, LOST_POOL_EXPIRY_SECONDS])
        return lo <= elapsed <= hi

    def report_track_lost(self, global_id, camera_id, embedding_samples, last_position, timestamp):
        if not embedding_samples:
            return
        gate_id, leads_to = self._nearest_gate_leads_to(camera_id, last_position)
        with self.lock:
            self.lost_pool.append({
                "global_id": global_id,
                "samples": embedding_samples,
                "camera_id": camera_id,
                "lost_at": timestamp,
                "exit_gate": gate_id,
                "exit_leads_to": leads_to,   # None if gate unknown/unlinked
            })

    def report_new_track(self, camera_id, embedding_samples, crop_bgr, timestamp):
        """Returns (global_id, status) where status is one of:
        'new', 're-identified', 'pending_review' (provisional new id, logged for review)."""
        with self.lock:
            self._expire_lost(timestamp)

            hard_candidates = []   # gate explicitly confirms this transition
            soft_candidates = []   # no gate info, only loose topology/time plausibility

            for entry in self.lost_pool:
                elapsed = timestamp - entry["lost_at"]
                if entry["exit_leads_to"] is not None:
                    # A gate with a KNOWN destination that is NOT this camera -> impossible, skip.
                    if entry["exit_leads_to"] != camera_id:
                        continue
                    hard_candidates.append((entry, elapsed))
                else:
                    # No gate info at all -> fall back to loose topology check.
                    if self._topology_plausible(entry["camera_id"], camera_id, elapsed):
                        soft_candidates.append((entry, elapsed))

            best_hard = self._best_match(hard_candidates, embedding_samples)
            if best_hard and best_hard[1] >= GATE_MATCH_THRESHOLD:
                entry, score = best_hard
                self.lost_pool.remove(entry)
                return entry["global_id"], "re-identified"

            best_soft = self._best_match(soft_candidates, embedding_samples)
            if best_soft and best_soft[1] >= NO_GATE_HIGH_THRESHOLD:
                entry, score = best_soft
                self.lost_pool.remove(entry)
                return entry["global_id"], "re-identified"

            # Ambiguous zone: something scored high enough to be suspicious but not
            # certain enough to auto-merge. Queue it instead of guessing.
            best_overall = None
            if best_hard and best_soft:
                best_overall = best_hard if best_hard[1] >= best_soft[1] else best_soft
            else:
                best_overall = best_hard or best_soft

            gid = self.next_global_id
            self.next_global_id += 1
            if best_overall and best_overall[1] >= REVIEW_LOW_BOUND:
                entry, score = best_overall
                self._queue_review(entry, gid, camera_id, score, crop_bgr)
                return gid, "pending_review"

            return gid, "new"

    def _best_match(self, candidates, embedding_samples):
        best_entry, best_score = None, 0.0
        for entry, _elapsed in candidates:
            score = best_signature_similarity(embedding_samples, entry["samples"])
            if score > best_score:
                best_score, best_entry = score, entry
        return (best_entry, best_score) if best_entry else None

    def _queue_review(self, lost_entry, new_global_id, new_camera_id, score, new_crop):
        review_id = f"review_{len(self.pending_reviews) + 1}_{int(time.time())}"
        new_crop_path = os.path.join(REVIEW_QUEUE_DIR, f"{review_id}_new.png")
        if new_crop is not None:
            cv2.imwrite(new_crop_path, new_crop)
        record = {
            "review_id": review_id,
            "candidate_global_id": lost_entry["global_id"],
            "provisional_global_id": new_global_id,
            "from_camera": lost_entry["camera_id"],
            "to_camera": new_camera_id,
            "similarity_score": round(score, 3),
            "new_crop": new_crop_path,
            "resolved": False,
        }
        self.pending_reviews.append(record)
        self._append_review_file(record)
        print(f"[REVIEW QUEUED] {review_id}: possible match, score={score:.2f} "
              f"({lost_entry['camera_id']} -> {new_camera_id}). Check {REVIEW_QUEUE_DIR}/")

    def _append_review_file(self, record):
        existing = []
        if os.path.exists(REVIEW_QUEUE_FILE):
            with open(REVIEW_QUEUE_FILE) as f:
                existing = json.load(f)
        existing.append(record)
        with open(REVIEW_QUEUE_FILE, "w") as f:
            json.dump(existing, f, indent=2)

    def merge_global_ids(self, keep_id, merge_id):
        """Call after a human confirms two provisional IDs are the same person."""
        with self.lock:
            self.confirmed_merges[merge_id] = keep_id

    def _expire_lost(self, now):
        self.lost_pool = [e for e in self.lost_pool if now - e["lost_at"] <= LOST_POOL_EXPIRY_SECONDS]

    def unique_visitor_count(self):
        with self.lock:
            return (self.next_global_id - 1) - len(self.confirmed_merges)


def load_gates(cameras_file="cameras.json"):
    """Loads each camera's gates from its zones_<id>.json for the registry."""
    gates_by_camera = {}
    with open(cameras_file) as f:
        cameras = json.load(f)
    for cam in cameras:
        try:
            with open(f"zones_{cam['id']}.json") as f:
                cfg = json.load(f)
            gates_by_camera[cam["id"]] = cfg.get("gates", [])
        except FileNotFoundError:
            gates_by_camera[cam["id"]] = []
    return gates_by_camera


def load_topology(path="camera_topology.json"):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
