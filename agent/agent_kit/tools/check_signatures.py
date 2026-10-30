"""check_signatures (verification on): is the signature on one page consistent with a
genuine reference signature of the same person on another page?

The agent names both pages: the page to check, and a page the signer genuinely signed.
SAM 3.1 segments the signature or stamp on each page image (segment, below); the
largest region on each page is cropped and both crops go to Muse Spark, which judges
whether they are by the same hand. The verdict is one of VERDICTS. Anything other
than "consistent" becomes a signature flag the broker reviews at sign-off, and the
declaration rules refuse a finding marked proven on that signature. It is a
consistency check, not forgery detection.
"""

from __future__ import annotations

import base64
import json
import re
from io import BytesIO
from pathlib import Path
from typing import cast, TYPE_CHECKING

from openai import OpenAI
from openai.types.responses import Response
from PIL import Image

from .. import document_text
from ..settings import sam_model

if TYPE_CHECKING:
    from . import Context

VERDICTS = ("consistent", "inconsistent", "unclear", "unsigned", "no_signature_found")

DEFINITION = {
    "type": "function",
    "name": "check_signatures",
    "description": "Check whether the signature presented as the signer's on one page is consistent with a "
    "genuine signature of the same person on another page (the reference: a page you know they signed). "
    "Returns consistent, inconsistent, unclear, unsigned, or no_signature_found. Check a signature before "
    "relying on it for a checklist item.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "document_id": {
                "type": "string",
                "description": "the document whose signature you are checking",
            },
            "page": {"type": "integer"},
            "signer": {
                "type": "string",
                "description": "the person the signature is presented as",
            },
            "reference_document_id": {
                "type": "string",
                "description": "a document the signer genuinely signed",
            },
            "reference_page": {"type": "integer"},
        },
        "required": [
            "document_id",
            "page",
            "signer",
            "reference_document_id",
            "reference_page",
        ],
    },
}


def run(ctx: Context, args: dict) -> dict:
    document_id, page = str(args.get("document_id", "")), int(args.get("page") or 1)
    reference_id, reference_page = (
        str(args.get("reference_document_id", "")),
        int(args.get("reference_page") or 1),
    )
    signer = str(args.get("signer", ""))
    if (reference_id, reference_page) == (document_id, page):
        return {
            "error": "the reference must be a different page, one the signer genuinely signed"
        }
    questioned = document_text.page_image(ctx.root, document_id, page)
    reference = document_text.page_image(ctx.root, reference_id, reference_page)
    boxes = segment(ctx.client, questioned)
    reference_boxes = segment(ctx.client, reference)
    if not boxes or not reference_boxes:
        missing = " and ".join(
            label
            for label, found in (
                (f"{document_id} page {page}", boxes),
                (f"{reference_id} page {reference_page}", reference_boxes),
            )
            if not found
        )
        verdict, confidence, reason = (
            "no_signature_found",
            0.0,
            f"SAM found no signature or stamp on {missing}",
        )
    else:
        crop = crop_png(questioned, largest_box(boxes))
        reference_crop = crop_png(reference, largest_box(reference_boxes))
        judging = judge(
            ctx.client,
            signer,
            document_id,
            page,
            crop,
            reference_id,
            reference_page,
            reference_crop,
        )
        confidence = judging["confidence"]
        verdict = (
            "consistent"
            if judging["consistent"] and confidence >= 0.5
            else "inconsistent"
        )
        reason = f"{judging['reason']} (confidence {confidence:.2f})"
    ctx.case.add_signature_check(
        {
            "document_id": document_id,
            "page": page,
            "signer": signer,
            "verdict": verdict,
            "confidence": confidence,
            "reason": reason,
            "boxes": boxes,
            "reference": {
                "document_id": reference_id,
                "page": reference_page,
                "boxes": reference_boxes,
            },
        }
    )
    return {
        "document_id": document_id,
        "page": page,
        "signer": signer,
        "verdict": verdict,
        "confidence": confidence,
        "reason": reason,
    }


