// Mock regulation memory: catalog sources with versions, one document text, one diff and the
// regulation-change inbox (RC-0007 affects SYS-001 → re-run aud-sys001-r3).
import type { DocDiff, DocText, RegChange, RegSource } from './types';
import { mockTime } from '@/shared/lib/mocks/time';

const v = (
  version: number,
  fetchedAt: string,
  status: 'new' | 'changed' | 'same',
  bytes: number,
  diff?: { linesAdded: number; linesRemoved: number; changedSections: string[] },
) => ({
  version,
  fetchedAt,
  sha256: `${(version * 0x1a2b3c4d).toString(16).padStart(12, '0').slice(0, 12)}…`,
  status,
  bytes,
  diff,
});

export function buildMockSources(): RegSource[] {
  return [
    {
      id: 'ai-act',
      title: 'Regulation (EU) 2024/1689 (Artificial Intelligence Act)',
      kind: 'regulation',
      binding: true,
      status: 'final',
      publisher: 'EUR-Lex',
      url: 'https://eur-lex.europa.eu/eli/reg/2024/1689/oj',
      tags: ['ai-act'],
      documents: 3,
      versions: [v(1, mockTime('2026-11-13T21:00:00Z'), 'new', 851234)],
    },
    {
      id: 'ai-act-consolidated',
      title: 'AI Act, consolidated text',
      kind: 'consolidated',
      binding: true,
      status: 'final',
      publisher: 'EUR-Lex',
      tags: ['ai-act'],
      documents: 1,
      versions: [v(1, mockTime('2026-11-13T21:02:00Z'), 'new', 902112)],
    },
    {
      id: 'digital-omnibus-ai',
      title: 'Digital Omnibus on AI (proposal)',
      kind: 'amendment',
      binding: false,
      status: 'draft',
      publisher: 'European Commission',
      tags: ['ai-act', 'omnibus'],
      documents: 2,
      versions: [
        v(1, mockTime('2026-11-13T21:05:00Z'), 'new', 310220),
        v(2, mockTime('2026-11-14T16:00:00Z'), 'changed', 318004, {
          linesAdded: 41,
          linesRemoved: 12,
          changedSections: ['Article 1(5)', 'Art. 10(5)'],
        }),
      ],
    },
    {
      id: 'guidelines-high-risk-draft',
      title: 'Guidelines on high-risk classification and Art. 10 bias detection (draft)',
      kind: 'guideline',
      binding: false,
      status: 'draft',
      publisher: 'European Commission',
      tags: ['ai-act', 'art-6', 'art-10'],
      documents: 1,
      versions: [
        v(1, mockTime('2026-11-13T21:10:00Z'), 'new', 120440),
        v(2, mockTime('2026-11-14T17:30:00Z'), 'changed', 124980, {
          linesAdded: 9,
          linesRemoved: 3,
          changedSections: ['3.2 Bias detection and proxies'],
        }),
      ],
    },
    {
      id: 'guidelines-prohibited-practices',
      title: 'Commission Guidelines on prohibited AI practices',
      kind: 'guideline',
      binding: false,
      status: 'final',
      publisher: 'European Commission',
      tags: ['ai-act', 'art-5'],
      documents: 6,
      versions: [v(1, mockTime('2026-11-13T21:12:00Z'), 'new', 2210440)],
    },
    {
      id: 'ai-act-service-desk-faq',
      title: 'AI Act Service Desk FAQ',
      kind: 'faq',
      binding: false,
      status: 'final',
      publisher: 'European Commission',
      tags: ['ai-act', 'faq'],
      documents: 1,
      versions: [
        v(1, mockTime('2026-11-13T21:14:00Z'), 'new', 64420),
        v(2, mockTime('2026-11-14T09:00:00Z'), 'same', 64420),
      ],
    },
    {
      id: 'gdpr',
      title: 'Regulation (EU) 2016/679 (GDPR)',
      kind: 'regulation',
      binding: true,
      status: 'final',
      publisher: 'EUR-Lex',
      tags: ['gdpr'],
      documents: 1,
      versions: [v(1, mockTime('2026-11-13T21:16:00Z'), 'new', 980330)],
    },
    {
      id: 'cen-cenelec-ai-standards',
      title: 'CEN-CENELEC JTC 21 harmonised standards work programme',
      kind: 'standard',
      binding: false,
      status: 'draft',
      publisher: 'CEN-CENELEC',
      tags: ['standards'],
      documents: 1,
      versions: [v(1, mockTime('2026-11-13T21:18:00Z'), 'new', 44210)],
    },
    {
      id: 'org-fairness-thresholds',
      title: 'Org policy: fairness thresholds (org_thresholds)',
      kind: 'internal_policy',
      binding: 'internal',
      status: 'final',
      publisher: 'AI Officer',
      tags: ['internal'],
      documents: 1,
      versions: [v(1, mockTime('2026-11-10T08:00:00Z'), 'new', 3120)],
    },
  ];
}

