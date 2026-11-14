# Write the two reports
From the findings after the critic's review, write one report for the AI engineer and one for management.

- Engineer (`engineer_markdown`): what was tested and how to reproduce it (model, plugin, `kb_version`, dataset id and seed, MLflow run ids), each finding with its evidence and counter-evidence, limitations, and what to fix first.
- Management: a one-line headline, a traffic light per requirement (`red` = gap, `amber` = inconclusive or weakened, `green` = supports compliance, `grey` = not assessable by testing) with a one-line note, the decisions they need to take, and next steps.
- Use only the findings, critic reviews and artifacts in the brief; say which thresholds are organisational.
- Bar: an engineer can rerun every test from the report; a manager can act on the first screen.