# ---- SAM 3.1 segmentation ------------------------------------------------------
#
# SAM returns special-token text in output_text:
#     <0f>0<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..|><|mask;...|>,1<|box;...|>...
# Only the boxes are needed. SAM 3.1 does not match "signature" on a scanned page;
# "ink scribble" finds handwritten signatures.

SIGNATURE_PROMPT = "ink scribble"
BOX = re.compile(r"(\d+)<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)\|>")


def parse_boxes(output_text: str) -> list:
    """Every box in SAM's output, in order. Empty output means zero matches."""
    boxes = []
    for match in BOX.finditer(output_text or ""):
        ordinal, x1, y1, x2, y2, w, h = (int(v) for v in match.groups())
        boxes.append(
            {
                "ordinal": ordinal,
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "width": w,
                "height": h,
            }
        )
    return boxes


def data_url(image: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(image.read_bytes()).decode()


def segment(client: OpenAI, image: Path, prompt: str = SIGNATURE_PROMPT) -> list:
    """One SAM call on one page image: the boxes it found."""
    response = client.responses.create(
        model=sam_model(),
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": data_url(image)},
                ],
            }
        ],
    )
    return parse_boxes(cast(Response, response).output_text)


def largest_box(boxes: list) -> dict:
    """The largest region: the signature or stamp, not a stray mark."""
    return max(boxes, key=lambda box: (box["x2"] - box["x1"]) * (box["y2"] - box["y1"]))


CROP_PAD = 12


def crop_png(image: Path, box: dict) -> bytes:
    """The box region of a page image, with a small margin, as PNG bytes."""
    with Image.open(image) as picture:
        picture = picture.convert("RGB")
        width, height = picture.size
        area = picture.crop(
            (
                max(0, box["x1"] - CROP_PAD),
                max(0, box["y1"] - CROP_PAD),
                min(width, box["x2"] + CROP_PAD),
                min(height, box["y2"] + CROP_PAD),
            )
        )
        buffer = BytesIO()
        area.save(buffer, format="PNG")
        return buffer.getvalue()


def crop_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


# ---- Muse Spark verdict --------------------------------------------------------

VERDICT_PROMPT = (
    "SIGNATURE VERDICT\n"
    "Two signature-or-stamp crops follow. The first is the questioned signature from "
    "{doc} page {page}, presented as {signer}. The second is the genuine reference "
    "from {ref} page {ref_page}, also presented as {signer}. Are they by the same "
    "hand? Compare stroke shape, slant, proportions, and any stamp text.\n"
    'Return only JSON: {{"consistent": true|false, "confidence": 0-1, "reason": "..."}}'
)

VERDICT_ATTEMPTS = 2


def judge(
    client: OpenAI,
    signer: str,
    doc: str,
    page: int,
    crop: bytes,
    ref: str,
    ref_page: int,
    ref_crop: bytes,
) -> dict:
    """{"consistent": bool, "confidence": 0-1, "reason": str} for two crops."""
    prompt = VERDICT_PROMPT.format(
        doc=doc, page=page, signer=signer, ref=ref, ref_page=ref_page
    )
    images = [
        {"type": "input_image", "image_url": crop_url(crop)},
        {"type": "input_image", "image_url": crop_url(ref_crop)},
    ]
    error = ""
    for _ in range(VERDICT_ATTEMPTS):
        text = prompt if not error else prompt + f"\n\nYour previous output was invalid: {error}"
        output = document_text.ask(client, [{"type": "input_text", "text": text}, *images])
        try:
            parsed = json.loads(output)
            return {
                "consistent": bool(parsed["consistent"]),
                "confidence": min(1.0, max(0.0, float(parsed["confidence"]))),
                "reason": str(parsed.get("reason", "")),
            }
        except (ValueError, KeyError, TypeError) as problem:
            error = str(problem)
    return {
        "consistent": False,
        "confidence": 0.0,
        "reason": f"the verdict was not valid JSON ({error})",
    }
