import { Field, FormGrid, Select, useTranslation } from "@/sdk";

import { usePlanDetail, usePlans } from "../catalog";

export interface PlanChoiceValue {
  plan: string;
  interval: string;
  currency: string;
}

/**
 * Plan, billing interval and currency pickers. The intervals and currencies offered are the ones the chosen plan has a
 * price for right now; leaving them empty lets the platform choose its defaults.
 */
export function PlanChoice({ value, onChange, optionalPlan }: { value: PlanChoiceValue; onChange: (next: PlanChoiceValue) => void; optionalPlan?: boolean }) {
  const { t } = useTranslation("operator");
  const plans = usePlans();
  const detail = usePlanDetail(value.plan);
  const prices = (detail.data?.current_prices ?? []).filter((p) => !p.withdrawn);
  const intervals = [...new Set(prices.map((p) => p.interval))];
  const currencies = [...new Set(prices.filter((p) => !value.interval || p.interval === value.interval).map((p) => p.currency))];
  return (
    <>
      <Field label={t("common.plan")} required={!optionalPlan}>
        <Select value={value.plan} onChange={(e) => onChange({ plan: e.target.value, interval: "", currency: "" })}>
          <option value="">{optionalPlan ? t("common.keepPlan") : t("common.choosePlan")}</option>
          {(plans.data ?? []).filter((p) => p.status === "active").map((p) => <option key={p.code} value={p.code}>{p.name} ({p.code})</option>)}
        </Select>
      </Field>
      {value.plan && (
        <FormGrid>
          <Field label={t("common.interval")}>
            <Select value={value.interval} onChange={(e) => onChange({ ...value, interval: e.target.value, currency: "" })}>
              <option value="">{t("common.platformDefault")}</option>
              {intervals.map((i) => <option key={i} value={i}>{t(`interval.${i}`)}</option>)}
            </Select>
          </Field>
          <Field label={t("common.currency")}>
            <Select value={value.currency} onChange={(e) => onChange({ ...value, currency: e.target.value })}>
              <option value="">{t("common.platformDefault")}</option>
              {currencies.map((c) => <option key={c} value={c}>{c}</option>)}
            </Select>
          </Field>
        </FormGrid>
      )}
    </>
  );
}
