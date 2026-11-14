# ruff: noqa: E501 - verbatim act text lines
"""Small extracted-text fixtures in the shape the extract stage writes for Cellar acts."""

from __future__ import annotations

CONSOLIDATED = """02024R1689 — EN — 27.07.2026 — 001.001

| ►B | REGULATION (EU) 2024/1689 OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL |

Amended by:

| ►M1 | REGULATION (EU) 2026/1744 OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL   of 8 July 2026 | L 1744 | 1 | 24.7.2026 |

---

▼B

## CHAPTER I

GENERAL PROVISIONS

### Article 3

Definitions

For the purposes of this Regulation, the following definitions apply:

(1)

‘AI system’ means a machine-based system;

(2)

‘risk’ means the combination of the probability of an occurrence of harm and the severity of that harm;

## CHAPTER III

HIGH-RISK AI SYSTEMS

## SECTION 1

### Article 6

Classification rules for high-risk AI systems

2.
In addition to the high-risk AI systems referred to in paragraph 1, AI systems referred to in Annex III shall be considered to be high-risk.

## SECTION 2

### Article 9

Risk management system

1.
A risk management system shall be established, implemented, documented and maintained in relation to high-risk AI systems.

2.

It shall comprise the following steps:

(a)

the identification and analysis of the known and the reasonably foreseeable risks;

(b)

the estimation and evaluation of the risks that may emerge.

### Article 10

Data and data governance

▼M1

1.
High-risk AI systems shall be developed on the basis of training, validation and testing data sets that meet the quality criteria.

▼B

2.

Those practices shall concern in particular:

(f)

examination in view of possible biases that are likely to affect the health and safety of persons;

(g)

appropriate measures to detect, prevent and mitigate possible biases identified according to point (f);

## CHAPTER IV

TRANSPARENCY OBLIGATIONS

### Article 50

Transparency obligations for providers and deployers of certain AI systems

1.
Providers shall ensure that AI systems intended to interact directly with natural persons are designed so that the natural persons concerned are informed that they are interacting with an AI system.

## CHAPTER XIII

FINAL PROVISIONS

### Article 113

Entry into force and application

It shall apply from 2 August 2026.

▼M1

(c)

Chapter III, Sections 1, 2, and 3 shall apply from:

(i)

2 December 2027 as regards AI systems classified as high-risk pursuant to Article 6(2) and Annex III; and

(ii)

2 August 2028 as regards AI systems classified as high-risk pursuant to Article 6(1) and Annex I;

▼B

## ANNEX III

High-risk AI systems referred to in Article 6(2)

4.

Employment, workers’ management and access to self-employment:

(a)

AI systems intended to be used for the recruitment or selection of natural persons;

(b)

AI systems intended to be used to make decisions affecting terms of work-related relationships;
"""

OMNIBUS = """# REGULATION (EU) 2026/1744

Whereas:

| (1) | Simplification is needed. |
| --- | --- |

HAVE ADOPTED THIS REGULATION:

### Article 1

Amendments to Regulation (EU) 2024/1689

Regulation (EU) 2024/1689 is amended as follows:

| (1) | in Article 10(1), the first subparagraph is replaced by the following: ‘1. High-risk AI systems ...’ |
| --- | --- |

| (2) | in Article 113, point (c) is replaced by the following: ‘(c) ...’ |
| --- | --- |
"""

GUIDELINE_HTML = """<html><body><main>
<h1>Guidelines on high-risk classification</h1>
<h2>Employment</h2>
<p>A CV screener that ranks applicants falls under point 4(a) of Annex III and Article 6(2).</p>
<h2>Bias</h2>
<p>Providers should examine data under Article 10(2), point (f).</p>
</main></body></html>"""
