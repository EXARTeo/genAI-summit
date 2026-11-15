import { ArrowLeft, ArrowRight, Check, Wand2 } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useSystems } from '@/features/systems/hooks/useSystems';
import { systemRoutes } from '@/features/systems/lib/routes';
import { ApiError } from '@/shared/lib/api';
import { Button, Card, PageHeader, Stepper, toast, type StepState } from '@/shared/ui';
import { useRegisterSystem } from '../hooks/useRegisterSystem';
import {
  EMPTY_FORM,
  STEPS,
  exampleForm,
  firstInvalidStep,
  mergeFiles,
  nextSystemId,
  stepErrors,
  type StepId,
  type WizardForm,
} from '../lib/wizard';
import { RegisteredScreen } from './wizard_parts/RegisteredScreen';
import { DeploymentStep, DocumentsStep, IdentityStep, PurposeStep, ReviewStep } from './wizard_parts/Steps';

const DESCRIPTIONS: Record<StepId, string> = {
  identity: 'Name the system and say how you got it.',
  purpose: 'What it does and what it is for: the classifier reads this first.',
  deployment: 'Where it runs, who it affects, and what else it does.',
  documents: 'Anything that describes the system. You can add more later in the Folder tab.',
  review: 'Check everything before the system is created.',
};

/**
 * "Register a system" (plan 02 §5): five short steps for the PM, documents only. Creates a
 * `draft` system with its card and documents; the engineer adds the pipeline later (Plugins tab).
 */
