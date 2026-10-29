# Adapters

The filed declaration is one structured object — `header`, `items`,
`discrepancies`, `open_questions`, `review` — and each adapter maps that same
object to one target format:

* `sad_pdf.py` — the SAD as a two-page PDF (numbered boxes, then evidence).
* `sad_xml.py` — the same declaration as XML, one element per SAD box.
* `asycuda_stub.py` — the field map to ASYCUDA World, raising until DTI access lands.

`common.py` holds what the adapters share: the broker identity (box 14),
the office of entry (box 29), and the cited-field-to-box map for the evidence
page. Boxes 46/47 hold no rates of their own: they render the declaration's
`duty_estimate`, computed by the agent's `compute_duty` tool against the
country tariff pack (`tariff/<pack>.json`).
