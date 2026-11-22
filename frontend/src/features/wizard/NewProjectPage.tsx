import { useRef, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Paperclip, Plus, Sparkles, X } from 'lucide-react';
import { api, errorMessage } from '../../api/client';
import type { BriefOut, MemberIn, Project, QuestionsOut, Role } from '../../api/types';
import AppShell from '../../layout/AppShell';
import { ROLE_LABEL, splitSkills } from '../../lib/format';
import { useMe } from '../auth/useMe';
import { keys } from '../projects/queries';

interface PersonRow {
  key: string;
  email: string;
  name: string;
  skills: string;
  hours: string;
  role: Role;
}

const blankPerson = (): PersonRow => ({ key: crypto.randomUUID(), email: '', name: '', skills: '', hours: '', role: 'member' });

/** Step 1 (describe) and step 2 (the AI's questions). Planning itself happens on /projects/:id/plan. */
export default function NewProjectPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const fileInput = useRef<HTMLInputElement>(null);

  const [name, setName] = useState('');
  const [brief, setBrief] = useState('');
  const [deadline, setDeadline] = useState('');
  const [mySkills, setMySkills] = useState<string | null>(null);
  const [myHours, setMyHours] = useState<string | null>(null);
  const [people, setPeople] = useState<PersonRow[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [questions, setQuestions] = useState<string[] | null>(null);
  const [answers, setAnswers] = useState<string[]>([]);

  const toPlan = (id: string, withAnswers: boolean) =>
    navigate(`/projects/${id}/plan`, {
      state: { answers: withAnswers && questions ? questions.map((question, i) => ({ question, answer: answers[i] ?? '' })) : [] },
    });

  const attach = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append('file', file);
      return api.post<BriefOut>('/api/briefs/extract', form).then((r) => r.data.text);
    },
    onSuccess: (text) => setBrief((current) => (current.trim() ? `${current.trim()}\n\n${text}` : text)),
  });

  const start = useMutation({
    mutationFn: async () => {
      let id = projectId;
      if (!id) {
        if (me && (mySkills !== null || myHours !== null)) {
          await api.patch('/api/me', {
            skills: splitSkills(mySkills ?? me.skills.join(', ')),
            weekly_hours: Number(myHours ?? me.weekly_hours),
          });
        }
        const members: MemberIn[] = people
          .filter((p) => p.email.trim())
          .map((p) => ({
            email: p.email.trim(),
            name: p.name.trim() || null,
            role: p.role,
            skills: splitSkills(p.skills),
            weekly_hours: p.hours ? Number(p.hours) : null,
          }));
        const project = await api.post<Project>('/api/projects', { name, brief, deadline: deadline || null, members });
        id = project.data.id;
        setProjectId(id); // a retry asks the questions again without making a second project
        qc.invalidateQueries({ queryKey: keys.projects });
      }
      const res = await api.post<QuestionsOut>(`/api/projects/${id}/plan/questions`);
      return { id, questions: res.data.questions };
    },
    onSuccess: ({ id, questions: asked }) => {
      if (asked.length === 0) {
        navigate(`/projects/${id}/plan`, { state: { answers: [] } });
        return;
      }
      setQuestions(asked);
      setAnswers(asked.map(() => ''));
    },
  });

  const update = (key: string, field: keyof PersonRow, value: string) =>
    setPeople((rows) => rows.map((row) => (row.key === key ? { ...row, [field]: value } : row)));

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    start.mutate();
  };

  if (questions) {
    return (
      <AppShell title="A few questions" subtitle="Answers make the plan fit. Skip any you'd rather not answer.">
        <section className="clv-card max-w-3xl gap-5">
          <div className="clv-assist-title">
            <Sparkles aria-hidden="true" className="text-secondary-text" /> Clovio asks
          </div>
          {questions.map((question, i) => (
            <div key={question}>
              <label htmlFor={`answer-${i}`} className="clv-field-label">{question}</label>
              <input
                id={`answer-${i}`}
                className="clv-input"
                value={answers[i]}
                onChange={(e) => setAnswers((all) => all.map((a, j) => (j === i ? e.target.value : a)))}
              />
            </div>
          ))}
          <div className="flex flex-wrap gap-2">
            <button type="button" className="clv-btn clv-btn-primary" onClick={() => toPlan(projectId!, true)}>
              <Sparkles aria-hidden="true" /> Make the plan
            </button>
            <button type="button" className="clv-btn clv-btn-secondary bg-ground" onClick={() => toPlan(projectId!, false)}>
              Skip the questions
            </button>
          </div>
        </section>
      </AppShell>
    );
  }

  return (
    <AppShell title="New project" subtitle="Describe the work. Clovio drafts the plan and gives each task to whoever can finish it soonest.">
      <form className="flex max-w-3xl flex-col gap-4" onSubmit={onSubmit}>
        <section className="clv-card gap-5">
          <div>
            <label htmlFor="brief" className="clv-field-label">What's the project?</label>
            <textarea
              id="brief"
              required
              rows={8}
              className="clv-input"
              placeholder="Paste the brief, or describe the goal, the scale, what's already done and any fixed dates."
              value={brief}
              onChange={(e) => setBrief(e.target.value)}
            />
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <input
                ref={fileInput}
                type="file"
                accept=".pdf,.docx,.txt,.md"
                className="clv-sr"
                aria-label="Attach a brief"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) attach.mutate(file);
                  e.target.value = '';
                }}
              />
              <button type="button" className="clv-btn clv-btn-outline" onClick={() => fileInput.current?.click()} disabled={attach.isPending}>
                <Paperclip aria-hidden="true" /> {attach.isPending ? 'Reading the file' : 'Attach a brief'}
              </button>
              <span className="text-caption text-ink-muted">PDF, Word or text. Its text appears above so you can see what Clovio reads.</span>
            </div>
            {attach.isError && <p role="alert" className="mt-2 text-sm text-danger-text">{errorMessage(attach.error, "Couldn't read that file.")}</p>}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="deadline" className="clv-field-label">Deadline or event date</label>
              <input id="deadline" type="date" className="clv-input" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
            </div>
            <div>
              <label htmlFor="name" className="clv-field-label">Project name</label>
              <input id="name" className="clv-input" placeholder="Leave blank and Clovio suggests one" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
          </div>
        </section>

        <section className="clv-card gap-4">
          <div>
            <h2 className="clv-card-title">People</h2>
            <p className="clv-card-sub">Skills and hours decide who gets what. People you add can sign in later; they can be given work now.</p>
          </div>

          {me && (
            <div className="grid gap-3 rounded-lg bg-surface-sunken p-3 sm:grid-cols-[1fr_1fr_8rem]">
              <div className="text-[13px]">
                <div className="font-semibold">{me.name} (you)</div>
                <div className="text-ink-muted">Owner</div>
              </div>
              <input aria-label="Your skills" className="clv-input" placeholder="Your skills, comma-separated" value={mySkills ?? me.skills.join(', ')} onChange={(e) => setMySkills(e.target.value)} />
              <input aria-label="Your hours a week" type="number" min={0} max={100} className="clv-input" placeholder="h / week" value={myHours ?? String(me.weekly_hours)} onChange={(e) => setMyHours(e.target.value)} />
            </div>
          )}

          {people.map((p) => (
            <div key={p.key} className="grid gap-2 rounded-lg bg-surface-sunken p-3 sm:grid-cols-[1.4fr_1fr_1.4fr_6rem_8rem_auto]">
              <input aria-label="Email" type="email" required className="clv-input" placeholder="Email" value={p.email} onChange={(e) => update(p.key, 'email', e.target.value)} />
              <input aria-label="Name" className="clv-input" placeholder="Name" value={p.name} onChange={(e) => update(p.key, 'name', e.target.value)} />
              <input aria-label="Skills" className="clv-input" placeholder="Skills, comma-separated" value={p.skills} onChange={(e) => update(p.key, 'skills', e.target.value)} />
              <input aria-label="Hours a week" type="number" min={0} max={100} className="clv-input" placeholder="h / wk" value={p.hours} onChange={(e) => update(p.key, 'hours', e.target.value)} />
              <select aria-label="Role" className="clv-input" value={p.role} onChange={(e) => update(p.key, 'role', e.target.value)}>
                {(['member', 'manager', 'owner'] as Role[]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
              </select>
              <button type="button" className="clv-icon-btn bg-ground" aria-label="Remove this person" onClick={() => setPeople((rows) => rows.filter((row) => row.key !== p.key))}>
                <X aria-hidden="true" />
              </button>
            </div>
          ))}
          <button type="button" className="clv-btn clv-btn-outline self-start" onClick={() => setPeople((rows) => [...rows, blankPerson()])}>
            <Plus aria-hidden="true" /> Add a person
          </button>
        </section>

        {start.isError && (
          <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-danger-text">
            {errorMessage(start.error, "Couldn't start planning.")}
            {projectId && (
              <button type="button" className="font-semibold text-primary hover:text-primary-strong" onClick={() => toPlan(projectId, false)}>
                Skip the questions
              </button>
            )}
          </div>
        )}
        <button type="submit" className="clv-btn clv-btn-primary self-start" disabled={start.isPending}>
          <Sparkles aria-hidden="true" /> {start.isPending ? 'Reading the brief' : 'Plan it with Clovio'}
        </button>
      </form>
    </AppShell>
  );
}
