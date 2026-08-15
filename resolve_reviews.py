"""
Review Queue Resolver
--------------------------
Works through review_queue.json — the ambiguous Re-ID matches the live
dashboard wasn't confident enough to auto-merge. For each one, open the
saved crop image, decide if it's really the same person as the candidate
who was lost around that time, and answer here. Confirmed duplicates get
written to confirmed_merges.json so daily/weekly totals can be corrected.

This does NOT need to run while the dashboard is live — it's meant as an
end-of-day (or end-of-shift) pass, the same rhythm as reviewing incident
reports.

Usage:
    python resolve_reviews.py
"""

import json
import os

REVIEW_QUEUE_FILE = "review_queue.json"
MERGES_FILE = "confirmed_merges.json"


def main():
    if not os.path.exists(REVIEW_QUEUE_FILE):
        print("No review_queue.json found — nothing to review yet.")
        return

    with open(REVIEW_QUEUE_FILE) as f:
        reviews = json.load(f)

    merges = {}
    if os.path.exists(MERGES_FILE):
        with open(MERGES_FILE) as f:
            merges = json.load(f)

    pending = [r for r in reviews if not r["resolved"]]
    if not pending:
        print("No pending reviews.")
        return

    print(f"{len(pending)} pending review(s).\n")
    for r in pending:
        print(f"--- {r['review_id']} ---")
        print(f"  Candidate global#{r['candidate_global_id']} (last seen on {r['from_camera']})")
        print(f"  vs. new arrival global#{r['provisional_global_id']} (on {r['to_camera']})")
        print(f"  Similarity score: {r['similarity_score']}")
        print(f"  New arrival's crop image: {r['new_crop']}")
        print(f"  (Open that image and compare against your own footage/memory of "
              f"global#{r['candidate_global_id']} if needed.)")
        answer = input("  Same person? [y/n/skip]: ").strip().lower()

        if answer == "y":
            merges[str(r["provisional_global_id"])] = r["candidate_global_id"]
            r["resolved"] = True
            print(f"  -> Merged: global#{r['provisional_global_id']} is now counted as "
                  f"global#{r['candidate_global_id']}.\n")
        elif answer == "n":
            r["resolved"] = True
            print("  -> Kept as two separate visitors.\n")
        else:
            print("  -> Skipped, will ask again next run.\n")

    with open(REVIEW_QUEUE_FILE, "w") as f:
        json.dump(reviews, f, indent=2)
    with open(MERGES_FILE, "w") as f:
        json.dump(merges, f, indent=2)

    print(f"Done. {len(merges)} confirmed merge(s) total — subtract this many from "
          f"any raw unique-visitor count pulled from the dashboard's running total.")


if __name__ == "__main__":
    main()