export function RegisterWizard() {
  const systems = useSystems();
  const taken = useMemo(() => (systems.data ?? []).map((s) => s.id), [systems.data]);
  const [form, setForm] = useState<WizardForm>(EMPTY_FORM);
  const [files, setFiles] = useState<File[]>([]);
  const [step, setStep] = useState(0);
  const [reached, setReached] = useState(0);
  const [tried, setTried] = useState<Set<number>>(new Set());
  const [done, setDone] = useState<{ id: string; name: string } | null>(null);
  const register = useRegisterSystem();
  const heading = useRef<HTMLHeadingElement>(null);

  // Propose the next free id once the list is known (editable; clearing it does not refill it).
  const proposed = useRef(false);
  useEffect(() => {
    if (!systems.data || proposed.current) return;
    proposed.current = true;
    setForm((f) => (f.id ? f : { ...f, id: nextSystemId(taken) }));
  }, [systems.data, taken]);

  const current = STEPS[step];
  const errors = tried.has(step) ? stepErrors(current.id, form, taken) : {};
  const set = <K extends keyof WizardForm>(key: K, value: WizardForm[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const go = (i: number) => {
    setStep(i);
    setReached((r) => Math.max(r, i));
    heading.current?.focus();
  };

  const next = () => {
    if (Object.keys(stepErrors(current.id, form, taken)).length) {
      setTried((t) => new Set(t).add(step));
      return;
    }
    go(step + 1);
  };

  const fillExample = () => {
    setForm(exampleForm(form.id && !taken.includes(form.id) ? form.id : nextSystemId(taken)));
    if (!files.some((f) => f.name === 'system-specification.md')) {
      const spec = new File([EXAMPLE_SPEC], 'system-specification.md', { type: 'text/markdown' });
      setFiles((fs) => mergeFiles(fs, [spec]));
    }
    setTried(new Set());
    toast.success('Example filled: CV Parser');
  };

  const create = () => {
    const bad = firstInvalidStep(form, taken);
    if (bad >= 0) {
      setTried((t) => new Set(t).add(bad));
      go(bad);
      return;
    }
    register.mutate(
      { form, files },
      {
        onSuccess: (id) => setDone({ id, name: form.name.trim() }),
        onError: (e) =>
          toast.error(
            e instanceof ApiError && e.status === 409
              ? `${form.id} already exists. Pick another id.`
              : e instanceof Error
                ? e.message
                : 'Could not register the system',
          ),
      },
    );
  };

  const reset = () => {
    setForm({ ...EMPTY_FORM, id: nextSystemId([...taken, done?.id ?? ''].filter(Boolean)) });
    setFiles([]);
    setStep(0);
    setReached(0);
    setTried(new Set());
    setDone(null);
    register.reset();
  };

  const stepState = (i: number): StepState =>
    i === step ? 'active' : i < reached || i < step ? 'done' : 'pending';

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        breadcrumbs={[{ label: 'Systems', to: systemRoutes.list() }, { label: 'Register' }]}
        title="Register a system"
        description="Describe the system and attach its documents. No models needed: the AI engineer builds the pipeline later."
        actions={
          !done && (
            <Button variant="secondary" size="sm" leftIcon={<Wand2 />} onClick={fillExample}>
              Fill example
            </Button>
          )
        }
      />

      {done ? (
        <RegisteredScreen systemId={done.id} name={done.name} onAnother={reset} />
      ) : (
        <>
          <nav aria-label="Registration steps" className="mb-5 [&_.text-shimmer]:text-primary">
            <Stepper
              orientation="horizontal"
              steps={STEPS.map((s, i) => ({ id: s.id, title: s.title, state: stepState(i) }))}
              onStepClick={(id) => {
                const i = STEPS.findIndex((s) => s.id === id);
                if (i <= reached) go(i);
              }}
            />
          </nav>

          <Card className="overflow-hidden">
            <div className="border-b border-border px-4 py-4 sm:px-6">
              <div className="text-2xs font-medium uppercase tracking-wider text-muted">
                Step {step + 1} of {STEPS.length}
              </div>
              <h2 ref={heading} tabIndex={-1} className="mt-0.5 text-base font-semibold focus:outline-none">
                {current.id === 'deployment' ? 'Deployment and people' : current.title}
              </h2>
              <p className="text-sm text-muted">{DESCRIPTIONS[current.id]}</p>
            </div>

            <form
              className="px-4 py-5 sm:px-6"
              noValidate
              onSubmit={(e) => {
                e.preventDefault();
                if (current.id === 'review') create();
                else next();
              }}
            >
              {current.id === 'identity' && <IdentityStep form={form} set={set} errors={errors} />}
              {current.id === 'purpose' && <PurposeStep form={form} set={set} errors={errors} />}
              {current.id === 'deployment' && <DeploymentStep form={form} set={set} errors={errors} />}
              {current.id === 'documents' && (
                <DocumentsStep
                  files={files}
                  onAdd={(added) => setFiles((fs) => mergeFiles(fs, added))}
                  onRemove={(name) => setFiles((fs) => fs.filter((f) => f.name !== name))}
                />
              )}
              {current.id === 'review' && (
                <ReviewStep
                  form={form}
                  files={files}
                  goTo={(id) => go(STEPS.findIndex((s) => s.id === id))}
                />
              )}

              <div className="mt-6 flex flex-col-reverse gap-2 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-between">
                <Button
                  type="button"
                  variant="ghost"
                  leftIcon={<ArrowLeft />}
                  onClick={() => go(step - 1)}
                  disabled={step === 0 || register.isPending}
                  className={step === 0 ? 'invisible' : ''}
                >
                  Back
                </Button>
                <div className="flex flex-col items-stretch gap-1 sm:items-end">
                  {current.id === 'review' ? (
                    <Button type="submit" leftIcon={<Check />} loading={register.isPending}>
                      {register.isPending && register.progress ? register.progress.label : 'Create system'}
                    </Button>
                  ) : (
                    <Button type="submit" rightIcon={<ArrowRight />}>
                      {current.id === 'documents' && files.length === 0 ? 'Skip' : 'Next'}
                    </Button>
                  )}
                </div>
              </div>
            </form>
          </Card>
        </>
      )}
    </div>
  );
}

/** The example's specification (what the demo uploads with "Fill example"). */
const EXAMPLE_SPEC = `# CV Parser: system specification

## 1. Purpose
Turns incoming CVs (PDF, DOCX) into structured candidate records for the applicant
tracking system, so recruiters do not retype them.

## 2. Output
Fields: name, contact details, work history (employer, role, dates), education,
skills, languages. Each field carries the text span it came from.

## 3. What it does not do
It does not score, rank, filter, shortlist or reject candidates. Records are listed
in the order the CVs arrived. Recruiters decide whom to contact.

## 4. Human oversight
Recruiters see the original CV next to the extracted fields and correct any field
before saving. Nothing is saved without a recruiter.

## 5. Model
A fine-tuned document-layout model plus rules for dates and phone numbers. No
inference about the person (no personality, fit or performance prediction).
`;
