# Write the two reports
From the sealed findings (final, one per obligation), write one report for the AI engineer and one for management. Code appends the evidence register and the gap list.

- Engineer (`engineer_markdown`): pins (`kb_version`, dossier, config, model version, seeds), what was tested and how to reproduce it (dataset sha256, predictions sha256, MLflow run ids), each tested obligation's verdict with its evidence and counter-arguments, documentary obligations with evidence present/missing, limitations, and what to fix first.
- Management: a one-line headline, a traffic light per obligation (`red` = gap, `amber` = partial/inconclusive, `green` = pass, `grey` = not assessable by testing / not applicable) with a one-line note, the decisions they need to take, next steps.
- Use only the findings and artifacts in the brief; say which thresholds are organisational. Never change a verdict.
- Bar: an engineer can rerun every test from the report; a manager can act on the first screen.
- Each finding's `register_status` (`new`, `still_open`, `resolved`, `regressed`, `accepted_risk`, `unchanged`) and `register`: say per obligation what changed since the earlier audits (fixed, still open since <audit>, regressed); list accepted risks with their reason, separately from new gaps.
