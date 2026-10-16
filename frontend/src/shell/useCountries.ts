import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/sdk";

import { chooseCountries, type Country, currenciesOf, fromServer } from "./countries";

/**
 * The countries the sign-up form offers: from the server (so country packs can refine an entry), with the built-in
 * static list while loading or when the server cannot be reached.
 */
export function useCountries(): { countries: readonly Country[]; currencies: string[]; byCode: (code: string) => Country | undefined; fromServer: boolean } {
  const query = useQuery({
    queryKey: ["countries"],
    queryFn: async () => (await unwrap(api.GET("/api/v1/countries"))).map(fromServer),
    staleTime: 10 * 60_000,
    retry: 1,
  });
  const countries = chooseCountries(query.data);
  return {
    countries,
    currencies: currenciesOf(countries),
    byCode: (code: string) => countries.find((c) => c.code === code),
    fromServer: !!query.data && query.data.length > 0,
  };
}
