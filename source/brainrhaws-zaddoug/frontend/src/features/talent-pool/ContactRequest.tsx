import { useState } from 'react';
import { Button } from '../../components/ui/button';
import { OperationsDialogHeader, OperationsDialogTitle, OperationsDialogDescription } from '../../components/operations';
import { useI18n } from '../../i18n/useI18n';
import { formatMessage } from '../../i18n/formatMessage';
import type { ContactDraft, PoolProfile } from './types';

export function ContactRequest({ profile, draft, onClose, onSave }: {
  profile: PoolProfile;
  draft?: ContactDraft;
  onClose: () => void;
  onSave: (draft: ContactDraft) => void;
}) {
  const { t } = useI18n();
  const [form, setForm] = useState<ContactDraft>(() => draft ?? {
    profileId: profile.id,
    recipient: profile.email ?? '',
    subject: t('pool.contactSubject'),
    message: formatMessage(t('pool.contactMessage'), { name: profile.name }),
  });
  const update = (key: keyof ContactDraft, value: string) => setForm((current) => ({ ...current, [key]: value }));
  return <>
    <OperationsDialogHeader className="pr-8 text-left">
      <OperationsDialogTitle className="leading-snug">{t('pool.contactAction')} · {profile.name}</OperationsDialogTitle>
      <OperationsDialogDescription>{t('pool.contactNote')}</OperationsDialogDescription>
    </OperationsDialogHeader>
    <form className="pool-form" onSubmit={(event) => {
      event.preventDefault();
      onSave({ ...form, recipient: form.recipient.trim(), subject: form.subject.trim(), message: form.message.trim() });
    }}>
      <label>{t('pool.recipient')}<input required type="email" autoComplete="off" value={form.recipient} onChange={(event) => update('recipient', event.target.value)} /></label>
      {!profile.email && <p className="pool-muted">{t('pool.emailNeeded')}</p>}
      <label>{t('pool.subject')}<input required maxLength={180} pattern=".*\S.*" value={form.subject} onChange={(event) => update('subject', event.target.value)} /></label>
      <label>{t('pool.message')}<textarea required minLength={10} maxLength={4000} rows={7} value={form.message} onChange={(event) => update('message', event.target.value)} /></label>
      <div className="pool-dialog-actions">
        <Button type="button" variant="outline" onClick={onClose}>{t('pool.cancel')}</Button>
        <Button type="submit" disabled={!form.subject.trim() || form.message.trim().length < 10}>{t('pool.saveDraft')}</Button>
      </div>
    </form>
  </>;
}
