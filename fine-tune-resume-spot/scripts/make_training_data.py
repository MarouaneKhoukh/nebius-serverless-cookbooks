"""Recreate the bundled original synthetic training fixture (no customer data)."""

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from evaluate import SYSTEM_PROMPT

CASES = {
    "billing": [
        "The tax amount on my latest invoice looks incorrect.",
        "My card was charged twice for the same monthly plan.",
        "Can I get a refund for the annual subscription I bought yesterday?",
        "What is the price difference between monthly and yearly billing?",
        "I need to replace the credit card used for subscription payments.",
        "Please send a receipt for last month's payment.",
        "My subscription renewed even though I cancelled it.",
        "The invoice is missing my company's tax registration number.",
        "I cannot apply the promotional discount at checkout.",
        "Our purchase order number needs to appear on the invoice.",
        "The bank rejected my payment but the invoice still says paid.",
        "How can we pay our outstanding balance by bank transfer?",
        "I want to downgrade the paid plan before the next renewal.",
        "The subscription amount increased without explanation.",
        "Can you switch our invoice currency for future payments?",
        "I need a credit note for the duplicate invoice.",
        "Please explain the extra usage charges on this month's bill.",
        "I paid for three seats but the invoice charged for five.",
        "Our finance team needs a breakdown of the subscription fees.",
        "When will the refund appear on my credit card statement?",
    ],
    "technical": [
        "Exporting a CSV returns an internal server error.",
        "Our configured webhook never receives event notifications.",
        "The dashboard chart remains blank after the data upload.",
        "The mobile application crashes when I attach a photo.",
        "Search results take over a minute to load.",
        "The API returns a malformed JSON response for this request.",
        "The Slack integration stopped syncing messages.",
        "The uploaded PDF preview shows only a white page.",
        "Our scheduled report is not generated at the selected time.",
        "The download link returns a 404 error.",
        "Video playback freezes after the first few seconds.",
        "The date filter changes the wrong part of the dashboard.",
        "The browser tab uses too much memory during import.",
        "API requests time out after the latest software update.",
        "The spreadsheet connector duplicates the imported rows.",
        "The image editor saves a corrupted output file.",
        "Notifications are delayed even when the service is online.",
        "The text editor loses line breaks when I save.",
        "The bulk upload progress indicator never finishes.",
        "The application displays the wrong timezone on exported reports.",
    ],
    "account": [
        "I lost my two-factor authentication device and cannot sign in.",
        "Please help me reset the password for my profile.",
        "How can I change the email address linked to my account?",
        "My administrator invited me but I cannot join the workspace.",
        "I need permission to view a restricted team project.",
        "The login page says my account has been locked.",
        "I want to update the display name on my profile.",
        "How do I transfer workspace ownership to another teammate?",
        "Please remove an old team member's access to our account.",
        "I am not receiving the password reset email.",
        "I can sign in but my team workspace is missing.",
        "How do I enable single sign-on for my organization?",
        "My invitation expired before I could create a profile.",
        "Please grant me the editor role in the shared workspace.",
        "I want to close my personal account and remove its profile.",
        "My profile picture has not updated across the account.",
        "Can I add a second email address for account recovery?",
        "An unfamiliar device appears in my active login sessions.",
        "I accidentally joined the wrong organization with my account.",
        "How can I revoke a teammate's administrator permissions?",
    ],
}


def main():
    path = ROOT / "data/train.jsonl"
    rows = []
    for label, cases in CASES.items():
        for prefix in ("Please help with this request: ", "Our team needs support. "):
            for case in cases:
                rows.append({"messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prefix + case},
                    {"role": "assistant", "content": label},
                ]})
    random.Random(42).shuffle(rows)
    path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")
    if path.stat().st_size > 65536:
        raise ValueError("Training fixture exceeds Nebius's injected-file limit")
    print(f"Wrote {len(rows)} synthetic examples ({path.stat().st_size} bytes) to {path}")


if __name__ == "__main__":
    main()
