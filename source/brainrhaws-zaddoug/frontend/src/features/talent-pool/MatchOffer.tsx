import { useState } from 'react';
import { Button } from '../../components/ui/button';
import { OperationsDialogHeader, OperationsDialogTitle, OperationsDialogDescription, SystemState } from '../../components/operations';
import { useI18n } from '../../i18n/useI18n';
import type { PoolOffer, PoolProfile } from './types';

export function MatchOffer({ profile, offers, selectedOfferId, onClose, onSave }: {
  profile: PoolProfile;
  offers: PoolOffer[];
  selectedOfferId?: string;
  onClose: () => void;
  onSave: (offerId: string) => void;
}) {
  const { language, t } = useI18n();
  const [offerId, setOfferId] = useState(selectedOfferId ?? '');
  const offer = offers.find((item) => item.id === offerId);
  return <>
    <OperationsDialogHeader className="pr-8 text-left">
      <OperationsDialogTitle className="leading-snug">{t('pool.matchTitle')} · {profile.name}</OperationsDialogTitle>
      <OperationsDialogDescription>{t('pool.matchNote')}</OperationsDialogDescription>
    </OperationsDialogHeader>
    {offers.length === 0 ? <SystemState kind="empty" title={t('pool.noOffers')} description={t('pool.noOffersHelp')} /> :
      <form className="pool-form" onSubmit={(event) => { event.preventDefault(); if (offer) onSave(offer.id); }}>
        <label>{t('pool.chooseOffer')}
          <select required value={offerId} onChange={(event) => setOfferId(event.target.value)}>
            <option value="" disabled>{t('pool.chooseOfferPlaceholder')}</option>
            {offers.map((item) => <option key={item.id} value={item.id}>{item.title[language]} · {item.company}</option>)}
          </select>
        </label>
        {offer && <section className="pool-offer-summary" aria-label={t('pool.selectedOffer')}>
          <p className="pool-kicker">{t('pool.selectedOffer')}</p>
          <h3>{offer.title[language]}</h3>
          <p className="pool-muted">{offer.company} · {offer.location}</p>
          <p className="pool-copy">{offer.description[language]}</p>
          <p className="pool-kicker">{t('pool.requiredSkills')}</p>
          <div className="pool-card-skills">{offer.skills.map((skill) => <span className="pool-skill-tag" key={skill}>{skill}</span>)}</div>
          <p className="pool-muted">{t('pool.cv')} : {profile.sourceCv.filename}</p>
        </section>}
        <div className="pool-dialog-actions">
          <Button type="button" variant="outline" onClick={onClose}>{t('pool.cancel')}</Button>
          <Button type="submit" disabled={!offer}>{t('pool.keepMatchSelection')}</Button>
        </div>
      </form>}
  </>;
}
