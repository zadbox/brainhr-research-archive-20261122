import { useState } from 'react';
import { useI18n } from '../../i18n/useI18n';
import { formatMessage } from '../../i18n/formatMessage';
import { Button } from '../../components/ui/button';
import { OperationsDialogHeader, OperationsDialogTitle, OperationsDialogDescription } from '../../components/operations';
import type { InterviewDraft, PoolProfile } from './types';

export function InterviewRequest({ profile, draft, onClose, onSave }: { profile: PoolProfile; draft?: InterviewDraft; onClose: () => void; onSave: (draft: InterviewDraft) => void }) {
  const { language, t } = useI18n();
  const [form, setForm] = useState<InterviewDraft>(() => draft ?? {
    profileId: profile.id, recipient: profile.email ?? '', project: '', duration: '30',
    subject: formatMessage(t('pool.defaultSubject'), { role: profile.title[language] }),
    message: formatMessage(t('pool.defaultMessage'), { name: profile.name }),
  });
  const update = (key: keyof InterviewDraft, value: string) => setForm((current) => ({ ...current, [key]: value }));
  return <>
      <OperationsDialogHeader className="pr-8 text-left"><OperationsDialogTitle className="leading-snug">{t('pool.requestTitle')} · {profile.name}</OperationsDialogTitle><OperationsDialogDescription>{t('pool.requestNote')}</OperationsDialogDescription></OperationsDialogHeader>
      <form className="pool-form" onSubmit={(event) => { event.preventDefault(); onSave({ ...form, recipient: form.recipient.trim(), subject: form.subject.trim(), project: form.project.trim(), message: form.message.trim() }); }}>
        <label>{t('pool.recipient')}<input required type="email" value={form.recipient} onChange={(event) => update('recipient', event.target.value)} autoComplete="off" /></label>
        {!profile.email && <p className="pool-muted">{t('pool.emailNeeded')}</p>}
        <label>{t('pool.subject')}<input required maxLength={180} pattern=".*\S.*" value={form.subject} onChange={(event) => update('subject', event.target.value)} /></label>
        <div className="pool-form-columns"><label>{t('pool.project')}<input required maxLength={120} pattern=".*\S.*" placeholder={t('pool.projectPlaceholder')} value={form.project} onChange={(event) => update('project', event.target.value)} /></label>
        <label>{t('pool.duration')}<select value={form.duration} onChange={(event) => update('duration', event.target.value)}>{['15', '30', '45', '60'].map((duration) => <option key={duration} value={duration}>{formatMessage(t('pool.minutes'), { count: duration })}</option>)}</select></label></div>
        <label>{t('pool.message')}<textarea required minLength={10} maxLength={4000} rows={7} value={form.message} onChange={(event) => update('message', event.target.value)} /></label>
        <div className="pool-dialog-actions"><Button type="button" variant="outline" onClick={onClose}>{t('pool.cancel')}</Button><Button type="submit" disabled={!form.message.trim() || !form.subject.trim() || !form.project.trim()}>{t('pool.saveDraft')}</Button></div>
      </form>
  </>;
}
