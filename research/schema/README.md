# Which JSON shape a drawing turns into

**Answer:** a flat list of value records (option A), plus a flat `features` list at the drawing level.
Each value gets a `feature_id` that points into that list, and a `limits` field with the lower and upper bound.
Nothing is nested, so grouping by feature (option B) and an inspection ledger (option C) are joins over the same data.
The reverse is not true: B and C cannot be turned back into what was printed on the sheet.
The full comparison, with the same 17 callouts from drawing CTC-01 written in each shape, is in [`review.html`](review.html).

## Why

- The extractor reads one callout at a time, which is how the page looks to it. Grouping callouts into features is the hardest step on a 3D view like CTC-01, so putting it in the stored shape adds the riskiest judgement to every record.
- A flat record is the easiest to label and to score: a prediction matches a gold record or it does not.
- Every record keeps `raw`, the text as printed, so a disagreement can be traced back to the sheet.
- The eval matches on value, unit and kind. These can be checked by a person without interpretation. `meaning` is the only free text and is judged by a rubric.
- Names follow ASME Y14.5, the standard the NIST drawings use.

## Options compared

| Criterion | A flat list | B feature tree | C ledger |
| --- | --- | --- | --- |
| Newcomer can read it | good | fair | poor |
| Inspector can use it | fair | good | good |
| Platform can index it | good | fair (nested) | good |
| Extraction risk added by the shape | low | high (grouping) | medium (limit rules) |
| Gold labelling effort | lowest | highest | medium |
| Scoring | direct match | flatten first | direct match on limits |
| Traceable to what was printed | yes (`raw`) | partly | no, unless `raw` is kept |

## Decisions taken

- Option A with `feature_id` and `limits` is the stored shape.
- The 17 CTC-01 records become the first gold file once corrected.
