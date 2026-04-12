import type { FilingUsed } from '../types';

export function CompanyChip({ filing }: { filing: FilingUsed }) {
  const label = [filing.ticker, filing.filing_type, filing.period_label]
    .filter(Boolean)
    .join(' \u00b7 ');

  return <span className="company-chip">{label}</span>;
}