export function mockDocText(docId: string, version?: number): DocText {
  const ver = version ?? 2;
  const extra =
    ver >= 2
      ? `\n\n### 3.2.4 Proxies for protected characteristics\n\nProviders should examine whether features that are not protected characteristics, such as **postcode or region of residence**, act as proxies for them. Counterfactual testing that changes the protected characteristic **together with the features it causally influences** is an appropriate means of examination.\n`
      : '';
  return {
    docId,
    version: ver,
    text: `# Guidelines on high-risk classification and Art. 10 bias detection (draft)

## 3. Data and data governance (Article 10)

### 3.2 Bias detection and proxies

Article 10(2)(f) requires providers to examine training, validation and testing data sets in view of possible biases that are likely to affect the health and safety of persons, have a negative impact on fundamental rights or lead to discrimination prohibited under Union law.

### 3.2.1 Scope

The examination covers the data sets **and** the behaviour of the system on them where the system is used in an area listed in Annex III.

### 3.2.3 Thresholds

The AI Act does not set numeric thresholds for fairness metrics. Providers should document the thresholds they apply and why.${extra}`,
  };
}

export function mockDocDiff(docId: string): DocDiff {
  return {
    docId,
    from: 1,
    to: 2,
    unified: `--- text/${docId}/v0001.md
+++ text/${docId}/v0002.md
@@ -14,7 +14,13 @@
 ### 3.2.3 Thresholds

-The AI Act does not set numeric thresholds for fairness metrics.
+The AI Act does not set numeric thresholds for fairness metrics. Providers should document the thresholds they apply and why.
+
+### 3.2.4 Proxies for protected characteristics
+
+Providers should examine whether features that are not protected characteristics, such as postcode or region of residence, act as proxies for them.
+Counterfactual testing that changes the protected characteristic together with the features it causally influences is an appropriate means of examination.

-## 4. Record-keeping (Article 12)
+## 4. Record-keeping and logging (Article 12)
`,
  };
}

export function buildMockChanges(): RegChange[] {
  return [
    {
      id: 'RC-0007',
      sourceId: 'guidelines-high-risk-draft',
      title: 'Art. 10 guideline adds a section on proxies for protected characteristics',
      detectedAt: mockTime('2026-11-14T17:30:00Z'),
      changeType: 'clarification',
      provisions: ['AI Act Art. 10(2)(f)', 'Guideline §3.2.4'],
      fromVersion: 1,
      toVersion: 2,
      candidateKbVersion: '2026.11.15-1',
      status: 'proposed',
      summary:
        'New §3.2.4 says postcode/region can be a proxy and names counterfactual testing with causal propagation as appropriate. Non-binding, but it sharpens how Art. 10(2)(f) is read.',
      traceId: 'tr-rc-0007',
      affected: [
        {
          systemId: 'SYS-001',
          systemName: 'CV Screener',
          path: ['Art. 10(2)(f)', 'REQ.AIA.10.2.f.bias-examination', 'F-001, F-002'],
          findings: ['F-001', 'F-002'],
          decision: 'rerun_tests',
          confidence: 0.82,
          reasoning:
            'SYS-001 uses postcode_region; F-001 already found a proxy effect. Re-run TS-003/TS-004 under the new kb_version so the evidence cites §3.2.4.',
          humanDecision: null,
          rerunAuditId: 'aud-sys001-r3',
        },
        {
          systemId: 'SYS-002',
          systemName: 'Credit Scorer',
          path: ['Art. 10(2)(f)', 'REQ.AIA.10.2.f.bias-examination', 'F-201'],
          findings: ['F-201'],
          decision: 'reinterpret_existing_evidence',
          confidence: 0.74,
          reasoning:
            'postcode_region has negligible weight (0.02); existing twin results already cover the proxy question.',
          humanDecision: null,
        },
        {
          systemId: 'SYS-003',
          systemName: 'Exam Proctoring',
          path: ['Art. 10(2)(f)'],
          findings: [],
          decision: 'no_impact',
          confidence: 0.9,
          reasoning: 'No location features in the model inputs.',
          humanDecision: null,
        },
      ],
    },
    {
      id: 'RC-0006',
      sourceId: 'digital-omnibus-ai',
      title: 'Omnibus amends the special-category data rule for bias detection (ex-Art. 10(5))',
      detectedAt: mockTime('2026-11-14T16:00:00Z'),
      changeType: 'scope_change',
      provisions: ['AI Act Art. 10(5)', 'Omnibus Art. 1(5)'],
      fromVersion: 1,
      toVersion: 2,
      candidateKbVersion: '2026.11.14-2',
      status: 'accepted',
      summary:
        'Processing special categories for bias detection moves to a general GDPR-based legal basis. Org memory MEM-0021 marked stale.',
      traceId: 'tr-rc-0006',
      affected: [
        {
          systemId: 'SYS-001',
          systemName: 'CV Screener',
          path: ['Art. 10(5)', 'REQ.AIA.10.5.special-categories'],
          findings: [],
          decision: 'new_tests_needed',
          confidence: 0.61,
          reasoning:
            'Protected attributes may now be used on real data under conditions; consider a real-data spot check.',
          humanDecision: 'reinterpret_existing_evidence',
        },
        {
          systemId: 'SYS-002',
          systemName: 'Credit Scorer',
          path: ['Art. 10(5)'],
          findings: [],
          decision: 'reinterpret_existing_evidence',
          confidence: 0.7,
          reasoning: 'Synthetic-only tests remain valid; update the documentation.',
          humanDecision: null,
        },
      ],
    },
    {
      id: 'RC-0004',
      sourceId: 'ai-act-service-desk-faq',
      title: 'FAQ: typo fixes in the GPAI section',
      detectedAt: mockTime('2026-11-14T09:00:00Z'),
      changeType: 'editorial',
      provisions: ['FAQ Q12'],
      fromVersion: 1,
      toVersion: 2,
      candidateKbVersion: '2026.11.14-1',
      status: 'accepted',
      summary: 'Editorial only.',
      affected: [],
    },
  ];
}
