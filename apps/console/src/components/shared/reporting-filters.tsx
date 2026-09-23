import { Button, Dropdown, Label } from '@/components/ui/elements';
import { ReportingDatePicker } from '@/components/shared/reporting-date-picker';
import { SearchPicker, type SearchPickerOption } from '@/components/shared/search-picker';
import { reportDimensions, type ReportDimension, type ReportPeriod } from '@/features/reporting/url';

const labels: Record<ReportDimension, string> = {
  workspace: 'Workspace',
  owner: 'Key owner',
  key: 'Inference key',
  model: 'Model',
  provider: 'Provider',
  credential: 'Provider credential',
};

const periods: Array<{ value: ReportPeriod; label: string }> = [
  { value: 'today', label: 'Today' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
  { value: 'month_to_date', label: 'Month to date' },
  { value: 'custom', label: 'Custom dates' },
];

export function ReportingFilters({
  workspaceId,
  period,
  timezone,
  startDate,
  endDate,
  selected,
  options,
  onChange,
  onClear,
}: {
  workspaceId?: string;
  period: ReportPeriod;
  timezone: string;
  startDate: string;
  endDate: string;
  selected: (dimension: ReportDimension) => string;
  options: Record<ReportDimension, SearchPickerOption[]>;
  onChange: (name: string, value: string) => void;
  onClear: () => void;
}) {
  const dimensions = reportDimensions.filter((dimension) => !workspaceId || dimension !== 'workspace');
  const timezones = [...new Set([timezone, 'UTC', ...Intl.supportedValuesOf('timeZone')])];

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="space-y-1.5">
          <Label htmlFor="report-period">Period</Label>
          <Dropdown id="report-period" value={period} onValueChange={(value) => onChange('period', value)} options={periods} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="report-timezone">Timezone</Label>
          <SearchPicker
            id="report-timezone"
            value={timezone}
            onValueChange={(value) => onChange('timezone', value)}
            options={timezones.map((value) => ({ value, label: value, searchText: value }))}
            title="Choose timezone"
            description="Dates and chart buckets use this timezone."
            searchLabel="Search timezones"
            searchPlaceholder="Search timezones"
            emptyMessage="No matching timezone."
          />
        </div>
        {period === 'custom' && (
          <>
            <div className="space-y-1.5">
              <Label htmlFor="report-start-date">Start date</Label>
              <ReportingDatePicker
                id="report-start-date"
                label="Start date"
                value={startDate}
                onValueChange={(value) => onChange('start_date', value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="report-end-date">End date</Label>
              <ReportingDatePicker id="report-end-date" label="End date" value={endDate} onValueChange={(value) => onChange('end_date', value)} />
            </div>
          </>
        )}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {dimensions.map((dimension) => (
          <div key={dimension} className="space-y-1.5">
            <Label htmlFor={`report-${dimension}`}>{labels[dimension]}</Label>
            <SearchPicker
              id={`report-${dimension}`}
              value={selected(dimension)}
              onValueChange={(value) => onChange(`${dimension === 'owner' ? 'owner' : dimension}_id`, value)}
              options={[{ value: '', label: `All ${labels[dimension].toLowerCase()}s`, searchText: 'all' }, ...options[dimension]]}
              title={`Choose ${labels[dimension].toLowerCase()}`}
              description="Choose a value recorded in usage history."
              searchLabel={`Search ${labels[dimension].toLowerCase()}s`}
              searchPlaceholder={`Search ${labels[dimension].toLowerCase()}s`}
              emptyMessage="No matching values."
            />
          </div>
        ))}
      </div>
      {dimensions.some((dimension) => selected(dimension)) && (
        <div className="flex flex-wrap items-center gap-2">
          {dimensions
            .filter((dimension) => selected(dimension))
            .map((dimension) => (
              <Button key={dimension} variant="secondary" size="sm" onClick={() => onChange(`${dimension}_id`, '')}>
                {labels[dimension]}: {options[dimension].find((option) => option.value === selected(dimension))?.label ?? selected(dimension)} ×
              </Button>
            ))}
          <Button variant="ghost" size="sm" onClick={onClear}>
            Clear selections
          </Button>
        </div>
      )}
    </div>
  );
}
