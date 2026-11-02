# Failure gold

The failure finder's gold: given a photo of a failed part, which NTSB report figure shows the
same failure, which section of the report it belongs to, and what the failure mode is. A photo
that no report covers, such as a drawing or a logo, should match nothing.

- `cases.jsonl` has one line per case: its image, its kind, and for a photo of a report figure
  the expected report, figure, section and failure mode.
- `images/` holds the 149 images the cases own. The five unrelated cases point at files of the
  router gold in `../routes/items/other/`, so those are not copied.
- `../../../data/reports/sections.toml` says which section and failure mode each figure shows.
  The expected labels here agree with it.

| Kind | Cases | What they are |
| --- | --- | --- |
| positive | 138 | 3 perturbed copies of each of the 46 figures in the three reports |
| negative_drawing | 11 | page 1 of each NIST drawing, rendered at 100 dpi |
| negative_unrelated | 5 | 2 report logos, 2 report text pages as images, 1 physics diagram |

## Fields

    case_id            stable name, such as pos_18-061_fig06_v1
    image              the image, relative to this folder
    kind               positive, negative_drawing or negative_unrelated
    expected_report    16-006, 18-061, 24-013, or none for a negative
    expected_figure    <report>/fig<nn>, for a positive
    section            the part and assembly the figure is about
    failure_mode       heat_damage, jam_corrosion, fatigue, overstress or reference_no_defect
    failure_keywords   word starts an answer about this failure should use, as the answer evals check
    perturbations      what was done to the figure: crop, rotation, colour, blur, downscale
    unit               what a split keeps on one side: a figure with its copies, or one negative

## How it was made

Each figure was cut from its report and perturbed three times with seed 0: a random crop keeping
60 to 90% of each side, then by chance a rotation, a colour shift, a blur and a downscale, saved
as JPEG at quality 35 to 85. The labels were assigned by hand from the report text, by figure
range.

The positives are copies of the figures a finder indexes. The failure and answer evals hide each
case's own figure from the search, so the best hit must be another figure of its section;
`failure-copy` keeps it in, which only tests matching under damage.

## Licences

The NTSB reports and the NIST drawings are works of the US government. The physics diagram is
CC BY-SA 4.0; its author and page are in `../routes/commons.json`.
